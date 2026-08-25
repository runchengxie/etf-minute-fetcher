"""Adapter around the existing AKShare/EastMoney/Sina fetch implementation."""

from __future__ import annotations

import pandas as pd

from ..fetcher import fetch_etf_minute_range
from ..models import Instrument


class LegacyMinuteProvider:
    """Keep the current concrete fetcher behind the provider boundary.

    The network-specific implementation remains in ``fetcher.py`` for backward
    compatibility in this first extraction. New engines and callers depend on
    this adapter contract instead of importing those details directly.
    """

    def fetch(
        self,
        instrument: Instrument,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str,
        source: str = "auto",
    ) -> pd.DataFrame:
        return fetch_etf_minute_range(
            instrument.ts_code,
            start_trade_date,
            end_trade_date,
            period=period,
            source=source,
        )
