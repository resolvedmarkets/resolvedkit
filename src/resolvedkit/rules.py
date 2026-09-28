"""Strategies from a JSON spec, so a backtest can be written without Python (or by an AI agent).

{
  "name": "late favorite",
  "entry": {
    "side": "favorite",            // UP, DOWN, favorite (higher mid) or underdog (lower mid)
    "seconds_before_end": 120,      // enter once this close to the market's end time
    "min_price": 0.6, "max_price": 0.9,   // only if the side's best ask is in this range
    "usd": 100,                     // order size
    "max_slippage": 0.02            // never pay more than best ask + this
  },
  "exit": {                         // optional; without it the position is held to resolution
    "take_profit": 0.05,            // sell when the best bid is this far above the entry price
    "stop_loss": 0.10               // sell when the best bid is this far below it
  }
}
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import Context, Strategy
from .models import DOWN, UP, Book

_SIDES = {"UP", "DOWN", "favorite", "underdog"}
EPS = 1e-9  # price comparisons: 0.52 + 0.05 is 0.5700000000000001 in floating point


@dataclass
class RuleStrategy(Strategy):
    spec: dict

    def __post_init__(self):
        e = self.spec.get("entry") or {}
        if e.get("side") not in _SIDES:
            raise ValueError(f"entry.side must be one of {sorted(_SIDES)}")
        for k in ("seconds_before_end", "usd"):
            if not isinstance(e.get(k), (int, float)) or e[k] <= 0:
                raise ValueError(f"entry.{k} must be a positive number")

    def on_start(self, ctx: Context) -> None:
        ctx.state.update(side=None)

    def _pick_side(self, ctx: Context) -> str | None:
        want = self.spec["entry"]["side"]
        if want in (UP, DOWN):
            return want
        up, down = ctx.book(UP), ctx.book(DOWN)
        if not up or not down:
            return None
        fav = UP if up.mid >= down.mid else DOWN
        return fav if want == "favorite" else (DOWN if fav == UP else UP)

    def on_book(self, ctx: Context, book: Book) -> None:
        # State comes from fills, not from orders placed: a rejected or partial order is retried.
        e, x, st = self.spec["entry"], self.spec.get("exit") or {}, ctx.state
        if ctx.pending_orders():
            return
        side = st["side"]
        entered = side is not None and any(f.action == "BUY" for f in ctx.position(side).fills)
        if not entered:
            if not (0 < ctx.seconds_to_end <= e["seconds_before_end"]):
                return
            side = self._pick_side(ctx)
            b = ctx.book(side) if side else None
            if not b or b.best_ask is None:
                return
            if not (e.get("min_price", 0.0) - EPS <= b.best_ask <= e.get("max_price", 1.0) + EPS):
                return
            ctx.buy(side, e["usd"], max_price=b.best_ask + e.get("max_slippage", 0.02))
            st["side"] = side
            return
        pos = ctx.position(side)
        if pos.shares <= 1e-9 or book.side != side or not x or book.best_bid is None:
            return
        entry = pos.cost / pos.shares
        bid = book.best_bid
        if ("take_profit" in x and bid >= entry + x["take_profit"] - EPS) or (
            "stop_loss" in x and bid <= entry - x["stop_loss"] + EPS
        ):
            ctx.sell(side)
