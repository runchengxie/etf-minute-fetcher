"""etf-minute-fetcher 命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .fetcher import fetch_symbol_range

_VALID_SUFFIXES = {"SH", "SZ"}


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
    raw = symbol.strip().upper()
    if not raw:
        raise ValueError("ETF 代码不能为空")

    if "." in raw:
        code, suffix = raw.rsplit(".", 1)
        if suffix not in _VALID_SUFFIXES:
            raise ValueError(f"不支持的交易所后缀: {raw}")
    else:
        code = raw
        # 与 akshare 当前 ETF market id 规则一致：5/6 开头走上交所，其余走深交所。
        suffix = "SH" if code.startswith(("5", "6")) else "SZ"

    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"ETF 代码应为 6 位数字: {symbol!r}")
    return f"{code}.{suffix}"


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    symbols: list[str] = []
    if args.symbols:
        symbols.extend(s.strip() for s in args.symbols.split(",") if s.strip())
    if args.symbols_file:
        p = Path(args.symbols_file)
        if not p.exists():
            raise FileNotFoundError(f"symbols file 不存在: {p}")
        symbols.extend(
            line.strip()
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        ts_code = _normalize_ts_code(symbol)
        if ts_code not in seen:
            normalized.append(ts_code)
            seen.add(ts_code)
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etf-min", description="抓取 ETF 分钟线 (akshare)")
    parser.add_argument("--symbols", help="逗号分隔的 ts_code 列表，如 512880.SH,159993.SZ")
    parser.add_argument("--symbols-file", help="每行一个 ts_code 的文件")
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
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not symbols:
        print("ERROR: 必须通过 --symbols 或 --symbols-file 指定至少一只 ETF", file=sys.stderr)
        return 2

    output_dir = Path(args.out).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[etf-min] symbols={symbols}")
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
