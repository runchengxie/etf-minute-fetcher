from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from etf_minute_fetcher import check


def _frame(*, amount=None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["512880.SH"],
            "trade_time": pd.to_datetime(["2026-08-25 09:31:00"]),
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "vol": [100.0],
            "amount": [amount],
        }
    )


def test_health_check_accepts_missing_amount_from_fallback(monkeypatch, capsys):
    monkeypatch.setattr(check, "fetch_etf_minute_range", lambda *args, **kwargs: _frame())
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(__version__="1.18.94"))

    assert check.main(["--symbol", "512880.SH", "--period", "5"]) == 0

    output = capsys.readouterr().out
    assert "core_nulls=0" in output
    assert "amount_nulls=1" in output


def test_health_check_reports_fetch_failure(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(check, "fetch_etf_minute_range", fail)

    assert check.main(["--symbol", "512880.SH"]) == 1
    assert "ConnectionError: offline" in capsys.readouterr().out


def test_health_check_rejects_missing_columns(monkeypatch, capsys):
    frame = _frame(amount=10.0).drop(columns=["vol"])
    monkeypatch.setattr(check, "fetch_etf_minute_range", lambda *args, **kwargs: frame)

    assert check.main(["--symbol", "512880.SH"]) == 1
    assert "vol" in capsys.readouterr().out


def test_health_check_rejects_bad_arguments(capsys):
    assert check.main(["--lookback-days", "0"]) == 2
    assert "lookback-days" in capsys.readouterr().out

    assert check.main(["--symbol", "ABC"]) == 2
    assert "ETF 代码" in capsys.readouterr().out
