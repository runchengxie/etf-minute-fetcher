"""ETF 分钟行情在线健康检查。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from .cli import _normalize_ts_code
from .fetcher import fetch_etf_minute_range

_REQUIRED_COLUMNS = {
    "ts_code",
    "trade_time",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
}
_CORE_COLUMNS = ["open", "high", "low", "close", "vol"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="etf-min-check",
        description="检查 ETF 分钟行情链路是否可用",
    )
    parser.add_argument(
        "--symbol",
        default="512880.SH",
        help="用于探测的 ETF，默认 512880.SH",
    )
    parser.add_argument(
        "--period",
        choices=("1", "5", "15", "30", "60"),
        default="1",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=14,
        help="探测窗口的自然日数，默认 14",
    )
    args = parser.parse_args(argv)

    if args.lookback_days < 1:
        print("FAIL: --lookback-days 必须 >= 1")
        return 2

    try:
        symbol = _normalize_ts_code(args.symbol)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 2

    end_date = date.today()
    start_date = end_date - timedelta(days=args.lookback_days - 1)
    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")

    try:
        frame = fetch_etf_minute_range(symbol, start, end, period=args.period)
    except Exception as exc:
        # 健康检查需要把上游、解析和网络异常都转换成可读的失败结果。
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1

    if frame.empty:
        print(f"FAIL: {symbol} 在 {start}~{end} 没有返回分钟数据")
        return 1

    missing = sorted(_REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        print(f"FAIL: 返回字段缺失: {missing}")
        return 1

    trade_dates = sorted(frame["trade_time"].dt.strftime("%Y%m%d").unique().tolist())
    first_ts = frame["trade_time"].min()
    last_ts = frame["trade_time"].max()
    core_nulls = int(frame[_CORE_COLUMNS].isna().sum().sum())
    amount_nulls = int(frame["amount"].isna().sum())

    try:
        import akshare as ak

        version = getattr(ak, "__version__", "unknown")
    except Exception:
        # 版本信息只用于诊断，读取失败不应掩盖已经成功的行情检查。
        version = "unknown"

    print(f"OK: akshare={version} symbol={symbol} period={args.period}")
    print(f"OK: rows={len(frame)} trade_dates={trade_dates}")
    print(f"OK: range={first_ts} ~ {last_ts} core_nulls={core_nulls} amount_nulls={amount_nulls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
