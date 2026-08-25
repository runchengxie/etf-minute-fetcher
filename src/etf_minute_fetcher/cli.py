"""etf-minute-fetcher 命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .engine import DownloadConfig, DownloadEngine
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
    name_contains = getattr(args, "name_contains", None)
    fund_type = getattr(args, "fund_type", None)
    as_of = getattr(args, "as_of", None)

    universe_only_filters = {
        "--exchange": exchange,
        "--name-contains": name_contains,
        "--fund-type": fund_type,
        "--as-of": as_of,
    }
    invalid_filters = [flag for flag, value in universe_only_filters.items() if value and not universe_name]
    if invalid_filters:
        raise ValueError(f"{', '.join(invalid_filters)} 只能与 --universe 一起使用")

    if symbols_arg:
        providers.append(ExplicitUniverse([s.strip() for s in symbols_arg.split(",") if s.strip()]))
    if symbols_file:
        providers.append(FileUniverse(Path(symbols_file)))
    if universe_name == "cn-etf":
        providers.append(
            AkshareETFUniverse(
                exchange=exchange,
                name_contains=name_contains,
                fund_type=fund_type,
                as_of=as_of,
            )
        )

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
    parser.add_argument("--universe", choices=("cn-etf",), help="自动发现 ETF 标的集合；cn-etf=沪深 ETF")
    parser.add_argument("--exchange", choices=("SH", "SZ"), help="仅筛选 universe 中指定交易所 ETF")
    parser.add_argument("--name-contains", help="按 ETF 名称包含关系筛选 universe")
    parser.add_argument("--fund-type", help="按 AKShare/同花顺基金类型精确筛选，如 股票型、债券型")
    parser.add_argument("--as-of", help="按 YYYYMMDD 获取历史 point-in-time ETF universe")
    parser.add_argument("--start", default=None, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    parser.add_argument("--days", type=int, default=5, help="未指定 start 时，从 end 往前覆盖的自然日数")
    parser.add_argument("--period", choices=("1", "5", "15", "30", "60"), default="1", help="分钟粒度")
    parser.add_argument("--out", required=True, help="输出根目录（将创建 ts_code/trade_date=* 分区）")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已存在的分区")
    parser.add_argument("--workers", type=int, default=4, help="批量下载最大并发 ETF 数，默认 4")
    parser.add_argument("--rate-limit", type=float, default=2.0, help="每秒最多启动的 ETF 请求任务数；0=不限速")
    parser.add_argument("--symbol-attempts", type=int, default=2, help="失败 ETF 的批量级最大尝试次数")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="失败重试轮次之间的基础等待秒数")
    parser.add_argument("--checkpoint", help="checkpoint JSON；默认 <out>/.download-checkpoint.json")
    parser.add_argument("--stats-file", help="批量统计 JSON；默认 <out>/.download-summary.json")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有 checkpoint，重新调度所有标的")
    args = parser.parse_args(argv)

    try:
        symbols = _resolve_symbols(args)
        end = args.end or _default_end()
        start = args.start or _start_from_end(end, args.days)
        trade_dates = _resolve_trade_dates(start, end)
        config = DownloadConfig(
            workers=args.workers,
            rate_limit_per_second=args.rate_limit,
            symbol_attempts=args.symbol_attempts,
            retry_delay=args.retry_delay,
            resume=not args.no_resume,
        )
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
        filters = []
        if args.exchange:
            filters.append(f"exchange={args.exchange}")
        if args.name_contains:
            filters.append(f"name~={args.name_contains!r}")
        if args.fund_type:
            filters.append(f"fund_type={args.fund_type!r}")
        if args.as_of:
            filters.append(f"as_of={args.as_of}")
        scope = " " + " ".join(filters) if filters else ""
        print(f"[etf-min] universe={args.universe}{scope} resolved={len(symbols)}")
    print(f"[etf-min] 区间 {start}~{end}（{len(trade_dates)} 个自然日），period={args.period}")
    print(
        f"[etf-min] 调度 workers={config.workers} rate_limit={config.rate_limit_per_second}/s "
        f"symbol_attempts={config.symbol_attempts} resume={config.resume}"
    )
    print(f"[etf-min] 输出 {output_dir}")
    if args.period == "1":
        print("[etf-min] 注意: AKShare/东方财富 1 分钟接口只提供最近 5 个交易日；更早日期会显示 empty")

    checkpoint_path = Path(args.checkpoint).expanduser().resolve() if args.checkpoint else None
    stats_path = Path(args.stats_file).expanduser().resolve() if args.stats_file else None
    try:
        summary = DownloadEngine(config).run(
            symbols,
            trade_dates,
            period=args.period,
            output_dir=output_dir,
            skip_existing=not args.no_skip,
            checkpoint_path=checkpoint_path,
            stats_path=stats_path,
        )
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"[etf-min] 汇总: completed={summary.completed_symbols}/{summary.total_symbols} "
        f"resumed={summary.resumed_symbols} written={summary.written_partitions} "
        f"skipped={summary.skipped_partitions} empty={summary.empty_partitions} "
        f"failed={summary.failed_symbols}"
    )
    if summary.failures:
        for symbol, message in summary.failures.items():
            print(f"  ERR {symbol}: {message}")
        return 1
    if summary.written_partitions == 0 and summary.skipped_partitions == 0:
        print("ERROR: 本次没有产生任何数据分区；请检查日期窗口、ETF 代码或上游接口状态", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
