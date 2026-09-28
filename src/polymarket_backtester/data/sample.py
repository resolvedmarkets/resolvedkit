"""The bundled sample: settled BTC 15-minute Polymarket markets with full-depth books.

Data © Resolved Markets, licensed CC BY 4.0 (see DATA_LICENSE). Books are thinned to one snapshot per
side per second and the top 20 levels, which keeps the package small; the API serves every snapshot.
"""
from __future__ import annotations

from importlib.resources import files

from .parquet import ParquetSource


def load_sample() -> ParquetSource:
    return ParquetSource(files("polymarket_backtester") / "sample_data")
