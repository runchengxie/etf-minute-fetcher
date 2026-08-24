"""AKShare / 东方财富 ETF 分钟线现场健康检查。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from .cli import _normalize_ts_code
from .fetcher import fetch_etf_minute_range


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etf-min-check", description="检查 AKShare ETF 分钟接口是否可用")
    parser.add_argument("--symbol", default="512880.SH", help="用于探测的 ETF，默认 512880.SH")
    parser.add_argument("--period", choices=("1", "5", "15", "30", "60"), default="1")
    parser.add_argument("--lookback-days", type=int, default=14, help="探测窗口自然日数，默认 14")
    args = parser.parse_args(argv)

    if args.lookback_days < 1:
        print("FAIL: --lookback-days 必须 >= 1")
        return 2

    try:
        symbol = _normalize_ts_code(args.symbol)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 2

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=args.lookback_days - 1)
    start = start_dt.strftime("%Y%m%d")
    end = end_dt.strftime("%Y%m%d")

    try:
        frame = fetch_etf_minute_range(symbol, start, end, period=args.period)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1

    if frame.empty:
        print(f"FAIL: {symbol} 在 {start}~{end} 没有返回分钟数据")
        return 1

    required = {"ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        print(f"FAIL: 返回 schema 缺列: {missing}")
        return 1

    trade_dates = sorted(frame["trade_time"].dt.strftime("%Y%m%d").unique().tolist())
    first_ts = frame["trade_time"].min()
    last_ts = frame["trade_time"].max()
    core_nulls = int(frame[["open", "high", "low", "close", "vol", "amount"]].isna().sum().sum())

    try:
        import akshare as ak

        version = getattr(ak, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        version = "unknown"

    print(f"OK: akshare={version} symbol={symbol} period={args.period}")
    print(f"OK: rows={len(frame)} trade_dates={trade_dates}")
    print(f"OK: range={first_ts} ~ {last_ts} core_nulls={core_nulls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
