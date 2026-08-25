"""ETF 分钟行情源接口、默认回退链路和字段标准化。"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import pandas as pd

OUTPUT_COLUMNS = ["ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"]
VALID_PERIODS = frozenset({"1", "5", "15", "30", "60"})

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
_NUMERIC_COLUMNS = ["open", "high", "low", "close", "vol", "amount"]
_EASTMONEY_MINUTE_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
_EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SINA_KLINE_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
)
_SINA_MAX_DATALEN = "20000"


class MinuteDataProvider(Protocol):
    """返回单只 ETF 指定日期范围内的标准化分钟行情。"""

    def fetch(
        self,
        ts_code: str,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str = "1",
    ) -> pd.DataFrame: ...


def validate_request(start_trade_date: str, end_trade_date: str, period: str) -> None:
    if period not in VALID_PERIODS:
        raise ValueError(f"不支持的 period={period!r}，可选值: {sorted(VALID_PERIODS)}")
    _validate_trade_date(start_trade_date)
    _validate_trade_date(end_trade_date)
    if start_trade_date > end_trade_date:
        raise ValueError(
            f"start_trade_date {start_trade_date} 晚于 end_trade_date {end_trade_date}"
        )


def normalize_frame(raw: pd.DataFrame | None, ts_code: str) -> pd.DataFrame:
    """把上游数据表转换为项目固定字段。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    frame = raw.rename(columns=_COLUMN_MAP).copy()
    if "trade_time" not in frame.columns:
        raise ValueError("上游返回值缺少时间列 '时间'")

    for col in _NUMERIC_COLUMNS:
        if col not in frame.columns:
            frame[col] = pd.NA
        frame[col] = pd.to_numeric(
            frame[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )

    frame["ts_code"] = ts_code
    frame["trade_time"] = pd.to_datetime(frame["trade_time"], errors="coerce")
    out = frame[OUTPUT_COLUMNS].copy()
    out = out.dropna(subset=["trade_time"])
    out = out.sort_values("trade_time").drop_duplicates(
        subset=["ts_code", "trade_time"], keep="last"
    )
    return out.reset_index(drop=True)


def filter_frame_to_range(
    frame: pd.DataFrame, start_trade_date: str, end_trade_date: str
) -> pd.DataFrame:
    if frame.empty:
        return frame.reset_index(drop=True)
    start_ts = pd.Timestamp(
        datetime.strptime(start_trade_date, "%Y%m%d").replace(hour=9, minute=30)
    )
    end_ts = pd.Timestamp(datetime.strptime(end_trade_date, "%Y%m%d").replace(hour=15))
    return frame.loc[frame["trade_time"].between(start_ts, end_ts)].reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class AkshareMinuteProvider:
    attempts: int = 3
    retry_delay: float = 1.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts 必须 >= 1")
        if self.retry_delay < 0:
            raise ValueError("retry_delay 必须 >= 0")

    def fetch(
        self,
        ts_code: str,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str = "1",
    ) -> pd.DataFrame:
        validate_request(start_trade_date, end_trade_date, period)
        import akshare as ak

        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                raw = ak.fund_etf_hist_min_em(
                    symbol=_normalize_symbol(ts_code),
                    period=period,
                    start_date=f"{start_trade_date} 09:30:00",
                    end_date=f"{end_trade_date} 15:00:00",
                )
                return normalize_frame(raw, ts_code)
            except Exception as exc:
                last_error = exc
                if attempt < self.attempts:
                    time.sleep(self.retry_delay * attempt)
        if last_error is None:  # pragma: no cover
            raise RuntimeError("AKShare 请求未执行")
        raise last_error


@dataclass(frozen=True, slots=True)
class EastMoneyCurlMinuteProvider:
    def fetch(
        self,
        ts_code: str,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str = "1",
    ) -> pd.DataFrame:
        validate_request(start_trade_date, end_trade_date, period)
        raw = _fetch_eastmoney_with_curl(
            ts_code,
            start_trade_date,
            end_trade_date,
            period=period,
        )
        return filter_frame_to_range(
            normalize_frame(raw, ts_code),
            start_trade_date,
            end_trade_date,
        )


@dataclass(frozen=True, slots=True)
class SinaCurlMinuteProvider:
    def fetch(
        self,
        ts_code: str,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str = "1",
    ) -> pd.DataFrame:
        validate_request(start_trade_date, end_trade_date, period)
        raw = _fetch_sina_with_curl(
            ts_code,
            start_trade_date,
            end_trade_date,
            period=period,
        )
        return filter_frame_to_range(
            normalize_frame(raw, ts_code),
            start_trade_date,
            end_trade_date,
        )


@dataclass(frozen=True, slots=True)
class FallbackMinuteProvider:
    """按 AKShare、东方财富 curl、新浪 curl 的顺序尝试数据源。"""

    attempts: int = 3
    retry_delay: float = 1.0

    def fetch(
        self,
        ts_code: str,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str = "1",
    ) -> pd.DataFrame:
        validate_request(start_trade_date, end_trade_date, period)
        primary = AkshareMinuteProvider(attempts=self.attempts, retry_delay=self.retry_delay)
        primary_error: Exception | None = None
        try:
            frame = primary.fetch(ts_code, start_trade_date, end_trade_date, period=period)
            if not frame.empty:
                return frame
            primary_error = RuntimeError("AKShare 没有返回指定日期范围内的数据")
        except Exception as exc:
            primary_error = exc

        eastmoney_error: Exception | None = None
        try:
            frame = EastMoneyCurlMinuteProvider().fetch(
                ts_code,
                start_trade_date,
                end_trade_date,
                period=period,
            )
            if period == "1" or not frame.empty:
                return frame
            eastmoney_error = RuntimeError("东方财富回退没有返回指定日期范围内的数据")
        except Exception as exc:
            eastmoney_error = exc

        if period != "1":
            try:
                return SinaCurlMinuteProvider().fetch(
                    ts_code,
                    start_trade_date,
                    end_trade_date,
                    period=period,
                )
            except Exception as sina_error:
                raise RuntimeError(
                    f"AKShare 请求失败: {type(primary_error).__name__}: {primary_error}，"
                    f"东方财富 curl 回退失败: {type(eastmoney_error).__name__}: {eastmoney_error}，"
                    f"新浪 curl 回退也失败: {type(sina_error).__name__}: {sina_error}"
                ) from sina_error

        raise RuntimeError(
            f"AKShare 请求失败: {type(primary_error).__name__}: {primary_error}，"
            f"curl 直连回退也失败: {type(eastmoney_error).__name__}: {eastmoney_error}"
        ) from eastmoney_error


def _normalize_symbol(ts_code: str) -> str:
    return ts_code.split(".")[0]


def _eastmoney_market_id(symbol: str) -> str:
    return "1" if symbol.startswith(("5", "6")) else "0"


def _sina_market_symbol(symbol: str) -> str:
    market = "sh" if symbol.startswith(("5", "6")) else "sz"
    return f"{market}{symbol}"


def _validate_trade_date(trade_date: str) -> None:
    datetime.strptime(trade_date, "%Y%m%d")


def _eastmoney_request_spec(
    secid: str,
    period: str,
) -> tuple[str, str, list[str], dict[str, str]]:
    if period == "1":
        return (
            _EASTMONEY_MINUTE_URL,
            "trends",
            ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"],
            {
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "ndays": "5",
                "iscr": "0",
                "secid": secid,
            },
        )
    return (
        _EASTMONEY_KLINE_URL,
        "klines",
        [
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
        ],
        {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "klt": period,
            "fqt": "0",
            "secid": secid,
            "beg": "0",
            "end": "20500000",
        },
    )


def _fetch_eastmoney_with_curl(
    ts_code: str,
    start_trade_date: str,
    end_trade_date: str,
    *,
    period: str,
) -> pd.DataFrame:
    del start_trade_date, end_trade_date
    curl_path = shutil.which("curl")
    if curl_path is None:
        raise FileNotFoundError("未找到 curl，无法使用东方财富直连回退路径")

    symbol = _normalize_symbol(ts_code)
    secid = f"{_eastmoney_market_id(symbol)}.{symbol}"
    url, rows_key, columns, params = _eastmoney_request_spec(secid, period)

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


def _fetch_sina_with_curl(
    ts_code: str,
    start_trade_date: str,
    end_trade_date: str,
    *,
    period: str,
) -> pd.DataFrame:
    del start_trade_date, end_trade_date
    if period == "1":
        raise ValueError("新浪历史分钟接口不提供可用的 1 分钟回退")

    curl_path = shutil.which("curl")
    if curl_path is None:
        raise FileNotFoundError("未找到 curl，无法使用新浪历史分钟回退路径")

    params = {
        "symbol": _sina_market_symbol(_normalize_symbol(ts_code)),
        "scale": period,
        "ma": "no",
        "datalen": _SINA_MAX_DATALEN,
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
        _SINA_KLINE_URL,
    ]
    for key, value in params.items():
        command.extend(["--data-urlencode", f"{key}={value}"])

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ConnectionError(f"curl 请求新浪历史分钟失败（exit={result.returncode}）: {detail}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"新浪返回的 curl 响应不是 JSON: {result.stdout[:200]!r}") from exc

    if not isinstance(payload, list):
        raise TypeError(f"新浪历史分钟响应不是列表: {payload!r}")
    columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量"]
    if not payload:
        return pd.DataFrame(columns=columns)
    if not all(isinstance(row, dict) for row in payload):
        raise ValueError("新浪历史分钟响应的行不是对象列表")

    raw = pd.DataFrame(payload).rename(
        columns={
            "day": "时间",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
        }
    )
    missing = [column for column in columns if column not in raw.columns]
    if missing:
        raise ValueError(f"新浪历史分钟响应缺少列: {missing}")
    return raw[columns]
