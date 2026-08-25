"""Public ETF minute-fetch orchestration API.

Provider-specific network behavior lives in :mod:`etf_minute_fetcher.providers` and
persistence lives in :mod:`etf_minute_fetcher.storage`. This module keeps the original
public functions as stable compatibility boundaries for callers and the DownloadEngine.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .providers import FallbackMinuteProvider, MinuteDataProvider, OUTPUT_COLUMNS, validate_request
from .storage import BarStorage, ParquetBarStorage

# Backward-compatible schema constant used by callers/tests.
_OUTPUT_COLUMNS = OUTPUT_COLUMNS


def _validate_trade_date(trade_date: str) -> None:
    datetime.strptime(trade_date, "%Y%m%d")


def fetch_etf_minute_range(
    ts_code: str,
    start_trade_date: str,
    end_trade_date: str,
    *,
    period: str = "1",
    attempts: int = 3,
    retry_delay: float = 1.0,
    provider: MinuteDataProvider | None = None,
) -> pd.DataFrame:
    """Fetch normalized minute bars for one ETF and date range.

    When ``provider`` is omitted the default fallback chain remains AKShare ->
    EastMoney curl -> Sina curl. Supplying a provider makes the network source
    replaceable without changing callers.
    """
    validate_request(start_trade_date, end_trade_date, period)
    if attempts < 1:
        raise ValueError("attempts 必须 >= 1")
    if retry_delay < 0:
        raise ValueError("retry_delay 必须 >= 0")
    resolved_provider = provider or FallbackMinuteProvider(attempts=attempts, retry_delay=retry_delay)
    return resolved_provider.fetch(
        ts_code,
        start_trade_date,
        end_trade_date,
        period=period,
    )


def fetch_etf_minute(
    ts_code: str,
    trade_date: str,
    *,
    period: str = "1",
    provider: MinuteDataProvider | None = None,
) -> pd.DataFrame:
    """Fetch one trading day's normalized minute bars."""
    return fetch_etf_minute_range(
        ts_code,
        trade_date,
        trade_date,
        period=period,
        provider=provider,
    )


def write_partition(
    df: pd.DataFrame,
    output_dir: Path,
    trade_date: str,
    *,
    storage: BarStorage | None = None,
) -> Path | None:
    """Write one trade-date partition using the configured storage adapter."""
    resolved_storage = storage or ParquetBarStorage()
    return resolved_storage.write(df, output_dir, trade_date)


def fetch_symbol_range(
    ts_code: str,
    trade_dates: list[str],
    *,
    period: str = "1",
    output_dir: Path,
    skip_existing: bool = True,
    provider: MinuteDataProvider | None = None,
    storage: BarStorage | None = None,
) -> dict[str, Any]:
    """Fetch one ETF across multiple dates and persist date partitions.

    The orchestration layer depends only on ``MinuteDataProvider`` and ``BarStorage``.
    Existing callers can omit both and retain the original behavior.
    """
    written: list[str] = []
    skipped: list[str] = []
    empty: list[str] = []
    errors: dict[str, str] = {}
    pending: list[str] = []
    resolved_storage = storage or ParquetBarStorage()

    for td in trade_dates:
        _validate_trade_date(td)
        if skip_existing and resolved_storage.exists(output_dir, td):
            skipped.append(td)
            continue
        pending.append(td)

    if not pending:
        return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}

    try:
        frame = fetch_etf_minute_range(
            ts_code,
            min(pending),
            max(pending),
            period=period,
            provider=provider,
        )
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        errors.update({td: message for td in pending})
        return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}

    if frame.empty:
        empty.extend(pending)
        return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}

    frame_trade_dates = frame["trade_time"].dt.strftime("%Y%m%d")
    for td in pending:
        day_df = frame.loc[frame_trade_dates == td].copy()
        if day_df.empty:
            empty.append(td)
            continue
        resolved_storage.write(day_df, output_dir, td)
        written.append(td)
    return {"written": written, "skipped": skipped, "empty": empty, "errors": errors}
