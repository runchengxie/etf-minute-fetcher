# Architecture

## Pipeline

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

The current `DownloadEngine` keeps the existing single-symbol execution boundary
and injects a provider and storage implementation into `fetch_symbol_range`.
This preserves the public fetcher API while allowing batch tasks to replace the
data source or sink independently.

## Provider boundary

`MinuteDataProvider.fetch()` receives an `Instrument`, a date range, a period,
and an optional source selection. It must return the project's normalized minute
bar schema.

`LegacyMinuteProvider` is the compatibility adapter for the current
AKShare/EastMoney/Sina implementation. The concrete network code remains in
`fetcher.py` for now; extracting those adapters is intentionally a follow-up so
this change does not alter fallback behavior.

## Storage boundary

`BarStorage` owns partition existence checks and writes. `ParquetStorage` writes
to:

```text
<root>/<ts_code>/trade_date=YYYYMMDD/part.parquet
```

It writes a unique temporary file and atomically replaces the final Parquet
file. The legacy `write_partition()` function remains available to callers that
use the single-symbol API directly.

## Remaining follow-ups

- split AKShare, EastMoney, and Sina network adapters into separate provider
  modules
- add HTTP-request-level rate limiting inside providers
- add a lifecycle metadata source for exact ETF listing and delisting dates
