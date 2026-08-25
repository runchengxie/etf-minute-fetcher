from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_minute_fetcher.engine import DownloadConfig, DownloadEngine
from etf_minute_fetcher.fetcher import fetch_symbol_range
from etf_minute_fetcher.models import Instrument
from etf_minute_fetcher.providers import legacy
from etf_minute_fetcher.providers.legacy import LegacyMinuteProvider
from etf_minute_fetcher.storage import ParquetStorage


def _bars(instrument: Instrument, trade_date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": [instrument.ts_code],
            "trade_time": [pd.Timestamp(f"{trade_date} 09:30:00")],
            "open": [1.0],
            "high": [1.01],
            "low": [0.99],
            "close": [1.0],
            "vol": [100.0],
            "amount": [10000.0],
        }
    )


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def fetch(self, instrument, start_trade_date, end_trade_date, *, period):
        self.calls.append((instrument.ts_code, start_trade_date, end_trade_date, period))
        return _bars(instrument, start_trade_date)


def test_fetch_symbol_range_uses_provider_and_storage(tmp_path: Path):
    provider = FakeProvider()
    storage = ParquetStorage(tmp_path / "bars")

    stats = fetch_symbol_range(
        "512880.SH",
        ["20260824"],
        output_dir=tmp_path / "legacy-symbol-root",
        provider=provider,
        storage=storage,
    )

    assert stats["written"] == ["20260824"]
    assert provider.calls == [("512880.SH", "20260824", "20260824", "1")]
    assert storage.partition_path(Instrument.from_ts_code("512880.SH"), "20260824").exists()


def test_download_engine_wires_default_fetcher_to_provider_and_storage(tmp_path: Path):
    provider = FakeProvider()
    storage = ParquetStorage(tmp_path / "bars")
    engine = DownloadEngine(
        DownloadConfig(workers=1, rate_limit_per_second=0, symbol_attempts=1, retry_delay=0),
        provider=provider,
        storage=storage,
    )

    summary = engine.run(
        ["512880.SH"],
        ["20260824"],
        period="1",
        output_dir=tmp_path / "bars",
    )

    assert summary.completed_symbols == 1
    assert provider.calls == [("512880.SH", "20260824", "20260824", "1")]
    assert storage.partition_path(Instrument.from_ts_code("512880.SH"), "20260824").exists()


def test_legacy_provider_delegates_to_existing_fetcher(monkeypatch):
    calls = []

    def fake_fetch(ts_code, start_trade_date, end_trade_date, *, period, source):
        calls.append((ts_code, start_trade_date, end_trade_date, period, source))
        return pd.DataFrame()

    monkeypatch.setattr(legacy, "fetch_etf_minute_range", fake_fetch)
    LegacyMinuteProvider().fetch(
        Instrument.from_ts_code("512880.SH"),
        "20260824",
        "20260824",
        period="15",
        source="sina",
    )

    assert calls == [("512880.SH", "20260824", "20260824", "15", "sina")]
