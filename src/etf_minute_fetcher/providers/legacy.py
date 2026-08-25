"""Adapter around the existing fetcher implementation."""

from __future__ import annotations

import pandas as pd

from ..fetcher import fetch_etf_minute_range
from ..models import Instrument


class LegacyMinuteDataProvider:
    """Keep the current AKShare/curl/Sina implementation behind a provider seam."""

    def fetch(
        self,
        instrument: Instrument,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str,
    ) -> pd.DataFrame:
        return fetch_etf_minute_range(
            instrument.ts_code,
            start_trade_date,
            end_trade_date,
            period=period,
        )
