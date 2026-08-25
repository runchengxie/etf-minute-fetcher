"""下载 ETF 分钟行情，并按交易日保存为 Parquet 分区。"""

from __future__ import annotations

__version__ = "0.2.0"

from .engine import DownloadConfig, DownloadEngine, DownloadSummary
from .fetcher import fetch_etf_minute, fetch_etf_minute_range, fetch_symbol_range, write_partition
from .models import Instrument
from .universe import AkshareETFUniverse, ExplicitUniverse, FileUniverse, UniverseProvider

__all__ = [
    "AkshareETFUniverse",
    "DownloadConfig",
    "DownloadEngine",
    "DownloadSummary",
    "ExplicitUniverse",
    "FileUniverse",
    "Instrument",
    "UniverseProvider",
    "fetch_etf_minute",
    "fetch_etf_minute_range",
    "fetch_symbol_range",
    "write_partition",
]
