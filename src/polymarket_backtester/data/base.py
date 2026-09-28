from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from ..models import Book, Market

TIMEFRAME_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class DataSource(Protocol):
    def markets(self) -> list[Market]:
        """Markets to backtest over, oldest first."""
        ...

    def books(self, market_id: str) -> list[Book]:
        """Every order-book snapshot for both outcome tokens of one market, in time order."""
        ...


def parse_ts(value: str | int | float) -> int:
    """API timestamps are UTC strings like '2026-09-28 13:15:15.955'; return epoch ms."""
    if isinstance(value, (int, float)):
        return int(value)
    dt = datetime.fromisoformat(value.replace("Z", "").replace(" ", "T"))
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def thin(books: list[Book], every_ms: int) -> list[Book]:
    """Keep the last snapshot per side in each `every_ms` bucket. Book state at bucket ends is exact."""
    last: dict[tuple[str, int], Book] = {}
    for b in books:
        last[(b.side, b.ts // every_ms)] = b
    return sorted(last.values(), key=lambda b: (b.ts, b.side))
