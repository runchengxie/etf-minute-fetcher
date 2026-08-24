"""ETF 分钟级行情抓取（akshare 源）。

数据来自东方财富（push2his.eastmoney.com / quote.eastmoney.com），
优先通过 akshare 的 ``fund_etf_hist_min_em`` 拉取；当其 requests 请求被代理
断开时，自动回退到系统 curl 直连东方财富。落盘结构刻意对齐
``~/data/market-data-platform/assets/tushare/etf/daily``：按 ``trade_date``
做 Hive 风格分区，单分区一个 ``part.parquet``，列名采用 tushare 风格
（ts_code/open/high/low/close/vol/amount），并额外保留 ``trade_time`` 分钟时间戳。

注意：akshare 的 ``symbol`` 参数不带交易所后缀（如 ``512880``），而本模块
对外与落盘的 ``ts_code`` 统一带后缀（如 ``512880.SH``），便于和现有 ETF
日线数据集直接 join。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
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
_NUMERIC_COLUMNS = ["open", "high", "low", "close", "vol", "amount"]
_VALID_PERIODS = {"1", "5", "15", "30", "60"}
_EASTMONEY_MINUTE_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def _normalize_symbol(ts_code: str) -> str:
    """把 ``512880.SH`` 形式的代码转成 akshare 需要的 ``512880``。"""
    return ts_code.split(".")[0]


def _eastmoney_market_id(symbol: str) -> str:
    """返回东方财富 ``secid`` 所需的市场编号。"""
    return "1" if symbol.startswith(("5", "6")) else "0"


def _fetch_eastmoney_with_curl(
    ts_code: str,
    start_trade_date: str,
    end_trade_date: str,
    *,
    period: str,
) -> pd.DataFrame:
    """用系统 curl 直连东方财富并还原成 AKShare 的原始 schema。

    某些代理会正常代理普通 HTTPS 请求，却会直接关闭东方财富的行情查询。
    AKShare 内部固定使用 ``requests``，因此这里提供一个只在 AKShare 请求
    完全失败后使用的直连回退路径。curl 的参数全部作为 argv 传递，不经过 shell。
    """
    curl_path = shutil.which("curl")
    if curl_path is None:
        raise FileNotFoundError("未找到 curl；无法使用东方财富直连回退路径")

    symbol = _normalize_symbol(ts_code)
    secid = f"{_eastmoney_market_id(symbol)}.{symbol}"
    if period == "1":
        url = _EASTMONEY_MINUTE_URL
        rows_key = "trends"
        columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"]
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "ndays": "5",
            "iscr": "0",
            "secid": secid,
        }
    else:
        url = _EASTMONEY_KLINE_URL
        rows_key = "klines"
        columns = [
            "时间",
            "开盘",
            "收盘",
            "最高",
            "最低",
            "成交量",
            "成交额",
            "振幅",
            "涨跌幅",
            "涨跌额",
            "换手率",
        ]
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": period,
            "fqt": "0",
            "secid": secid,
            "beg": "0",
            "end": "20500000",
        }

    command = [
        curl_path,
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--noproxy",
        "*",
        "--connect-timeout",
        "15",
        "--max-time",
        "30",
        "--get",
        url,
    ]
    for key, value in params.items():
        command.extend(["--data-urlencode", f"{key}={value}"])

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ConnectionError(f"curl 请求东方财富失败（exit={result.returncode}）: {detail}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"东方财富返回的 curl 响应不是 JSON: {result.stdout[:200]!r}") from exc

    data = payload.get("data")
    rows = data.get(rows_key) if isinstance(data, dict) else None
    if rows is None:
        if isinstance(data, dict) and data.get("total") == 0:
            return pd.DataFrame(columns=columns)
        raise ValueError(f"东方财富响应缺少 data.{rows_key}: {payload!r}")
    if not isinstance(rows, list):
        raise ValueError(f"东方财富 data.{rows_key} 不是列表")
    if not rows:
        return pd.DataFrame(columns=columns)

    split_rows = [str(row).split(",") for row in rows]
    bad_widths = sorted({len(row) for row in split_rows if len(row) != len(columns)})
    if bad_widths:
        raise ValueError(f"东方财富 data.{rows_key} 列数异常: {bad_widths}，期望 {len(columns)}")
    return pd.DataFrame(split_rows, columns=columns)


def _validate_trade_date(trade_date: str) -> None:
    """校验 ``YYYYMMDD`` 交易日字符串。"""
    datetime.strptime(trade_date, "%Y%m%d")


def _normalize_frame(raw: pd.DataFrame | None, ts_code: str) -> pd.DataFrame:
    """把 akshare 返回值规范成稳定的 tushare 风格 schema。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    frame = raw.rename(columns=_COLUMN_MAP).copy()
    if "trade_time" not in frame.columns:
        raise ValueError("akshare 返回值缺少时间列 '时间'")

    for col in _NUMERIC_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
        frame[col] = pd.to_numeric(
            frame[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )

    frame["ts_code"] = ts_code
    frame["trade_time"] = pd.to_datetime(frame["trade_time"], errors="coerce")
    out = frame[_OUTPUT_COLUMNS].copy()
    out = out.dropna(subset=["trade_time"])
    out = out.sort_values("trade_time").drop_duplicates(subset=["ts_code", "trade_time"], keep="last")
    return out.reset_index(drop=True)


def fetch_etf_minute_range(
    ts_code: str,
    start_trade_date: str,
    end_trade_date: str,
    *,
    period: str = "1",
    attempts: int = 3,
    retry_delay: float = 1.0,
) -> pd.DataFrame:
    """一次请求抓取单只 ETF 的分钟线日期区间。

    ``period='1'`` 时受东方财富/akshare 上游限制，只能获得最近 5 个交易日。
    """
    import akshare as ak

    if period not in _VALID_PERIODS:
        raise ValueError(f"不支持的 period={period!r}; 可选值: {sorted(_VALID_PERIODS)}")
    if attempts < 1:
        raise ValueError("attempts 必须 >= 1")
    if retry_delay < 0:
        raise ValueError("retry_delay 必须 >= 0")
    _validate_trade_date(start_trade_date)
    _validate_trade_date(end_trade_date)
    if start_trade_date > end_trade_date:
        raise ValueError(f"start_trade_date {start_trade_date} 晚于 end_trade_date {end_trade_date}")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            raw = ak.fund_etf_hist_min_em(
                symbol=_normalize_symbol(ts_code),
                period=period,
                start_date=f"{start_trade_date} 09:30:00",
                end_date=f"{end_trade_date} 15:00:00",
            )
            return _normalize_frame(raw, ts_code)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts:
                time.sleep(retry_delay * attempt)

    if last_error is None:  # pragma: no cover - attempts >= 1 guarantees this
        raise RuntimeError("AKShare 请求未执行")

    try:
        fallback_raw = _fetch_eastmoney_with_curl(
            ts_code,
            start_trade_date,
            end_trade_date,
            period=period,
        )
        fallback_frame = _normalize_frame(fallback_raw, ts_code)
        if fallback_frame.empty:
            return fallback_frame

        start_ts = pd.Timestamp(datetime.strptime(start_trade_date, "%Y%m%d").replace(hour=9, minute=30))
        end_ts = pd.Timestamp(datetime.strptime(end_trade_date, "%Y%m%d").replace(hour=15))
        return fallback_frame.loc[fallback_frame["trade_time"].between(start_ts, end_ts)].reset_index(drop=True)
    except Exception as fallback_error:  # noqa: BLE001
        raise RuntimeError(
            f"AKShare 请求失败: {type(last_error).__name__}: {last_error}; "
            f"curl 直连回退也失败: {type(fallback_error).__name__}: {fallback_error}"
        ) from fallback_error



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
    return fetch_etf_minute_range(ts_code, trade_date, trade_date, period=period)


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
    tmp_path = part_dir / ".part.parquet.tmp"
    try:
        df.to_parquet(tmp_path, index=False, engine="pyarrow")
        tmp_path.replace(out_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
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

    每只 ETF 的待抓日期合并成一次上游请求，再按 ``trade_time`` 分区，避免原先
    每个自然日都重复下载同一份“最近 5 个交易日”数据。

    Returns:
        统计字典：written / skipped / empty / errors。
    """
    written: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    errors: dict[str, str] = {}
    pending: list[str] = []

    for td in trade_dates:
        _validate_trade_date(td)
        part_dir = output_dir / f"trade_date={td}"
        if skip_existing and (part_dir / "part.parquet").exists():
            skipped.append(td)
            continue
        pending.append(td)

    if not pending:
        return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}

    try:
        frame = fetch_etf_minute_range(ts_code, min(pending), max(pending), period=period)
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        errors.update({td: message for td in pending})
        return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}

    if frame.empty:
        empty.extend(pending)
        return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}

    frame_trade_dates = frame["trade_time"].dt.strftime("%Y%m%d")
    for td in pending:
        day_df = frame.loc[frame_trade_dates == td].copy()
        if day_df.empty:
            empty.append(td)
            continue
        write_partition(day_df, output_dir, td)
        written.append(td)
    return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}
