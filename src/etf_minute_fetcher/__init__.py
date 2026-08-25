"""etf-minute-fetcher: 用 akshare 抓取 ETF 分钟级行情并落盘为分区 parquet。"""

from __future__ import annotations

__version__ = "0.2.0"

from .engine import DownloadConfig, DownloadEngine, DownloadSummary
from .fetcher import fetch_etf_minute, fetch_etf_minute_range, fetch_symbol_range, write_partition
from .models import Instrument
from .providers.base import MinuteDataProvider
from .providers.legacy import LegacyMinuteProvider
from .storage import BarStorage, ParquetStorage
from .universe import AkshareETFUniverse, ExplicitUniverse, FileUniverse, UniverseProvider

__all__ = [
    "AkshareETFUniverse",
    "DownloadConfig",
    "DownloadEngine",
    "DownloadSummary",
    "ExplicitUniverse",
    "FileUniverse",
    "Instrument",
    "BarStorage",
    "LegacyMinuteProvider",
    "MinuteDataProvider",
    "ParquetStorage",
    "UniverseProvider",
    "fetch_etf_minute",
    "fetch_etf_minute_range",
    "fetch_symbol_range",
    "write_partition",
]
