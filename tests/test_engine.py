from __future__ import annotations

import json
from pathlib import Path

import pytest

from etf_minute_fetcher.engine import DownloadConfig, DownloadEngine


def _ok(*, written=None, skipped=None, empty=None):
    return {
        "written": list(written or []),
        "skipped": list(skipped or []),
        "empty": list(empty or []),
        "errors": {},
    }


def test_download_engine_retries_failed_symbols_in_next_pass(tmp_path: Path):
    calls: dict[str, int] = {}

    def fake_fetch(symbol, trade_dates, *, period, output_dir, skip_existing):
        calls[symbol] = calls.get(symbol, 0) + 1
        if symbol == "512880.SH" and calls[symbol] == 1:
            return {"written": [], "skipped": [], "empty": [], "errors": {"20260824": "temporary"}}
        return _ok(written=["20260824"])

    engine = DownloadEngine(
        DownloadConfig(workers=2, rate_limit_per_second=0, symbol_attempts=2, retry_delay=0),
        fetch_symbol=fake_fetch,
    )
    summary = engine.run(
        ["512880.SH", "159993.SZ"],
        ["20260824"],
        period="1",
        output_dir=tmp_path,
    )

    assert calls == {"512880.SH": 2, "159993.SZ": 1}
    assert summary.completed_symbols == 2
    assert summary.failed_symbols == 0
    assert summary.written_partitions == 2


def test_download_engine_persists_checkpoint_and_resumes(tmp_path: Path):
    calls: list[str] = []

    def fake_fetch(symbol, trade_dates, *, period, output_dir, skip_existing):
        calls.append(symbol)
        return _ok(skipped=["20260824"])

    config = DownloadConfig(workers=1, rate_limit_per_second=0, symbol_attempts=1, retry_delay=0)
    engine = DownloadEngine(config, fetch_symbol=fake_fetch)
    first = engine.run(["512880.SH"], ["20260824"], period="1", output_dir=tmp_path)

    assert first.resumed_symbols == 0
    assert calls == ["512880.SH"]
    checkpoint = json.loads((tmp_path / ".download-checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["symbols"]["512880.SH"]["status"] == "success"

    def must_not_run(*args, **kwargs):
        raise AssertionError("resume should not schedule completed symbol")

    second = DownloadEngine(config, fetch_symbol=must_not_run).run(
        ["512880.SH"],
        ["20260824"],
        period="1",
        output_dir=tmp_path,
    )

    assert second.resumed_symbols == 1
    assert second.completed_symbols == 1
    assert second.skipped_partitions == 1


def test_download_engine_persists_final_failures(tmp_path: Path):
    def fake_fetch(symbol, trade_dates, *, period, output_dir, skip_existing):
        return {"written": [], "skipped": [], "empty": [], "errors": {"20260824": "down"}}

    engine = DownloadEngine(
        DownloadConfig(workers=1, rate_limit_per_second=0, symbol_attempts=2, retry_delay=0),
        fetch_symbol=fake_fetch,
    )
    summary = engine.run(["512880.SH"], ["20260824"], period="1", output_dir=tmp_path)

    assert summary.failed_symbols == 1
    assert "512880.SH" in summary.failures
    persisted = json.loads((tmp_path / ".download-summary.json").read_text(encoding="utf-8"))
    assert persisted["failed_symbols"] == 1


def test_download_engine_rejects_mismatched_checkpoint(tmp_path: Path):
    config = DownloadConfig(workers=1, rate_limit_per_second=0, symbol_attempts=1, retry_delay=0)
    DownloadEngine(config, fetch_symbol=lambda *args, **kwargs: _ok(empty=["20260824"])).run(
        ["512880.SH"],
        ["20260824"],
        period="1",
        output_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="checkpoint"):
        DownloadEngine(config, fetch_symbol=lambda *args, **kwargs: _ok()).run(
            ["512880.SH"],
            ["20260823"],
            period="1",
            output_dir=tmp_path,
        )


def test_download_engine_rejects_checkpoint_when_skip_policy_changes(tmp_path: Path):
    config = DownloadConfig(
        workers=1,
        rate_limit_per_second=0,
        symbol_attempts=1,
        retry_delay=0,
    )
    engine = DownloadEngine(config, fetch_symbol=lambda *args, **kwargs: _ok(written=["20260824"]))
    engine.run(
        ["512880.SH"],
        ["20260824"],
        period="1",
        output_dir=tmp_path,
        skip_existing=True,
    )

    with pytest.raises(ValueError, match="覆盖策略"):
        engine.run(
            ["512880.SH"],
            ["20260824"],
            period="1",
            output_dir=tmp_path,
            skip_existing=False,
        )


def test_download_engine_accepts_legacy_checkpoint_with_default_skip_policy(tmp_path: Path):
    config = DownloadConfig(
        workers=1,
        rate_limit_per_second=0,
        symbol_attempts=1,
        retry_delay=0,
    )
    engine = DownloadEngine(config, fetch_symbol=lambda *args, **kwargs: _ok(written=["20260824"]))
    engine.run(["512880.SH"], ["20260824"], period="1", output_dir=tmp_path)

    checkpoint_path = tmp_path / ".download-checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["fingerprint"].pop("skip_existing")
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    resumed = DownloadEngine(
        config,
        fetch_symbol=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy checkpoint should resume")
        ),
    ).run(["512880.SH"], ["20260824"], period="1", output_dir=tmp_path)

    assert resumed.resumed_symbols == 1


def test_download_engine_converts_unexpected_task_exception_to_failure(tmp_path: Path):
    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    summary = DownloadEngine(
        DownloadConfig(
            workers=1,
            rate_limit_per_second=0,
            symbol_attempts=1,
            retry_delay=0,
        ),
        fetch_symbol=fail,
    ).run(["512880.SH"], ["20260824"], period="1", output_dir=tmp_path)

    assert summary.failed_symbols == 1
    assert "RuntimeError: boom" in summary.failures["512880.SH"]


def test_download_config_validates_bounds():
    with pytest.raises(ValueError, match="workers"):
        DownloadConfig(workers=0)
    with pytest.raises(ValueError, match="rate_limit"):
        DownloadConfig(rate_limit_per_second=-1)
    with pytest.raises(ValueError, match="symbol_attempts"):
        DownloadConfig(symbol_attempts=0)
    with pytest.raises(ValueError, match="retry_delay"):
        DownloadConfig(retry_delay=-1)
