"""Backtest Polymarket strategies against the real order book."""
from .data import ParquetSource, ResolvedMarketsAPI, load_sample, write_parquet
from .engine import Backtester, Context, MarketResult, Strategy
from .fees import taker_fee
from .metrics import Results
from .models import DOWN, UP, Book, Fill, Level, Market
from .rules import RuleStrategy

__version__ = "0.1.0"
__all__ = [
    "Backtester", "Book", "Context", "DOWN", "Fill", "Level", "Market", "MarketResult", "ParquetSource",
    "ResolvedMarketsAPI", "Results", "RuleStrategy", "Strategy", "UP", "load_sample", "taker_fee", "write_parquet",
]
