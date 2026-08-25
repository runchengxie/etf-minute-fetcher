from __future__ import annotations

import sys
import types

import pytest

import etf_minute_fetcher.providers as providers


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


def test_sina_provider_rejects_one_minute_before_curl(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(providers.shutil, "which", lambda name: "/usr/bin/curl")

    with pytest.raises(ValueError, match="1 分钟"):
        providers.SinaCurlMinuteProvider().fetch(
            "512880.SH",
            "20260824",
            "20260824",
            period="1",
        )
