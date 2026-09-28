"""resolvedkit run spec.json [--data sample|api|<folder>] [--compare-mid] [--json]"""
from __future__ import annotations

import argparse
import json
import sys

from .engine import Backtester
from .rules import RuleStrategy


def _source(args):
    if args.data == "sample":
        from .data import load_sample

        return load_sample()
    if args.data == "api":
        from .data import ResolvedMarketsAPI

        return ResolvedMarketsAPI(crypto=args.crypto, timeframe=args.timeframe, category=args.category,
                                  since=args.since, before=args.before, limit=args.limit, thin_ms=args.thin_ms)
    from .data import ParquetSource

    return ParquetSource(args.data)


def _spec_path(name: str):
    """A path to a JSON spec, or the name of a bundled example such as `late_favorite`."""
    from importlib.resources import files
    from pathlib import Path

    p = Path(name)
    if p.exists():
        return p
    bundled = files("resolvedkit") / "specs" / f"{p.stem}.json"
    if bundled.is_file():
        return bundled
    examples = sorted(x.name.removesuffix(".json") for x in (files("resolvedkit") / "specs").iterdir())
    raise SystemExit(f"No spec file '{name}'. Bundled examples: {', '.join(examples)}")


def _print(label: str, s: dict) -> None:
    print(f"\n{label}")
    for k, v in s.items():
        print(f"  {k:<22} {v}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="resolvedkit", description="Backtest Polymarket strategies against the real order book.")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run a JSON strategy spec")
    run.add_argument("spec", help="path to a JSON strategy spec, or a bundled example: late_favorite, early_underdog_scalp")
    run.add_argument("--data", default="sample", help="'sample' (bundled, default), 'api' (Resolved Markets), or a Parquet folder")
    run.add_argument("--latency-ms", type=int, default=250)
    run.add_argument("--compare-mid", action="store_true", help="also run with mid-price fills and show the difference")
    run.add_argument("--json", action="store_true", help="print results as JSON")
    for flag in ("--crypto", "--timeframe", "--category", "--since", "--before"):
        run.add_argument(flag, help="with --data api: filter markets like /v1/markets/history/recent")
    run.add_argument("--limit", type=int, default=20, help="with --data api: number of markets")
    run.add_argument("--thin-ms", type=int, default=None, help="with --data api: keep one snapshot per side per interval")
    args = p.parse_args(argv)

    spec = json.loads(_spec_path(args.spec).read_text())
    data = _source(args)
    markets = data.markets()
    book = Backtester(data, RuleStrategy(spec), latency_ms=args.latency_ms).run(markets).summary()
    out = {"strategy": spec.get("name", args.spec), "book": book}
    if args.compare_mid:
        out["mid"] = Backtester(data, RuleStrategy(spec), latency_ms=args.latency_ms, fill_model="mid").run(markets).summary()
    if args.json:
        json.dump(out, sys.stdout, indent=2)
        print()
        return 0
    print(f"Strategy: {out['strategy']}  ({len(markets)} markets)")
    _print("Fills against the real order book:", book)
    if args.compare_mid:
        _print("Same strategy with mid-price fills (unrealistic):", out["mid"])
        rm, rb = out["mid"]["return_on_invested"], book["return_on_invested"]
        if rm is not None and rb is not None:
            print(f"\nReturn on money invested: {rm:+.1%} with mid-price fills vs {rb:+.1%} on the real book.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
