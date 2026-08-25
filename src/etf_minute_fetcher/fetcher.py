"""ETF 分钟行情的公开编排接口。

具体网络请求放在 ``providers`` 模块，落盘实现放在 ``storage`` 模块。这里保留原有公开
函数，作为调用方和 ``DownloadEngine`` 的稳定边界。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TypedDict

import pandas as pd

from .providers import (
    OUTPUT_COLUMNS,
    FallbackMinuteProvider,
    MinuteDataProvider,
    validate_request,
)
from .storage import BarStorage, ParquetBarStorage

# 保留兼容常量，已有调用方和测试仍可继续引用。
_OUTPUT_COLUMNS = OUTPUT_COLUMNS


class FetchStats(TypedDict):
    """单只 ETF 下载任务的结构化统计结果。"""

    written: list[str]
    skipped: list[str]
    empty: list[str]
    errors: dict[str, str]


def _validate_trade_date(trade_date: str) -> None:
    datetime.strptime(trade_date, "%Y%m%d")


def _stats(
    written: list[str],
    skipped: list[str],
    empty: list[str],
    errors: dict[str, str],
) -> FetchStats:
    return FetchStats(
        written=written,
        skipped=skipped,
        empty=empty,
        errors=errors,
    )


def fetch_etf_minute_range(
    ts_code: str,
    start_trade_date: str,
    end_trade_date: str,
    *,
    period: str = "1",
    attempts: int = 3,
    retry_delay: float = 1.0,
    provider: MinuteDataProvider | None = None,
) -> pd.DataFrame:
    """抓取单只 ETF 在指定日期范围内的标准化分钟行情。

    未传入 ``provider`` 时使用默认回退链路：AKShare、东方财富 curl、新浪 curl。
    传入自定义实现后，调用方无需修改编排逻辑即可替换数据源。
    """
    validate_request(start_trade_date, end_trade_date, period)
    if attempts < 1:
        raise ValueError("attempts 必须 >= 1")
    if retry_delay < 0:
        raise ValueError("retry_delay 必须 >= 0")
    resolved_provider = provider or FallbackMinuteProvider(
        attempts=attempts,
        retry_delay=retry_delay,
    )
    return resolved_provider.fetch(
        ts_code,
        start_trade_date,
        end_trade_date,
        period=period,
    )


def fetch_etf_minute(
    ts_code: str,
    trade_date: str,
    *,
    period: str = "1",
    provider: MinuteDataProvider | None = None,
) -> pd.DataFrame:
    """抓取单只 ETF 某一交易日的标准化分钟行情。"""
    return fetch_etf_minute_range(
        ts_code,
        trade_date,
        trade_date,
        period=period,
        provider=provider,
    )


def write_partition(
    df: pd.DataFrame,
    output_dir: Path,
    trade_date: str,
    *,
    storage: BarStorage | None = None,
) -> Path | None:
    """通过配置的存储实现写入一个交易日分区。"""
    resolved_storage = storage or ParquetBarStorage()
    return resolved_storage.write(df, output_dir, trade_date)


def fetch_symbol_range(
    ts_code: str,
    trade_dates: list[str],
    *,
    period: str = "1",
    output_dir: Path,
    skip_existing: bool = True,
    provider: MinuteDataProvider | None = None,
    storage: BarStorage | None = None,
) -> FetchStats:
    """抓取单只 ETF 的多个日期，并按交易日分区落盘。

    这一层只依赖 ``MinuteDataProvider`` 和 ``BarStorage`` 两个接口。未传入自定义实现时，
    行为与原有公开 API 保持一致。
    """
    written: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    errors: dict[str, str] = {}
    pending: list[str] = []
    resolved_storage = storage or ParquetBarStorage()

    for trade_date in trade_dates:
        _validate_trade_date(trade_date)
        if skip_existing and resolved_storage.exists(output_dir, trade_date):
            skipped.append(trade_date)
            continue
        pending.append(trade_date)

    if not pending:
        return _stats(written, skipped, empty, errors)

    try:
        frame = fetch_etf_minute_range(
            ts_code,
            min(pending),
            max(pending),
            period=period,
            provider=provider,
        )
    except Exception as exc:
        # 单只 ETF 的执行边界把上游异常转换为按日期记录的任务错误。
        message = f"{type(exc).__name__}: {exc}"
        errors.update({trade_date: message for trade_date in pending})
        return _stats(written, skipped, empty, errors)

    if frame.empty:
        empty.extend(pending)
        return _stats(written, skipped, empty, errors)

    frame_trade_dates = frame["trade_time"].dt.strftime("%Y%m%d")
    for trade_date in pending:
        day_frame = frame.loc[frame_trade_dates == trade_date].copy()
        if day_frame.empty:
            empty.append(trade_date)
            continue
        resolved_storage.write(day_frame, output_dir, trade_date)
        written.append(trade_date)
    return _stats(written, skipped, empty, errors)
