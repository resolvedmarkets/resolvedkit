"""Core data types. Prices are probabilities in [0, 1]; sizes are shares; money is USDC."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

UP, DOWN = "UP", "DOWN"
SIDES = (UP, DOWN)


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass(frozen=True)
class Book:
    """One order-book snapshot for one outcome token.

    `bids` are sorted best (highest) first, `asks` best (lowest) first. An empty side means
    nobody was quoting it, which happens near settlement.
    """

    ts: int  # epoch milliseconds, UTC
    side: str  # UP or DOWN: UP is the market's first outcome (e.g. "Up" or "Yes")
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float:
        """Polymarket's convention: a missing bid counts as 0 and a missing ask as 1."""
        return ((self.best_bid or 0.0) + (self.best_ask if self.best_ask is not None else 1.0)) / 2

    @property
    def two_sided(self) -> bool:
        return bool(self.bids) and bool(self.asks)

    @property
    def is_placeholder(self) -> bool:
        """A freshly listed market often shows a 0.01 bid / 0.99 ask before real quoting starts.

        Trading against it in a backtest buys at 0.99 or sells at 0.01, which no one would do.
        """
        return (self.best_bid or 0.0) <= 0.01 and (self.best_ask if self.best_ask is not None else 1.0) >= 0.99


@dataclass(frozen=True)
class Market:
    market_id: str
    question: str
    category: str
    end_ts: int  # epoch ms: expiry for crypto up/down, kickoff for sports
    outcomes: tuple[str, str] = ("Up", "Down")
    # Settlement value per share of each side, e.g. (1.0, 0.0). None while unresolved.
    payout: tuple[float, float] | None = None
    start_ts: int | None = None  # window start for recurring markets, when known
    slug: str = ""
    timeframe: str = ""

    def payout_for(self, side: str) -> float | None:
        if self.payout is None:
            return None
        return self.payout[0] if side == UP else self.payout[1]


@dataclass
class Fill:
    side: str  # UP or DOWN token
    action: str  # BUY or SELL
    ts: int
    shares: float
    avg_price: float
    fee: float
    mid_at_fill: float
    depth_limited: bool = False  # the book (or the price limit) could not absorb the full order

    @property
    def notional(self) -> float:
        return self.shares * self.avg_price


@dataclass
class Position:
    side: str
    shares: float = 0.0
    cost: float = 0.0  # USDC paid for the shares still held, excluding fees
    fees: float = 0.0
    fills: list[Fill] = field(default_factory=list)


def ms_to_dt(ms: int) -> datetime:
    from datetime import timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
