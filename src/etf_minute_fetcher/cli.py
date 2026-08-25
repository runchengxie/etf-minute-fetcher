"""etf-minute-fetcher 命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .downloader import DownloadConfig, DownloadEngine
from .models import Instrument
from .universe import AkshareETFUniverse, ExplicitUniverse, FileUniverse


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
    return Instrument.from_ts_code(symbol).ts_code


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    symbols: list[str] = []
    if args.symbols:
        symbols.extend(s.strip() for s in args.symbols.split(",") if s.strip())
    instruments: list[Instrument] = []
    if symbols:
        instruments.extend(ExplicitUniverse(symbols).get_instruments())
    if args.symbols_file:
        instruments.extend(FileUniverse(Path(args.symbols_file)).get_instruments())
    universe = getattr(args, "universe", None)
    exchange = getattr(args, "exchange", None)
    name_match = getattr(args, "match", None)
    if universe:
        if universe != "cn-etf":
            raise ValueError(f"不支持的 universe: {universe}")
        instruments.extend(
            AkshareETFUniverse(exchange=exchange, name_contains=name_match).get_instruments()
        )
    if (exchange or name_match) and not universe:
        raise ValueError("--exchange/--match 必须与 --universe cn-etf 一起使用")

    normalized: list[str] = []
    seen: set[str] = set()
    for instrument in instruments:
        if instrument.ts_code not in seen:
            normalized.append(instrument.ts_code)
            seen.add(instrument.ts_code)
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etf-min", description="抓取 ETF 分钟线 (akshare)")
    parser.add_argument("--symbols", help="逗号分隔的 ts_code 列表，如 512880.SH,159993.SZ")
    parser.add_argument("--symbols-file", help="每行一个 ts_code 的文件")
    parser.add_argument("--universe", choices=("cn-etf",), help="从当前沪深 ETF universe 自动发现标的")
    parser.add_argument("--exchange", choices=("SH", "SZ"), help="限制 universe 的交易所")
    parser.add_argument("--match", help="按 ETF 名称包含文本筛选 universe")
    parser.add_argument("--start", default=None, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    parser.add_argument("--days", type=int, default=5, help="未指定 start 时，从 end 往前覆盖的自然日数")
    parser.add_argument("--period", choices=("1", "5", "15", "30", "60"), default="1", help="分钟粒度")
    parser.add_argument("--out", required=True, help="输出根目录（将创建 ts_code/trade_date=* 分区）")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已存在的分区")
    parser.add_argument("--workers", type=int, default=4, help="并发下载的 ETF 数量，默认 4")
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=2.0,
        help="全局请求启动速率（请求/秒），0 表示不额外限速，默认 2",
    )
    parser.add_argument("--task-retries", type=int, default=1, help="单只 ETF 失败后的重试次数，默认 1")
    parser.add_argument("--checkpoint", default=None, help="checkpoint JSON 路径；默认写入输出根目录")
    args = parser.parse_args(argv)

    try:
        symbols = _resolve_symbols(args)
        end = args.end or _default_end()
        start = args.start or _start_from_end(end, args.days)
        trade_dates = _resolve_trade_dates(start, end)
    except (ValueError, FileNotFoundError, ImportError, RuntimeError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not symbols:
        print("ERROR: 必须通过 --symbols、--symbols-file 或 --universe 指定至少一只 ETF", file=sys.stderr)
        return 2

    output_dir = Path(args.out).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[etf-min] symbols={symbols}")
    print(f"[etf-min] 区间 {start}~{end}（{len(trade_dates)} 个自然日），period={args.period}")
    print(f"[etf-min] 输出 {output_dir}")
    if args.period == "1":
        print("[etf-min] 注意: AKShare/东方财富 1 分钟接口只提供最近 5 个交易日；更早日期会显示 empty")

    checkpoint_path = (
        Path(args.checkpoint).expanduser()
        if args.checkpoint
        else output_dir / ".etf-minute-checkpoint.json"
    )
    try:
        batch = DownloadEngine(
            DownloadConfig(
                workers=args.workers,
                requests_per_second=args.rate_limit,
                task_retries=args.task_retries,
                skip_existing=not args.no_skip,
                checkpoint_path=checkpoint_path,
            )
        ).download(
            [Instrument.from_ts_code(symbol) for symbol in symbols],
            trade_dates,
            period=args.period,
            output_dir=output_dir,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    total_written = total_skipped = total_empty = 0
    all_errors: dict[str, str] = {}
    for sym in symbols:
        stats = batch["results"].get(sym, {"written": [], "skipped": [], "empty": [], "errors": {}})
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
