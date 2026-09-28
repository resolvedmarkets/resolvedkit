from __future__ import annotations

from dataclasses import dataclass

from .engine import MarketResult


@dataclass
class Results:
    markets: list[MarketResult]
    fill_model: str = "book"
    latency_ms: int = 0

    @property
    def traded(self) -> list[MarketResult]:
        return [m for m in self.markets if m.traded]

    @property
    def pnl(self) -> float:
        return sum(m.pnl for m in self.markets)

    @property
    def fees(self) -> float:
        return sum(m.fees for m in self.markets)

    @property
    def invested(self) -> float:
        return sum(f.notional for m in self.markets for f in m.fills if f.action == "BUY")

    @property
    def win_rate(self) -> float | None:
        t = self.traded
        return sum(m.pnl > 0 for m in t) / len(t) if t else None

    @property
    def slippage_vs_mid(self) -> float | None:
        """Average cost of trading against the book instead of the mid, in price units (0.01 = 1¢).

        Positive means worse than mid: paid above it on buys, received below it on sells.
        """
        fills = [f for m in self.markets for f in m.fills]
        if not fills:
            return None
        signed = [(f.avg_price - f.mid_at_fill) * (1 if f.action == "BUY" else -1) * f.shares for f in fills]
        return sum(signed) / sum(f.shares for f in fills)

    @property
    def brier(self) -> float | None:
        """Brier score of the first entry price as a probability forecast of the side bought winning.

        Measures how well the market's price (as you traded it) predicted the outcome. Lower is better;
        always buying at 0.5 scores 0.25.
        """
        pairs = []
        for m in self.markets:
            buys = [f for f in m.fills if f.action == "BUY"]
            if buys and m.market.payout is not None:
                first = buys[0]
                pairs.append((first.avg_price, m.market.payout_for(first.side)))
        return sum((p - o) ** 2 for p, o in pairs) / len(pairs) if pairs else None

    @property
    def rejections(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for m in self.markets:
            for r in m.rejections:
                out[r.reason] = out.get(r.reason, 0) + 1
        return out

    def equity_curve(self) -> list[tuple[int, float]]:
        """Cumulative PnL after each market settles, as (end_ts, pnl)."""
        total, out = 0.0, []
        for m in sorted(self.markets, key=lambda r: r.market.end_ts):
            total += m.pnl
            out.append((m.market.end_ts, total))
        return out

    def summary(self) -> dict:
        def r(x, n=4):
            return None if x is None else round(x, n)

        return {
            "fill_model": self.fill_model,
            "latency_ms": self.latency_ms,
            "markets": len(self.markets),
            "markets_traded": len(self.traded),
            "invested_usd": r(self.invested, 2),
            "pnl_usd": r(self.pnl, 2),
            "return_on_invested": r(self.pnl / self.invested if self.invested else None),
            "fees_usd": r(self.fees, 2),
            "win_rate": r(self.win_rate),
            "partial_fills": sum(f.depth_limited for m in self.markets for f in m.fills),
            "avg_slippage_vs_mid": r(self.slippage_vs_mid),
            "entry_brier": r(self.brier),
            "rejected_orders": self.rejections,
            "unresolved_markets": sum(not m.resolved for m in self.traded),
        }
