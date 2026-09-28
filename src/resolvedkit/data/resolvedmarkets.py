"""Historical Polymarket order books from the Resolved Markets API (https://resolvedmarkets.com).

A free API key covers crypto up/down markets (the 5 most recent per coin and timeframe);
paid plans unlock full history and other categories. Set RESOLVED_MARKETS_API_KEY or pass api_key=.
"""
from __future__ import annotations

import os
import time

import requests

from ..models import DOWN, UP, Book, Level, Market
from .base import TIMEFRAME_MS, parse_ts, thin

BASE_URL = "https://api.resolvedmarkets.com"
PAGE = 500


class ResolvedMarketsAPI:
    def __init__(self, api_key: str | None = None, *, crypto: str | None = None, timeframe: str | None = None,
                 category: str | None = None, since: str | None = None, before: str | None = None,
                 limit: int = 20, thin_ms: int | None = None, depth: int | None = None, base_url: str = BASE_URL):
        """Select closed markets like `/v1/markets/history/recent` does, e.g. crypto="BTC", timeframe="15m".

        thin_ms keeps one snapshot per side per interval (1000 = one per second) to cut memory;
        depth keeps only the top N levels of each side.
        """
        key = api_key or os.environ.get("RESOLVED_MARKETS_API_KEY")
        if not key:
            raise ValueError("Set RESOLVED_MARKETS_API_KEY or pass api_key= (free key: https://resolvedmarkets.com/api-keys)")
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = key
        self.base_url = base_url
        self.query = {k: v for k, v in {"crypto": crypto, "timeframe": timeframe, "category": category,
                                         "since": since, "before": before, "status": "closed"}.items() if v}
        self.limit, self.thin_ms, self.depth = limit, thin_ms, depth
        self._markets: list[Market] | None = None

    def _get(self, path: str, **params) -> dict:
        for attempt in range(4):
            r = self.session.get(self.base_url + path, params=params, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 403 and "replay_locked" in r.text:
                raise PermissionError(f"{path}: this market is outside the free tier's replay window (upgrade for full history)")
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return r.json()

    def markets(self) -> list[Market]:
        if self._markets is None:
            rows = self._get("/v1/markets/history/recent", **self.query, limit=self.limit)["markets"]
            out = []
            for row in rows:
                if row.get("replay_locked"):
                    continue
                meta = self._get("/v1/markets/metadata", market_id=row["market_id"])["markets"][0]
                prices = meta.get("outcome_prices")
                payout = (float(prices[0]), float(prices[1])) if meta.get("resolution_status") == "resolved" and prices else None
                end_ts = parse_ts(meta["end_date"])
                tf = meta.get("timeframe") or ""
                out.append(Market(
                    market_id=row["market_id"], question=meta.get("question") or "", category=meta.get("category") or "",
                    end_ts=end_ts, outcomes=tuple(meta.get("outcomes") or ("Up", "Down")), payout=payout,
                    start_ts=end_ts - TIMEFRAME_MS[tf] if tf in TIMEFRAME_MS else None,
                    slug=meta.get("slug") or "", timeframe=tf,
                ))
            self._markets = sorted(out, key=lambda m: m.end_ts)
        return self._markets

    def books(self, market_id: str) -> list[Book]:
        books: list[Book] = []
        for side in (UP, DOWN):
            offset = 0
            while True:
                page = self._get(f"/v1/markets/{market_id}/snapshots", side=side, includebook="true", order="asc",
                                 count="false", limit=PAGE, offset=offset)["data"]
                for s in page:
                    bids = tuple(Level(l["price"], l["size"]) for l in s.get("bids") or ())
                    asks = tuple(Level(l["price"], l["size"]) for l in s.get("asks") or ())
                    if self.depth is not None:
                        bids, asks = bids[: self.depth], asks[: self.depth]
                    books.append(Book(ts=parse_ts(s["timestamp"]), side=side, bids=bids, asks=asks))
                if len(page) < PAGE:
                    break
                offset += PAGE
        books.sort(key=lambda b: (b.ts, b.side))
        return thin(books, self.thin_ms) if self.thin_ms else books
