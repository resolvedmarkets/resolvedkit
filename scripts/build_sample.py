"""Rebuild the bundled sample from the Resolved Markets API.

    RESOLVED_MARKETS_API_KEY=... python scripts/build_sample.py [n_markets]

Takes the most recent settled BTC 15-minute markets, one snapshot per side per second, top 20 levels.
"""
import sys
from pathlib import Path

from resolvedkit.data import ResolvedMarketsAPI, write_parquet

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
OUT = Path(__file__).resolve().parent.parent / "src" / "resolvedkit" / "sample_data"

api = ResolvedMarketsAPI(crypto="BTC", timeframe="15m", limit=N, thin_ms=1000, depth=20)
markets = [m for m in api.markets() if m.payout is not None]
books = {}
for i, m in enumerate(markets, 1):
    books[m.market_id] = api.books(m.market_id)
    print(f"{i}/{len(markets)} {m.question}: {len(books[m.market_id])} snapshots", flush=True)
write_parquet(OUT, markets, books, depth=20)
print("wrote", OUT, sum(f.stat().st_size for f in OUT.iterdir()) // 1024, "KiB")
