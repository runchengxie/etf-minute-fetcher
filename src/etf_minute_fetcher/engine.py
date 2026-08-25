"""Bounded batch download engine with resume and persistent task state."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .fetcher import fetch_symbol_range

FetchSymbol = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class DownloadConfig:
    workers: int = 4
    rate_limit_per_second: float = 2.0
    symbol_attempts: int = 2
    retry_delay: float = 2.0
    resume: bool = True

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers 必须 >= 1")
        if self.rate_limit_per_second < 0:
            raise ValueError("rate_limit_per_second 必须 >= 0")
        if self.symbol_attempts < 1:
            raise ValueError("symbol_attempts 必须 >= 1")
        if self.retry_delay < 0:
            raise ValueError("retry_delay 必须 >= 0")


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    total_symbols: int
    completed_symbols: int
    failed_symbols: int
    resumed_symbols: int
    written_partitions: int
    skipped_partitions: int
    empty_partitions: int
    failures: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _RateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        self._interval = 0.0 if rate_per_second <= 0 else 1.0 / rate_per_second
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            if delay:
                time.sleep(delay)
                now = time.monotonic()
            self._next_allowed = max(now, self._next_allowed) + self._interval


class DownloadEngine:
    """Run ETF downloads with bounded concurrency and durable checkpoints.

    The rate limit is applied to symbol-attempt starts. A single symbol fetch can still
    perform its own internal AKShare/EastMoney/Sina retries, so this is intentionally a
    coarse-grained guard rather than an HTTP request interceptor.
    """

    def __init__(
        self,
        config: DownloadConfig | None = None,
        *,
        fetch_symbol: FetchSymbol = fetch_symbol_range,
    ) -> None:
        self.config = config or DownloadConfig()
        self._fetch_symbol = fetch_symbol
        self._rate_limiter = _RateLimiter(self.config.rate_limit_per_second)

    def run(
        self,
        symbols: list[str],
        trade_dates: list[str],
        *,
        period: str,
        output_dir: Path,
        skip_existing: bool = True,
        checkpoint_path: Path | None = None,
        stats_path: Path | None = None,
    ) -> DownloadSummary:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_path or output_dir / ".download-checkpoint.json"
        stats_path = stats_path or output_dir / ".download-summary.json"
        fingerprint = {
            "period": period,
            "trade_dates": trade_dates,
            "output_dir": str(output_dir.resolve()),
        }
        checkpoint = self._load_checkpoint(checkpoint_path, fingerprint)
        states: dict[str, dict[str, Any]] = checkpoint.setdefault("symbols", {})

        resumed = 0
        pending: list[str] = []
        for symbol in symbols:
            state = states.get(symbol)
            if self.config.resume and state and state.get("status") == "success":
                resumed += 1
                continue
            pending.append(symbol)

        for attempt in range(1, self.config.symbol_attempts + 1):
            if not pending:
                break
            retry_queue: list[str] = []
            with ThreadPoolExecutor(max_workers=self.config.workers, thread_name_prefix="etf-min") as pool:
                futures = {
                    pool.submit(
                        self._run_symbol,
                        symbol,
                        trade_dates,
                        period=period,
                        output_dir=output_dir / symbol,
                        skip_existing=skip_existing,
                    ): symbol
                    for symbol in pending
                }
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        stats = future.result()
                    except Exception as exc:  # noqa: BLE001
                        stats = {
                            "written": [],
                            "skipped": [],
                            "empty": [],
                            "errors": {"engine": f"{type(exc).__name__}: {exc}"},
                        }
                    errors = stats.get("errors") or {}
                    if errors:
                        message = "; ".join(f"{key}: {value}" for key, value in sorted(errors.items()))
                        states[symbol] = {
                            "status": "failed",
                            "attempts": attempt,
                            "last_error": message,
                            "stats": _serializable_stats(stats),
                        }
                        if attempt < self.config.symbol_attempts:
                            retry_queue.append(symbol)
                    else:
                        states[symbol] = {
                            "status": "success",
                            "attempts": attempt,
                            "stats": _serializable_stats(stats),
                        }
                    self._write_checkpoint(checkpoint_path, checkpoint)

            pending = retry_queue
            if pending and attempt < self.config.symbol_attempts and self.config.retry_delay:
                time.sleep(self.config.retry_delay * attempt)

        summary = self._summarize(symbols, states, resumed)
        _atomic_write_json(stats_path, summary.to_dict())
        return summary

    def _run_symbol(
        self,
        symbol: str,
        trade_dates: list[str],
        *,
        period: str,
        output_dir: Path,
        skip_existing: bool,
    ) -> dict[str, Any]:
        self._rate_limiter.acquire()
        return self._fetch_symbol(
            symbol,
            trade_dates,
            period=period,
            output_dir=output_dir,
            skip_existing=skip_existing,
        )

    def _load_checkpoint(self, path: Path, fingerprint: dict[str, Any]) -> dict[str, Any]:
        if not self.config.resume or not path.exists():
            return {"version": 1, "fingerprint": fingerprint, "symbols": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取 checkpoint {path}: {exc}") from exc
        if payload.get("version") != 1:
            raise ValueError(f"不支持的 checkpoint 版本: {payload.get('version')!r}")
        if payload.get("fingerprint") != fingerprint:
            raise ValueError("checkpoint 与本次 period/trade_dates/output_dir 不匹配；请换 checkpoint 或使用 --no-resume")
        if not isinstance(payload.get("symbols"), dict):
            raise ValueError("checkpoint symbols 字段无效")
        return payload

    @staticmethod
    def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
        _atomic_write_json(path, payload)

    @staticmethod
    def _summarize(symbols: list[str], states: dict[str, dict[str, Any]], resumed: int) -> DownloadSummary:
        written = skipped = empty = completed = 0
        failures: dict[str, str] = {}
        for symbol in symbols:
            state = states.get(symbol) or {}
            stats = state.get("stats") or {}
            written += len(stats.get("written") or [])
            skipped += len(stats.get("skipped") or [])
            empty += len(stats.get("empty") or [])
            if state.get("status") == "success":
                completed += 1
            else:
                failures[symbol] = state.get("last_error") or "未完成"
        return DownloadSummary(
            total_symbols=len(symbols),
            completed_symbols=completed,
            failed_symbols=len(failures),
            resumed_symbols=resumed,
            written_partitions=written,
            skipped_partitions=skipped,
            empty_partitions=empty,
            failures=failures,
        )


def _serializable_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "written": list(stats.get("written") or []),
        "skipped": list(stats.get("skipped") or []),
        "empty": list(stats.get("empty") or []),
        "errors": dict(stats.get("errors") or {}),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
