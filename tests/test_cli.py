from __future__ import annotations

import argparse

import pytest

from etf_minute_fetcher.cli import _normalize_ts_code, _resolve_symbols, _resolve_trade_dates, _start_from_end
from etf_minute_fetcher.models import Instrument


def test_normalize_ts_code_infers_exchange():
    assert _normalize_ts_code("512880") == "512880.SH"
    assert _normalize_ts_code("159993") == "159993.SZ"
    assert _normalize_ts_code("159993.sz") == "159993.SZ"


def test_normalize_ts_code_rejects_bad_input():
    with pytest.raises(ValueError):
        _normalize_ts_code("51288")
    with pytest.raises(ValueError):
        _normalize_ts_code("512880.BJ")


def test_start_from_end_is_inclusive():
    assert _start_from_end("20260824", 5) == "20260820"


def test_resolve_trade_dates_rejects_reverse_range():
    with pytest.raises(ValueError, match="晚于"):
        _resolve_trade_dates("20260824", "20260821")


def test_resolve_symbols_deduplicates_and_reads_file(tmp_path):
    symbols_file = tmp_path / "symbols.txt"
    symbols_file.write_text("# comment\n159993\n512880.SH\n", encoding="utf-8")
    args = argparse.Namespace(symbols="512880,159993.SZ", symbols_file=str(symbols_file))

    assert _resolve_symbols(args) == ["512880.SH", "159993.SZ"]


def test_resolve_symbols_combines_current_universe(monkeypatch):
    monkeypatch.setattr(
        "etf_minute_fetcher.cli.AkshareETFUniverse.resolve",
        lambda self: [Instrument("512880", "SH"), Instrument("159993", "SZ")],
    )
    args = argparse.Namespace(
        symbols="512880.SH",
        symbols_file=None,
        universe="cn-etf",
        exchange=None,
    )

    assert _resolve_symbols(args) == ["512880.SH", "159993.SZ"]


def test_exchange_requires_universe():
    args = argparse.Namespace(symbols="512880.SH", symbols_file=None, universe=None, exchange="SH")
    with pytest.raises(ValueError, match="--exchange"):
        _resolve_symbols(args)
