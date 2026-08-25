from __future__ import annotations

import argparse

import pytest

from etf_minute_fetcher.cli import _normalize_ts_code, _resolve_symbols, _resolve_trade_dates, _start_from_end


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


def test_resolve_symbols_accepts_current_etf_universe(monkeypatch):
    class FakeUniverse:
        def __init__(self, *, exchange, name_contains):
            assert exchange == "SH"
            assert name_contains == "红利"

        def get_instruments(self):
            from etf_minute_fetcher.models import Instrument

            return [Instrument.from_ts_code("515080.SH", name="红利低波")]

    monkeypatch.setattr("etf_minute_fetcher.cli.AkshareETFUniverse", FakeUniverse)
    args = argparse.Namespace(
        symbols=None,
        symbols_file=None,
        universe="cn-etf",
        exchange="SH",
        match="红利",
    )

    assert _resolve_symbols(args) == ["515080.SH"]
