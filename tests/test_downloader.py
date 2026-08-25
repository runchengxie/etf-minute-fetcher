from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_minute_fetcher.downloader import DownloadConfig, DownloadEngine
from etf_minute_fetcher.models import Instrument


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
    def __init__(self):
        self.calls: list[str] = []

    def fetch(self, instrument, start_trade_date, end_trade_date, *, period):
        self.calls.append(instrument.ts_code)
        return _bars(instrument, start_trade_date)


def test_download_engine_writes_in_parallel_and_checkpoint(tmp_path: Path):
    provider = FakeProvider()
    checkpoint = tmp_path / "checkpoint.json"
    engine = DownloadEngine(
        DownloadConfig(workers=2, requests_per_second=0, checkpoint_path=checkpoint),
        provider=provider,
    )

    result = engine.download(
        [Instrument.from_ts_code("512880.SH"), Instrument.from_ts_code("159915.SZ")],
        ["20260824"],
        period="1",
        output_dir=tmp_path / "bars",
    )

    assert sorted(provider.calls) == ["159915.SZ", "512880.SH"]
    assert result["results"]["512880.SH"]["written"] == ["20260824"]
    assert (tmp_path / "bars/512880.SH/trade_date=20260824/part.parquet").exists()
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["symbols"]["159915.SZ"]["stats"]["written"] == ["20260824"]


def test_download_engine_retries_failed_symbol_task(tmp_path: Path):
    class FlakyProvider(FakeProvider):
        def fetch(self, instrument, start_trade_date, end_trade_date, *, period):
            self.calls.append(instrument.ts_code)
            if len(self.calls) == 1:
                raise ConnectionError("temporary")
            return _bars(instrument, start_trade_date)

    provider = FlakyProvider()
    engine = DownloadEngine(
        DownloadConfig(workers=1, requests_per_second=0, task_retries=1),
        provider=provider,
    )

    result = engine.download(
        [Instrument.from_ts_code("512880.SH")],
        ["20260824"],
        period="1",
        output_dir=tmp_path / "bars",
    )

    assert provider.calls == ["512880.SH", "512880.SH"]
    assert result["results"]["512880.SH"]["errors"] == {}
