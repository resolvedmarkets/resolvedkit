"""Fill simulation: walk the order book level by level, as a real marketable order would."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Level


@dataclass(frozen=True)
class WalkResult:
    legs: tuple[Level, ...]  # (price, shares) actually taken at each level
    depth_limited: bool  # stopped early: book exhausted or price limit reached

    @property
    def shares(self) -> float:
        return sum(l.size for l in self.legs)

    @property
    def cost(self) -> float:
        """USDC paid (buy) or received (sell), before fees."""
        return sum(l.size * l.price for l in self.legs)

    @property
    def avg_price(self) -> float:
        s = self.shares
        return self.cost / s if s else 0.0

    def fee(self, rate: float) -> float:
        """Polymarket charges each match at its own price: Σ shares × rate × p × (1 − p)."""
        return round(sum(l.size * rate * l.price * (1 - l.price) for l in self.legs), 5)


def walk_buy(asks: tuple[Level, ...], usd: float, max_price: float | None = None) -> WalkResult:
    """Spend up to `usd` lifting asks from the best price up, never paying above `max_price`."""
    legs, spent = [], 0.0
    for lvl in asks:
        if lvl.price <= 0 or lvl.size <= 0:
            continue
        remaining = usd - spent
        if remaining <= 1e-9:
            break
        if max_price is not None and lvl.price > max_price + 1e-12:
            return WalkResult(tuple(legs), True)
        take = min(lvl.size, remaining / lvl.price)
        legs.append(Level(lvl.price, take))
        spent += take * lvl.price
    return WalkResult(tuple(legs), usd - spent > 1e-6)


def walk_sell(bids: tuple[Level, ...], shares: float, min_price: float | None = None) -> WalkResult:
    """Sell up to `shares` into bids from the best price down, never selling below `min_price`."""
    legs, sold = [], 0.0
    for lvl in bids:
        if lvl.size <= 0:
            continue
        remaining = shares - sold
        if remaining <= 1e-9:
            break
        if min_price is not None and lvl.price < min_price - 1e-12:
            return WalkResult(tuple(legs), True)
        take = min(lvl.size, remaining)
        legs.append(Level(lvl.price, take))
        sold += take
    return WalkResult(tuple(legs), shares - sold > 1e-6)
