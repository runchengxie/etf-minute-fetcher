"""ETF 分钟级行情抓取（akshare 源）。

数据来自东方财富（push2his.eastmoney.com / quote.eastmoney.com），
通过 akshare 的 ``fund_etf_hist_min_em`` 拉取。落盘结构刻意对齐
``~/data/market-data-platform/assets/tushare/etf/daily``：按 ``trade_date``
做 Hive 风格分区，单分区一个 ``part.parquet``，列名采用 tushare 风格
（ts_code/open/high/low/close/vol/amount），并额外保留 ``trade_time`` 分钟时间戳。

注意：akshare 的 ``symbol`` 参数不带交易所后缀（如 ``512880``），而本模块
对外与落盘的 ``ts_code`` 统一带后缀（如 ``512880.SH``），便于和现有 ETF
日线数据集直接 join。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# akshare fund_etf_hist_min_em 返回的中文列 -> 统一英文列
_COLUMN_MAP = {
    "时间": "trade_time",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "vol",
    "成交额": "amount",
    "最新价": "latest",
}

# 落盘时保留的列顺序
_OUTPUT_COLUMNS = ["ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"]


def _normalize_symbol(ts_code: str) -> str:
    """把 ``512880.SH`` 形式的代码转成 akshare 需要的 ``512880``。"""
    return ts_code.split(".")[0]


def fetch_etf_minute(
    ts_code: str,
    trade_date: str,
    *,
    period: str = "1",
) -> pd.DataFrame:
    """抓取单只 ETF 某一交易日的分钟线。

    Args:
        ts_code: 带后缀的代码，如 ``512880.SH``。
        trade_date: ``YYYYMMDD`` 格式。
        period: 分钟粒度，``"1"``/``"5"``/``"15"``/``"30"``/``"60"``。

    Returns:
        标准化后的 DataFrame，含 ``ts_code`` 列；若该日无数据返回空表。
    """
    import akshare as ak

    start_dt = f"{trade_date} 09:30:00"
    end_dt = f"{trade_date} 15:00:00"
    raw = ak.fund_etf_hist_min_em(
        symbol=_normalize_symbol(ts_code),
        period=period,
        start_date=start_dt,
        end_date=end_dt,
    )
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    frame = raw.rename(columns=_COLUMN_MAP)
    # akshare 的 "成交量"/"成交额" 是字符串带单位（如 "1.2万"），需还原为数值
    for col in ("open", "high", "low", "close", "vol", "amount", "latest"):
        if col in frame.columns:
            frame[col] = pd.to_numeric(
                frame[col].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
    frame["ts_code"] = ts_code
    # trade_time 含日期，提取 trade_date 分区键
    frame["trade_time"] = pd.to_datetime(frame["trade_time"], errors="coerce")
    out = frame[[c for c in _OUTPUT_COLUMNS if c in frame.columns]].copy()
    out = out.dropna(subset=["trade_time"])
    return out


def write_partition(
    df: pd.DataFrame,
    output_dir: Path,
    trade_date: str,
) -> Path | None:
    """把一个交易日的 DataFrame 写入 ``output_dir/trade_date=YYYYMMDD/part.parquet``。

    Returns:
        写入的文件路径；若 df 为空则返回 None（不落盘）。
    """
    if df is None or df.empty:
        return None
    part_dir = output_dir / f"trade_date={trade_date}"
    part_dir.mkdir(parents=True, exist_ok=True)
    out_path = part_dir / "part.parquet"
    df.to_parquet(out_path, index=False, engine="pyarrow")
    return out_path


def fetch_symbol_range(
    ts_code: str,
    trade_dates: list[str],
    *,
    period: str = "1",
    output_dir: Path,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """抓取一只 ETF 在多个交易日区间的分钟线并落盘。

    Returns:
        统计字典：written / skipped / empty / errors。
    """
    written: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    errors: dict[str, str] = {}

    for td in trade_dates:
        part_dir = output_dir / f"trade_date={td}"
        if skip_existing and (part_dir / "part.parquet").exists():
            skipped.append(td)
            continue
        try:
            df = fetch_etf_minute(ts_code, td, period=period)
        except Exception as exc:  # noqa: BLE001
            errors[td] = f"{type(exc).__name__}: {exc}"
            continue
        if df.empty:
            empty.append(td)
            continue
        write_partition(df, output_dir, td)
        written.append(td)
    return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}
