from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

import etf_minute_fetcher.fetcher as fetcher
import etf_minute_fetcher.providers as providers
from etf_minute_fetcher.storage import ParquetBarStorage


def _install_fake_akshare(
    monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame
) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []

    def fund_etf_hist_min_em(**kwargs):
        calls.append(kwargs)
        return frame.copy()

    fake = types.SimpleNamespace(fund_etf_hist_min_em=fund_etf_hist_min_em)
    monkeypatch.setitem(sys.modules, "akshare", fake)
    return calls


def _minute_frame(*trade_times: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["512880.SH"] * len(trade_times),
            "trade_time": [pd.Timestamp(value) for value in trade_times],
            "open": [1.0] * len(trade_times),
            "high": [1.01] * len(trade_times),
            "low": [0.99] * len(trade_times),
            "close": [1.0] * len(trade_times),
            "vol": [100.0] * len(trade_times),
            "amount": [10000.0] * len(trade_times),
        }
    )


def test_fetch_etf_minute_normalizes_columns(monkeypatch: pytest.MonkeyPatch):
    raw = pd.DataFrame(
        {
            "时间": ["2026-08-24 09:30:00", "2026-08-24 09:31:00"],
            "开盘": [1.0, 1.01],
            "收盘": [1.01, 1.02],
            "最高": [1.02, 1.03],
            "最低": [0.99, 1.0],
            "成交量": [100, 200],
            "成交额": [10000.0, 20200.0],
            "均价": [1.0, 1.01],
        }
    )
    calls = _install_fake_akshare(monkeypatch, raw)

    result = fetcher.fetch_etf_minute("512880.SH", "20260824")

    assert list(result.columns) == fetcher._OUTPUT_COLUMNS
    assert result["ts_code"].tolist() == ["512880.SH", "512880.SH"]
    assert pd.api.types.is_datetime64_any_dtype(result["trade_time"])
    assert calls == [
        {
            "symbol": "512880",
            "period": "1",
            "start_date": "20260824 09:30:00",
            "end_date": "20260824 15:00:00",
        }
    ]


def test_fetch_range_keeps_stable_schema_when_optional_column_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    raw = pd.DataFrame(
        {
            "时间": ["2026-08-24 09:30:00"],
            "开盘": [1.0],
            "收盘": [1.0],
            "最高": [1.0],
            "最低": [1.0],
            "成交量": [100],
        }
    )
    _install_fake_akshare(monkeypatch, raw)

    result = fetcher.fetch_etf_minute_range("512880.SH", "20260824", "20260824")

    assert list(result.columns) == fetcher._OUTPUT_COLUMNS
    assert result["amount"].isna().all()


def test_fetch_range_rejects_bad_period(monkeypatch: pytest.MonkeyPatch):
    _install_fake_akshare(monkeypatch, pd.DataFrame())

    with pytest.raises(ValueError, match="period"):
        fetcher.fetch_etf_minute_range("512880.SH", "20260824", "20260824", period="2")


def test_fetch_range_rejects_reverse_dates(monkeypatch: pytest.MonkeyPatch):
    _install_fake_akshare(monkeypatch, pd.DataFrame())

    with pytest.raises(ValueError, match="晚于"):
        fetcher.fetch_etf_minute_range("512880.SH", "20260824", "20260821")


def test_fetch_range_retries_transient_error(monkeypatch: pytest.MonkeyPatch):
    calls = 0
    sleeps: list[float] = []
    raw = pd.DataFrame(
        {
            "时间": ["2026-08-24 09:30:00"],
            "开盘": [1.0],
            "收盘": [1.0],
            "最高": [1.0],
            "最低": [1.0],
            "成交量": [100],
            "成交额": [10000.0],
        }
    )

    def fund_etf_hist_min_em(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("temporary disconnect")
        return raw.copy()

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(fund_etf_hist_min_em=fund_etf_hist_min_em),
    )
    monkeypatch.setattr(providers.time, "sleep", sleeps.append)

    result = fetcher.fetch_etf_minute_range(
        "512880.SH",
        "20260824",
        "20260824",
        attempts=3,
        retry_delay=0.25,
    )

    assert len(result) == 1
    assert calls == 3
    assert sleeps == [0.25, 0.5]


def test_fetch_range_accepts_injected_provider():
    class FakeProvider:
        def fetch(self, ts_code, start_trade_date, end_trade_date, *, period="1"):
            return _minute_frame("2026-08-24 09:30:00")

    result = fetcher.fetch_etf_minute_range(
        "512880.SH",
        "20260824",
        "20260824",
        provider=FakeProvider(),
    )

    assert len(result) == 1


def test_write_partition(tmp_path: Path):
    frame = _minute_frame("2026-08-24 09:30:00")

    out = fetcher.write_partition(frame, tmp_path, "20260824")

    assert out == tmp_path / "trade_date=20260824" / "part.parquet"
    loaded = pd.read_parquet(out)
    pd.testing.assert_frame_equal(loaded, frame)


def test_fetch_symbol_range_uses_one_upstream_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    calls: list[tuple[str, str, str, str]] = []

    def fake_fetch_range(
        ts_code: str,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str = "1",
        provider=None,
    ) -> pd.DataFrame:
        calls.append((ts_code, start_trade_date, end_trade_date, period))
        return _minute_frame("2026-08-23 09:30:00", "2026-08-24 09:30:00")

    monkeypatch.setattr(fetcher, "fetch_etf_minute_range", fake_fetch_range)
    existing = tmp_path / "trade_date=20260822"
    existing.mkdir(parents=True)
    (existing / "part.parquet").touch()

    stats = fetcher.fetch_symbol_range(
        "512880.SH",
        ["20260822", "20260823", "20260824"],
        output_dir=tmp_path,
    )

    assert calls == [("512880.SH", "20260823", "20260824", "1")]
    assert stats == {
        "written": ["20260823", "20260824"],
        "skipped": ["20260822"],
        "empty": [],
        "errors": {},
    }


def test_fetch_symbol_range_marks_dates_without_rows_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(
        fetcher,
        "fetch_etf_minute_range",
        lambda *args, **kwargs: _minute_frame("2026-08-24 09:30:00"),
    )

    stats = fetcher.fetch_symbol_range(
        "512880.SH",
        ["20260823", "20260824"],
        output_dir=tmp_path,
    )

    assert stats["written"] == ["20260824"]
    assert stats["empty"] == ["20260823"]


def test_fetch_symbol_range_accepts_storage_adapter(tmp_path: Path):
    writes: list[str] = []

    class MemoryStorage:
        def exists(self, output_dir, trade_date):
            return trade_date == "20260823"

        def write(self, df, output_dir, trade_date):
            writes.append(trade_date)
            return None

    class FakeProvider:
        def fetch(self, ts_code, start_trade_date, end_trade_date, *, period="1"):
            return _minute_frame("2026-08-24 09:30:00")

    stats = fetcher.fetch_symbol_range(
        "512880.SH",
        ["20260823", "20260824"],
        output_dir=tmp_path,
        provider=FakeProvider(),
        storage=MemoryStorage(),
    )

    assert stats["skipped"] == ["20260823"]
    assert stats["written"] == ["20260824"]
    assert writes == ["20260824"]


def test_parquet_storage_partition_path(tmp_path: Path):
    storage = ParquetBarStorage()
    assert (
        storage.partition_path(tmp_path, "20260824")
        == tmp_path / "trade_date=20260824" / "part.parquet"
    )


def test_curl_fallback_parses_minute_response(monkeypatch: pytest.MonkeyPatch):
    response = {
        "data": {
            "trends": [
                "2026-08-24 09:30,1.000,1.001,1.002,0.999,100,10000.0,1.0005",
            ]
        }
    }
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

    monkeypatch.setattr(providers.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    result = providers._fetch_eastmoney_with_curl(
        "512880.SH",
        "20260824",
        "20260824",
        period="1",
    )

    assert result.columns.tolist() == [
        "时间",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "均价",
    ]
    assert result.iloc[0]["成交量"] == "100"
    assert calls[0][calls[0].index("--noproxy") + 1] == "*"
    assert "secid=1.512880" in calls[0]


def test_sina_fallback_parses_historical_minute_response(monkeypatch: pytest.MonkeyPatch):
    response = [
        {
            "day": "2026-08-24 09:30:00",
            "open": "1.000",
            "high": "1.002",
            "low": "0.999",
            "close": "1.001",
            "volume": "100",
        }
    ]
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

    monkeypatch.setattr(providers.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(providers.subprocess, "run", fake_run)

    result = providers._fetch_sina_with_curl(
        "512880.SH",
        "20260824",
        "20260824",
        period="15",
    )

    assert result.columns.tolist() == ["时间", "开盘", "收盘", "最高", "最低", "成交量"]
    assert result.iloc[0]["成交量"] == "100"
    assert calls[0][calls[0].index("--noproxy") + 1] == "*"
    assert "symbol=sh512880" in calls[0]
    assert "scale=15" in calls[0]
    assert "datalen=20000" in calls[0]


def test_fetch_range_uses_curl_fallback_after_akshare_failure(monkeypatch: pytest.MonkeyPatch):
    def always_fail(**kwargs):
        raise ConnectionError("requests path unavailable")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(fund_etf_hist_min_em=always_fail),
    )
    raw = pd.DataFrame(
        {
            "时间": ["2026-08-19 09:30:00", "2026-08-24 09:30:00"],
            "开盘": [1.0, 1.1],
            "收盘": [1.0, 1.1],
            "最高": [1.0, 1.1],
            "最低": [1.0, 1.1],
            "成交量": [100, 110],
            "成交额": [10000, 11000],
            "均价": [1.0, 1.1],
        }
    )
    monkeypatch.setattr(providers, "_fetch_eastmoney_with_curl", lambda *args, **kwargs: raw)

    result = fetcher.fetch_etf_minute_range(
        "512880.SH",
        "20260824",
        "20260824",
        attempts=1,
    )

    assert len(result) == 1
    assert result.iloc[0]["trade_time"] == pd.Timestamp("2026-08-24 09:30:00")


def test_fetch_range_uses_sina_after_eastmoney_failure(monkeypatch: pytest.MonkeyPatch):
    def always_fail(**kwargs):
        raise ConnectionError("requests path unavailable")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(fund_etf_hist_min_em=always_fail),
    )
    raw = pd.DataFrame(
        {
            "时间": ["2026-08-19 09:30:00", "2026-08-24 09:30:00"],
            "开盘": [1.0, 1.1],
            "收盘": [1.0, 1.1],
            "最高": [1.0, 1.1],
            "最低": [1.0, 1.1],
            "成交量": [100, 110],
        }
    )
    monkeypatch.setattr(
        providers,
        "_fetch_eastmoney_with_curl",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("eastmoney unavailable")),
    )
    monkeypatch.setattr(providers, "_fetch_sina_with_curl", lambda *args, **kwargs: raw)

    result = fetcher.fetch_etf_minute_range(
        "512880.SH",
        "20260824",
        "20260824",
        period="15",
        attempts=1,
    )

    assert len(result) == 1
    assert result.iloc[0]["trade_time"] == pd.Timestamp("2026-08-24 09:30:00")
    assert result["amount"].isna().all()
