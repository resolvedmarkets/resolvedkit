"""A local dataset: two Parquet files in one folder.

markets.parquet  market_id, slug, question, category, timeframe, start_ts, end_ts,
                 outcome_up, outcome_down, payout_up, payout_down   (payouts null if unresolved)
books.parquet    market_id, ts (epoch ms UTC), side ("UP"/"DOWN"),
                 bid_px, bid_sz, ask_px, ask_sz   (lists, best level first)

Any source of Polymarket order books can be converted to this layout and backtested.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..models import Book, Level, Market

_MARKET_SCHEMA = pa.schema([
    ("market_id", pa.string()), ("slug", pa.string()), ("question", pa.string()),
    ("category", pa.string()), ("timeframe", pa.string()),
    ("start_ts", pa.int64()), ("end_ts", pa.int64()),
    ("outcome_up", pa.string()), ("outcome_down", pa.string()),
    ("payout_up", pa.float64()), ("payout_down", pa.float64()),
])
_BOOK_SCHEMA = pa.schema([
    ("market_id", pa.string()), ("ts", pa.int64()), ("side", pa.string()),
    ("bid_px", pa.list_(pa.float64())), ("bid_sz", pa.list_(pa.float64())),
    ("ask_px", pa.list_(pa.float64())), ("ask_sz", pa.list_(pa.float64())),
])


class ParquetSource:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self._books: dict[str, list[Book]] | None = None

    def markets(self) -> list[Market]:
        rows = pq.read_table(self.folder / "markets.parquet").to_pylist()
        out = []
        for r in rows:
            payout = None
            if r["payout_up"] is not None and r["payout_down"] is not None:
                payout = (r["payout_up"], r["payout_down"])
            out.append(Market(
                market_id=r["market_id"], question=r["question"], category=r["category"],
                end_ts=r["end_ts"], outcomes=(r["outcome_up"], r["outcome_down"]), payout=payout,
                start_ts=r["start_ts"], slug=r["slug"], timeframe=r["timeframe"],
            ))
        return sorted(out, key=lambda m: m.end_ts)

    def books(self, market_id: str) -> list[Book]:
        if self._books is None:
            grouped: dict[str, list[Book]] = defaultdict(list)
            for r in pq.read_table(self.folder / "books.parquet").to_pylist():
                grouped[r["market_id"]].append(Book(
                    ts=r["ts"], side=r["side"],
                    bids=tuple(Level(p, s) for p, s in zip(r["bid_px"], r["bid_sz"])),
                    asks=tuple(Level(p, s) for p, s in zip(r["ask_px"], r["ask_sz"])),
                ))
            for v in grouped.values():
                v.sort(key=lambda b: (b.ts, b.side))
            self._books = dict(grouped)
        return self._books.get(market_id, [])


def write_parquet(folder: str | Path, markets: list[Market], books: dict[str, list[Book]], depth: int | None = None) -> None:
    """Save markets and their books in the layout ParquetSource reads. `depth` keeps the top N levels."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([{
        "market_id": m.market_id, "slug": m.slug, "question": m.question, "category": m.category,
        "timeframe": m.timeframe, "start_ts": m.start_ts, "end_ts": m.end_ts,
        "outcome_up": m.outcomes[0], "outcome_down": m.outcomes[1],
        "payout_up": m.payout[0] if m.payout else None, "payout_down": m.payout[1] if m.payout else None,
    } for m in markets], schema=_MARKET_SCHEMA), folder / "markets.parquet", compression="zstd")
    rows = []
    for market_id, bs in books.items():
        for b in bs:
            bids = b.bids if depth is None else b.bids[:depth]
            asks = b.asks if depth is None else b.asks[:depth]
            rows.append({
                "market_id": market_id, "ts": b.ts, "side": b.side,
                "bid_px": [l.price for l in bids], "bid_sz": [l.size for l in bids],
                "ask_px": [l.price for l in asks], "ask_sz": [l.size for l in asks],
            })
    pq.write_table(pa.Table.from_pylist(rows, schema=_BOOK_SCHEMA), folder / "books.parquet", compression="zstd")
