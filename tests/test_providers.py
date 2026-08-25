from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

from etf_minute_fetcher import providers


def test_standalone_provider_validates_period_before_network(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "akshare", types.SimpleNamespace())

    with pytest.raises(ValueError, match="period"):
        providers.AkshareMinuteProvider().fetch(
            "512880.SH",
            "20260824",
            "20260824",
            period="2",
        )


def test_fallback_provider_preserves_all_source_errors(monkeypatch: pytest.MonkeyPatch):
    def fail_akshare(self, *args, **kwargs):
        raise ConnectionError("akshare-down")

    def fail_eastmoney(self, *args, **kwargs):
        raise ConnectionError("eastmoney-down")

    def fail_sina(self, *args, **kwargs):
        raise ConnectionError("sina-down")

    monkeypatch.setattr(providers.AkshareMinuteProvider, "fetch", fail_akshare)
    monkeypatch.setattr(providers.EastMoneyCurlMinuteProvider, "fetch", fail_eastmoney)
    monkeypatch.setattr(providers.SinaCurlMinuteProvider, "fetch", fail_sina)

    with pytest.raises(RuntimeError) as excinfo:
        providers.FallbackMinuteProvider(attempts=1).fetch(
            "512880.SH",
            "20260824",
            "20260824",
            period="15",
        )

    message = str(excinfo.value)
    assert "akshare-down" in message
    assert "eastmoney-down" in message
    assert "sina-down" in message


def test_fallback_provider_continues_after_empty_primary(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def empty_akshare(self, *args, **kwargs):
        calls.append("akshare")
        return pd.DataFrame(columns=providers.OUTPUT_COLUMNS)

    def fail_eastmoney(self, *args, **kwargs):
        calls.append("eastmoney")
        raise ConnectionError("eastmoney-down")

    expected = pd.DataFrame(
        {
            "ts_code": ["512880.SH"],
            "trade_time": pd.to_datetime(["2026-08-24 09:45:00"]),
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "vol": [100.0],
            "amount": [pd.NA],
        }
    )

    def sina(self, *args, **kwargs):
        calls.append("sina")
        return expected

    monkeypatch.setattr(providers.AkshareMinuteProvider, "fetch", empty_akshare)
    monkeypatch.setattr(providers.EastMoneyCurlMinuteProvider, "fetch", fail_eastmoney)
    monkeypatch.setattr(providers.SinaCurlMinuteProvider, "fetch", sina)

    result = providers.FallbackMinuteProvider(attempts=1).fetch(
        "512880.SH",
        "20260824",
        "20260824",
        period="15",
    )

    assert calls == ["akshare", "eastmoney", "sina"]
    pd.testing.assert_frame_equal(result, expected)


def test_sina_provider_rejects_one_minute_before_curl(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(providers.shutil, "which", lambda name: "/usr/bin/curl")

    with pytest.raises(ValueError, match="1 分钟"):
        providers.SinaCurlMinuteProvider().fetch(
            "512880.SH",
            "20260824",
            "20260824",
            period="1",
        )
