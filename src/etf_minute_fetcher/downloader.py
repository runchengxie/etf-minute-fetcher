"""Bounded, resumable batch download engine."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fetcher import fetch_symbol_range
from .models import Instrument
from .providers.base import MinuteDataProvider
from .providers.legacy import LegacyMinuteDataProvider
from .storage import ParquetStorage


@dataclass(frozen=True, slots=True)
class DownloadConfig:
    workers: int = 4
    requests_per_second: float = 2.0
    task_retries: int = 1
    skip_existing: bool = True
    checkpoint_path: Path | None = None

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers 必须 >= 1")
        if self.requests_per_second < 0:
            raise ValueError("requests_per_second 必须 >= 0")
        if self.task_retries < 0:
            raise ValueError("task_retries 必须 >= 0")


class _RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1.0 / requests_per_second if requests_per_second else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self.interval == 0:
            return
        with self._lock:
            now = time.monotonic()
            wait_for = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self.interval
        if wait_for:
            time.sleep(wait_for)


class _Checkpoint:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"version": 1, "symbols": {}}
        if path and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("symbols"), dict):
                    self._state = loaded
            except (OSError, json.JSONDecodeError):
                self._state = {"version": 1, "symbols": {}}

    def update(self, symbol: str, stats: dict[str, Any]) -> None:
        if self.path is None:
            return
        with self._lock:
            self._state.setdefault("symbols", {})[symbol] = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "stats": stats,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)


class DownloadEngine:
    def __init__(
        self,
        config: DownloadConfig | None = None,
        *,
        provider: MinuteDataProvider | None = None,
    ) -> None:
        self.config = config or DownloadConfig()
        self.provider = provider or LegacyMinuteDataProvider()

    def download(
        self,
        instruments: list[Instrument],
        trade_dates: list[str],
        *,
        period: str,
        output_dir: Path,
    ) -> dict[str, Any]:
        storage = ParquetStorage(output_dir)
        checkpoint = _Checkpoint(self.config.checkpoint_path)
        limiter = _RateLimiter(self.config.requests_per_second)

        def run_one(instrument: Instrument) -> tuple[str, dict[str, Any]]:
            last_stats: dict[str, Any] = {}
            for attempt in range(self.config.task_retries + 1):
                limiter.wait()
                try:
                    last_stats = fetch_symbol_range(
                        instrument.ts_code,
                        trade_dates,
                        period=period,
                        output_dir=storage.symbol_dir(instrument),
                        skip_existing=self.config.skip_existing,
                        storage=storage,
                        provider=self.provider,
                    )
                except Exception as exc:  # noqa: BLE001
                    message = f"{type(exc).__name__}: {exc}"
                    last_stats = {
                        "written": [],
                        "skipped": [],
                        "empty": [],
                        "errors": {trade_date: message for trade_date in trade_dates},
                    }
                if not last_stats["errors"] or attempt == self.config.task_retries:
                    break
            checkpoint.update(instrument.ts_code, last_stats)
            return instrument.ts_code, last_stats

        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            futures = [executor.submit(run_one, instrument) for instrument in instruments]
            for future in as_completed(futures):
                symbol, stats = future.result()
                results[symbol] = stats
        return {"results": results}
