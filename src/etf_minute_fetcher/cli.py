"""etf-minute-fetcher 命令行入口。

示例：
    # 拉 512880.SH（证券ETF）最近约5个交易日，1分钟线
    etf-min --symbols 512880.SH --days 5 --out ~/data/market-data-platform/assets/tushare/etf/minute/fund_min_1m

    # 拉多只 + 指定日期区间
    etf-min --symbols 515080.SH,515100.SH --start 20260811 --end 20260818 --out <dir>

    # 从文件读代码列表（每行一个 ts_code）
    etf-min --symbols-file symbols.txt --start 20260811 --end 20260818 --out <dir>
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .fetcher import fetch_symbol_range


def _default_end() -> str:
    return datetime.now().strftime("%Y%m%d")


def _default_start(days: int = 5) -> str:
    # 粗略往前推 days 个自然日（含周末，抓取时会自动跳过无数据日）
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


def _resolve_trade_dates(start: str, end: str) -> list[str]:
    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    dates: list[str] = []
    cur = s
    while cur <= e:
        dates.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return dates


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    symbols: list[str] = []
    if args.symbols:
        symbols.extend(s.strip() for s in args.symbols.split(",") if s.strip())
    if args.symbols_file:
        p = Path(args.symbols_file)
        if p.exists():
            symbols.extend(
                line.strip() for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            )
    # 补齐 .SH 后缀（沪市 ETF 默认）
    norm: list[str] = []
    for sym in symbols:
        if "." not in sym:
            norm.append(f"{sym}.SH")
        else:
            norm.append(sym.upper())
    return norm


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etf-min", description="抓取 ETF 分钟线 (akshare)")
    parser.add_argument("--symbols", help="逗号分隔的 ts_code 列表，如 512880.SH,515080.SH")
    parser.add_argument("--symbols-file", help="每行一个 ts_code 的文件")
    parser.add_argument("--start", default=None, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    parser.add_argument("--days", type=int, default=5, help="未指定 start/end 时往前推的自然日数")
    parser.add_argument("--period", default="1", help="分钟粒度 1/5/15/30/60")
    parser.add_argument("--out", required=True, help="输出根目录（将创建 trade_date=* 分区）")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已存在的分区")
    args = parser.parse_args(argv)

    symbols = _resolve_symbols(args)
    if not symbols:
        print("ERROR: 必须通过 --symbols 或 --symbols-file 指定至少一只 ETF", file=sys.stderr)
        return 2

    start = args.start or _default_start(args.days)
    end = args.end or _default_end()
    trade_dates = _resolve_trade_dates(start, end)
    output_dir = Path(args.out).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[etf-min] symbols={symbols}")
    print(f"[etf-min] 区间 {start}~{end}（{len(trade_dates)} 个自然日），period={args.period}")
    print(f"[etf-min] 输出 {output_dir}")

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
        for k, v in all_errors.items():
            print(f"  ERR {k}: {v}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
