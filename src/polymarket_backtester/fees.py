"""Polymarket taker fees.

fee = shares × rate × p × (1 − p), charged to the taker only, rounded to 5 decimals.
Rates by category from https://docs.polymarket.com/trading/fees (checked 2026-09-28).
Polymarket changes these; pass `rate=` to override.
"""
from __future__ import annotations

TAKER_FEE_RATES: dict[str, float] = {
    "crypto": 0.07,
    "sports": 0.05,
    "finance": 0.04,
    "equities": 0.04,
    "politics": 0.04,
    "economics": 0.05,
    "culture": 0.05,
    "weather": 0.05,
    "social": 0.05,
    "mentions": 0.04,
    "tech": 0.04,
    "geopolitics": 0.0,
}
DEFAULT_RATE = 0.05  # Polymarket's "Other / General"


def rate_for(category: str) -> float:
    return TAKER_FEE_RATES.get((category or "").lower(), DEFAULT_RATE)


def taker_fee(shares: float, price: float, rate: float) -> float:
    """Fee in USDC for a taker fill of `shares` at `price`."""
    if shares <= 0 or rate <= 0:
        return 0.0
    return round(shares * rate * price * (1.0 - price), 5)
