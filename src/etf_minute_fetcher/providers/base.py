"""Provider protocol used by the download engine."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from ..models import Instrument


class MinuteDataProvider(Protocol):
    def fetch(
        self,
        instrument: Instrument,
        start_trade_date: str,
        end_trade_date: str,
        *,
        period: str,
    ) -> pd.DataFrame:
        ...
