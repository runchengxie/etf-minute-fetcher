# Architecture

## Current data flow

```text
UniverseProvider
    ↓
Instrument
    ↓
DownloadEngine
    ↓
MinuteDataProvider
    ↓
BarStorage
    ↓
trade_date partitioned Parquet
```

The command line supports three universe inputs:

- explicit `--symbols`
- `--symbols-file`
- current `--universe cn-etf`, backed by AKShare `fund_etf_spot_em()`

`AkshareETFUniverse` can filter by exchange and name. The provider returns the
current listed universe only. Historical listing and delisting dates are not
available in this first slice, so it must not be treated as a point-in-time
backtest universe.

## Download engine

`DownloadEngine` owns batch concerns that should not live in the CLI:

- bounded `ThreadPoolExecutor` concurrency
- global request-start rate limiting
- per-symbol task retries
- atomic JSON checkpoint updates
- skip-existing partition behavior

The checkpoint records the latest result per symbol. Parquet partition existence
remains the source of truth for resuming a partially completed date range.

## Provider and storage seams

`MinuteDataProvider` is the interface consumed by `fetch_symbol_range`. The
current `LegacyMinuteDataProvider` adapts the existing fetcher implementation,
so future AKShare, EastMoney, Sina, or other providers can be added without
changing the download engine.

`ParquetStorage` owns the instrument/date path and atomic write. The legacy
`write_partition` function remains for backwards compatibility with direct
callers and tests.

## Remaining follow-ups

- persist listing/delisting dates for a point-in-time ETF universe
- split the concrete AKShare/EastMoney/Sina adapters out of `fetcher.py`
- add a Dashboard-side Parquet reader and ETF instrument type in the separate
  `wu-t0-trading-dashboard` repository
