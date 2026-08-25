from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

from etf_minute_fetcher.models import Instrument
from etf_minute_fetcher.universe import AkshareETFUniverse


def test_instrument_preserves_explicit_exchange():
    instrument = Instrument.from_ts_code("159915.SH")

    assert instrument.symbol == "159915"
    assert instrument.exchange == "SH"
    assert instrument.ts_code == "159915.SH"


def test_akshare_universe_filters_exchange_and_name(monkeypatch: pytest.MonkeyPatch):
    frame = pd.DataFrame(
        {
            "代码": ["510050", "159915", "512880"],
            "名称": ["上证50ETF", "创业板ETF", "证券ETF"],
            "市场": ["沪市", "深市", "沪市"],
        }
    )
    fake = types.SimpleNamespace(fund_etf_spot_em=lambda: frame)
    monkeypatch.setitem(sys.modules, "akshare", fake)

    result = AkshareETFUniverse(exchange="SH", name_contains="证券").get_instruments()

    assert [(item.ts_code, item.name) for item in result] == [("512880.SH", "证券ETF")]


def test_akshare_universe_uses_code_inference_when_market_column_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    frame = pd.DataFrame({"代码": [510050, 159915], "名称": ["上证50ETF", "创业板ETF"]})
    fake = types.SimpleNamespace(fund_etf_spot_em=lambda: frame)
    monkeypatch.setitem(sys.modules, "akshare", fake)

    result = AkshareETFUniverse().get_instruments()

    assert [item.ts_code for item in result] == ["510050.SH", "159915.SZ"]
