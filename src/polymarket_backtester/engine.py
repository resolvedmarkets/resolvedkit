"""The event loop: replay each market's books in time order, execute orders against the book, settle."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .fees import rate_for
from .fills import walk_buy, walk_sell
from .models import DOWN, SIDES, UP, Book, Fill, Market, Position

FillModel = Literal["book", "mid"]


@dataclass
class Order:
    side: str
    action: str  # BUY or SELL
    submit_ts: int
    usd: float | None = None  # BUY size
    shares: float | None = None  # SELL size; None = the whole position
    limit: float | None = None  # max price for BUY, min price for SELL


@dataclass
class Rejection:
    order: Order
    reason: str  # placeholder_book, no_liquidity, price_limit, no_position, invalid_size


@dataclass
class MarketResult:
    market: Market
    fills: list[Fill] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    settlement: float = 0.0  # USDC received for shares held at resolution
    resolved: bool = True

    @property
    def fees(self) -> float:
        return sum(f.fee for f in self.fills)

    @property
    def pnl(self) -> float:
        cash = sum(-f.notional if f.action == "BUY" else f.notional for f in self.fills)
        return cash + self.settlement - self.fees

    @property
    def traded(self) -> bool:
        return bool(self.fills)


class Context:
    """What a strategy sees and does during one market."""

    def __init__(self, market: Market, engine: "Backtester"):
        self.market = market
        self._engine = engine
        self.now = 0
        self.books: dict[str, Book] = {}
        self.positions = {s: Position(s) for s in SIDES}
        self.pending: list[Order] = []
        self.state: dict = {}  # scratch space for the strategy, reset per market

    @property
    def seconds_to_end(self) -> float:
        return (self.market.end_ts - self.now) / 1000

    def book(self, side: str) -> Book | None:
        return self.books.get(side)

    def position(self, side: str) -> Position:
        return self.positions[side]

    def buy(self, side: str, usd: float, max_price: float | None = None) -> None:
        """Marketable buy for `usd` of the side's token, filled after the engine's latency."""
        self.pending.append(Order(side, "BUY", self.now, usd=usd, limit=max_price))

    def pending_orders(self, side: str | None = None) -> list[Order]:
        """Orders placed but not yet filled or rejected."""
        return [o for o in self.pending if side is None or o.side == side]

    def sell(self, side: str, shares: float | None = None, min_price: float | None = None) -> None:
        """Marketable sell of `shares` (default: the whole position)."""
        self.pending.append(Order(side, "SELL", self.now, shares=shares, limit=min_price))


class Strategy:
    """Subclass and override `on_book`. Called for every snapshot of either side, in time order."""

    def on_start(self, ctx: Context) -> None:
        pass

    def on_book(self, ctx: Context, book: Book) -> None:
        raise NotImplementedError

    def on_end(self, ctx: Context) -> None:
        pass


class Backtester:
    def __init__(self, data, strategy: Strategy, *, latency_ms: int = 250, fill_model: FillModel = "book",
                 fee_rate: float | None = None, skip_placeholder_books: bool = True):
        """
        latency_ms: an order fills against the book standing `latency_ms` after it was placed, i.e. the
            latest snapshot of that token at or before that moment.
        fill_model: "book" walks the ladder (default). "mid" fills the whole order at the mid price with no
            depth limit — unrealistic, provided only to measure how much a mid-price backtest overstates.
        fee_rate: override Polymarket's taker rate for the market's category.
        skip_placeholder_books: reject orders against 0.01/0.99 placeholder books.
        """
        self.data, self.strategy = data, strategy
        self.latency_ms, self.fill_model = latency_ms, fill_model
        self.fee_rate, self.skip_placeholder_books = fee_rate, skip_placeholder_books

    def run(self, markets: list[Market] | None = None) -> "Results":
        from .metrics import Results

        results = [self._run_market(m) for m in (markets if markets is not None else self.data.markets())]
        return Results(results, fill_model=self.fill_model, latency_ms=self.latency_ms)

    def _run_market(self, market: Market) -> MarketResult:
        res = MarketResult(market)
        ctx = Context(market, self)
        rate = self.fee_rate if self.fee_rate is not None else rate_for(market.category)
        self.strategy.on_start(ctx)
        for book in self.data.books(market.market_id):
            # Orders due before this snapshot fill against the books standing at their due time...
            self._execute_due(ctx, res, rate, before=book.ts)
            ctx.now = book.ts
            ctx.books[book.side] = book
            # ...and orders due exactly now see this snapshot too.
            self._execute_due(ctx, res, rate, before=book.ts + 1)
            self.strategy.on_book(ctx, book)
        self.strategy.on_end(ctx)
        # Orders still pending after the last snapshot fill against the final standing books.
        self._execute_due(ctx, res, rate, before=None)
        for side in SIDES:
            pos = ctx.positions[side]
            if pos.shares > 1e-9:
                payout = market.payout_for(side)
                if payout is None:  # unresolved: mark at the last mid so PnL is still defined
                    res.resolved = False
                    last = ctx.books.get(side)
                    payout = last.mid if last else 0.0
                res.settlement += pos.shares * payout
        return res

    def _execute_due(self, ctx: Context, res: MarketResult, rate: float, before: int | None) -> None:
        """Execute pending orders whose due time is earlier than `before` (all of them if None)."""
        still = []
        for o in ctx.pending:
            due = o.submit_ts + self.latency_ms
            if before is not None and due >= before:
                still.append(o)
                continue
            book = ctx.books.get(o.side)
            if book is None:
                res.rejections.append(Rejection(o, "no_liquidity"))
                continue
            if self.skip_placeholder_books and book.is_placeholder:
                res.rejections.append(Rejection(o, "placeholder_book"))
                continue
            pos = ctx.positions[o.side]
            fill = self._fill(o, pos, book, rate, due)
            if isinstance(fill, str):
                res.rejections.append(Rejection(o, fill))
                continue
            if o.action == "BUY":
                pos.shares += fill.shares
                pos.cost += fill.notional
            else:
                avg_cost = pos.cost / pos.shares if pos.shares else 0.0
                pos.cost -= avg_cost * fill.shares
                pos.shares -= fill.shares
            pos.fees += fill.fee
            pos.fills.append(fill)
            res.fills.append(fill)
        ctx.pending = still

    def _fill(self, o: Order, pos: Position, book: Book, rate: float, ts: int) -> Fill | str:
        if o.action == "BUY" and (o.usd is None or o.usd <= 0):
            return "invalid_size"
        if o.action == "SELL":
            want = pos.shares if o.shares is None else min(o.shares, pos.shares)
            if want <= 1e-9:
                return "no_position"
        if not (book.asks if o.action == "BUY" else book.bids):
            return "no_liquidity"  # same rule for both fill models, so --compare-mid compares like with like
        if self.fill_model == "mid":
            price = book.mid
            if o.action == "BUY":
                if o.limit is not None and price > o.limit:
                    return "price_limit"
                shares = o.usd / price if price > 0 else 0.0
            else:
                if o.limit is not None and price < o.limit:
                    return "price_limit"
                shares = want
            fee = round(shares * rate * price * (1 - price), 5)
            return Fill(o.side, o.action, ts, shares, price, fee, book.mid)
        walk = walk_buy(book.asks, o.usd, o.limit) if o.action == "BUY" else walk_sell(book.bids, want, o.limit)
        if walk.shares <= 1e-9:
            return "price_limit"
        return Fill(o.side, o.action, ts, walk.shares, walk.avg_price, walk.fee(rate), book.mid, walk.depth_limited)


def other(side: str) -> str:
    return DOWN if side == UP else UP
