from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_minute_fetcher.models import Instrument, infer_etf_exchange
from etf_minute_fetcher.universe import AkshareETFUniverse, ExplicitUniverse


def test_instrument_normalizes_and_formats_ts_code():
    instrument = Instrument("512880", "sh", name=" 证券ETF ")
    assert instrument.exchange == "SH"
    assert instrument.name == "证券ETF"
    assert instrument.ts_code == "512880.SH"


def test_infer_etf_exchange_matches_current_market_rule():
    assert infer_etf_exchange("512880") == "SH"
    assert infer_etf_exchange("159993") == "SZ"


def test_explicit_universe_deduplicates():
    universe = ExplicitUniverse(["512880", "512880.SH", "159993.sz"])
    assert [item.ts_code for item in universe.resolve()] == ["512880.SH", "159993.SZ"]


def test_akshare_universe_discovers_and_filters_exchange(monkeypatch):
    frame = pd.DataFrame(
        {
            "代码": ["512880", "159993", "510300"],
            "名称": ["证券ETF", "医药ETF", "300ETF"],
        }
    )
    fake_akshare = SimpleNamespace(fund_etf_spot_em=lambda: frame)
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    instruments = AkshareETFUniverse(exchange="SH").resolve()

    assert [(item.ts_code, item.name) for item in instruments] == [
        ("512880.SH", "证券ETF"),
        ("510300.SH", "300ETF"),
    ]


def test_akshare_universe_rejects_schema_drift(monkeypatch):
    fake_akshare = SimpleNamespace(fund_etf_spot_em=lambda: pd.DataFrame({"代码": ["512880"]}))
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    with pytest.raises(ValueError, match="缺少列"):
        AkshareETFUniverse().resolve()
