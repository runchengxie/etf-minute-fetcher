"""etf-minute-fetcher 命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .fetcher import fetch_symbol_range
from .universe import AkshareETFUniverse, ExplicitUniverse, FileUniverse, normalize_ts_code


def _default_end() -> str:
    return datetime.now().strftime("%Y%m%d")


def _start_from_end(end: str, days: int) -> str:
    if days < 1:
        raise ValueError("--days 必须 >= 1")
    end_dt = datetime.strptime(end, "%Y%m%d")
    return (end_dt - timedelta(days=days - 1)).strftime("%Y%m%d")


def _resolve_trade_dates(start: str, end: str) -> list[str]:
    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    if s > e:
        raise ValueError(f"起始日期 {start} 晚于结束日期 {end}")
    dates: list[str] = []
    cur = s
    while cur <= e:
        dates.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return dates


def _normalize_ts_code(symbol: str) -> str:
    """Backward-compatible wrapper around the shared universe normalizer."""

    return normalize_ts_code(symbol)


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    providers = []
    symbols_arg = getattr(args, "symbols", None)
    symbols_file = getattr(args, "symbols_file", None)
    universe_name = getattr(args, "universe", None)
    exchange = getattr(args, "exchange", None)

    if exchange and not universe_name:
        raise ValueError("--exchange 只能与 --universe 一起使用")

    if symbols_arg:
        providers.append(ExplicitUniverse([s.strip() for s in symbols_arg.split(",") if s.strip()]))
    if symbols_file:
        providers.append(FileUniverse(Path(symbols_file)))
    if universe_name == "cn-etf":
        providers.append(AkshareETFUniverse(exchange=exchange))

    normalized: list[str] = []
    seen: set[str] = set()
    for provider in providers:
        for instrument in provider.resolve():
            if instrument.ts_code not in seen:
                normalized.append(instrument.ts_code)
                seen.add(instrument.ts_code)
    return normalized


def _format_symbols_summary(symbols: list[str], *, preview: int = 10) -> str:
    if len(symbols) <= preview:
        return str(symbols)
    head = ", ".join(symbols[:preview])
    return f"[{head}, ...] (共 {len(symbols)} 只)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etf-min", description="抓取 ETF 分钟线 (akshare)")
    parser.add_argument("--symbols", help="逗号分隔的 ts_code 列表，如 512880.SH,159993.SZ")
    parser.add_argument("--symbols-file", help="每行一个 ts_code 的文件")
    parser.add_argument("--universe", choices=("cn-etf",), help="自动发现 ETF 标的集合；cn-etf=当前沪深 ETF")
    parser.add_argument("--exchange", choices=("SH", "SZ"), help="仅筛选 universe 中指定交易所 ETF")
    parser.add_argument("--start", default=None, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    parser.add_argument("--days", type=int, default=5, help="未指定 start 时，从 end 往前覆盖的自然日数")
    parser.add_argument("--period", choices=("1", "5", "15", "30", "60"), default="1", help="分钟粒度")
    parser.add_argument("--out", required=True, help="输出根目录（将创建 ts_code/trade_date=* 分区）")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已存在的分区")
    args = parser.parse_args(argv)

    try:
        symbols = _resolve_symbols(args)
        end = args.end or _default_end()
        start = args.start or _start_from_end(end, args.days)
        trade_dates = _resolve_trade_dates(start, end)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not symbols:
        print("ERROR: 必须通过 --symbols、--symbols-file 或 --universe 指定至少一只 ETF", file=sys.stderr)
        return 2

    output_dir = Path(args.out).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[etf-min] symbols={_format_symbols_summary(symbols)}")
    if args.universe:
        scope = f" exchange={args.exchange}" if args.exchange else ""
        print(f"[etf-min] universe={args.universe}{scope} resolved={len(symbols)}")
    print(f"[etf-min] 区间 {start}~{end}（{len(trade_dates)} 个自然日），period={args.period}")
    print(f"[etf-min] 输出 {output_dir}")
    if args.period == "1":
        print("[etf-min] 注意: AKShare/东方财富 1 分钟接口只提供最近 5 个交易日；更早日期会显示 empty")

    total_written = total_skipped = total_empty = 0
    all_errors: dict[str, str] = {}
    for sym in symbols:
        stats = fetch_symbol_range(
            sym,
            trade_dates,
            period=args.period,
            output_dir=output_dir / sym,
            skip_existing=not args.no_skip,
        )
        total_written += len(stats["written"])
        total_skipped += len(stats["skipped"])
        total_empty += len(stats["empty"])
        all_errors.update({f"{sym}/{k}": v for k, v in stats["errors"].items()})
        print(
            f"  {sym}: written={len(stats['written'])} "
            f"skipped={len(stats['skipped'])} empty={len(stats['empty'])} "
            f"errors={len(stats['errors'])}"
        )

    print(
        f"[etf-min] 汇总: written={total_written} skipped={total_skipped} "
        f"empty={total_empty} errors={len(all_errors)}"
    )
    if all_errors:
        for key, value in all_errors.items():
            print(f"  ERR {key}: {value}")
        return 1
    if total_written == 0 and total_skipped == 0:
        print("ERROR: 本次没有产生任何数据分区；请检查日期窗口、ETF 代码或上游接口状态", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
