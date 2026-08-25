"""etf-minute-fetcher: 用 akshare 抓取 ETF 分钟级行情并落盘为分区 parquet。"""

from __future__ import annotations

__version__ = "0.3.0"

from .downloader import DownloadConfig, DownloadEngine
from .fetcher import fetch_etf_minute, fetch_etf_minute_range, fetch_symbol_range, write_partition
from .models import Instrument
from .storage import ParquetStorage

__all__ = [
    "DownloadConfig",
    "DownloadEngine",
    "Instrument",
    "ParquetStorage",
    "fetch_etf_minute",
    "fetch_etf_minute_range",
    "fetch_symbol_range",
    "write_partition",
]
