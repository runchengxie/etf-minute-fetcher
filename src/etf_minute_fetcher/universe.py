"""ETF universe discovery and symbol normalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import pandas as pd

from .models import Instrument, VALID_EXCHANGES, infer_etf_exchange


class UniverseProvider(Protocol):
    """Resolve a source of ETF instruments into normalized instruments."""

    def resolve(self) -> list[Instrument]: ...


def normalize_ts_code(symbol: str) -> str:
    """Normalize bare or suffixed ETF code to ``NNNNNN.SH/SZ``."""

    raw = symbol.strip().upper()
    if not raw:
        raise ValueError("ETF 代码不能为空")

    if "." in raw:
        code, exchange = raw.rsplit(".", 1)
        if exchange not in VALID_EXCHANGES:
            raise ValueError(f"不支持的交易所后缀: {raw}")
    else:
        code = raw
        exchange = infer_etf_exchange(code)

    return Instrument(symbol=code, exchange=exchange).ts_code


def instrument_from_symbol(symbol: str, *, name: str | None = None) -> Instrument:
    ts_code = normalize_ts_code(symbol)
    code, exchange = ts_code.rsplit(".", 1)
    return Instrument(symbol=code, exchange=exchange, name=name)


@dataclass(frozen=True, slots=True)
class ExplicitUniverse:
    symbols: Sequence[str]

    def resolve(self) -> list[Instrument]:
        return _deduplicate(instrument_from_symbol(symbol) for symbol in self.symbols)


@dataclass(frozen=True, slots=True)
class FileUniverse:
    path: Path

    def resolve(self) -> list[Instrument]:
        if not self.path.exists():
            raise FileNotFoundError(f"symbols file 不存在: {self.path}")
        symbols = [
            line.strip()
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return ExplicitUniverse(symbols).resolve()


@dataclass(frozen=True, slots=True)
class AkshareETFUniverse:
    """Current mainland ETF universe returned by AKShare/EastMoney."""

    exchange: str | None = None

    def __post_init__(self) -> None:
        if self.exchange is not None:
            normalized = self.exchange.strip().upper()
            if normalized not in VALID_EXCHANGES:
                raise ValueError(f"不支持的交易所后缀: {self.exchange}")
            object.__setattr__(self, "exchange", normalized)

    def resolve(self) -> list[Instrument]:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover - package dependency in normal installs
            raise RuntimeError("未安装 akshare，无法获取 ETF universe") from exc

        try:
            raw = ak.fund_etf_spot_em()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"获取当前 ETF universe 失败: {type(exc).__name__}: {exc}") from exc

        if raw is None or raw.empty:
            return []
        missing = [column for column in ("代码", "名称") if column not in raw.columns]
        if missing:
            raise ValueError(f"AKShare ETF universe 缺少列: {missing}")

        instruments: list[Instrument] = []
        for raw_code, raw_name in raw[["代码", "名称"]].itertuples(index=False, name=None):
            code = _coerce_code(raw_code)
            name = None if pd.isna(raw_name) else str(raw_name).strip() or None
            try:
                instrument = instrument_from_symbol(code, name=name)
            except ValueError as exc:
                raise ValueError(f"AKShare ETF universe 包含非法代码: {raw_code!r}") from exc
            if self.exchange is None or instrument.exchange == self.exchange:
                instruments.append(instrument)
        return _deduplicate(instruments)


def _coerce_code(value: object) -> str:
    if pd.isna(value):
        raise ValueError("ETF 代码不能为空")
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):06d}"
    if isinstance(value, int):
        return f"{value:06d}"
    return str(value).strip()


def _deduplicate(instruments) -> list[Instrument]:
    result: list[Instrument] = []
    seen: set[str] = set()
    for instrument in instruments:
        if instrument.ts_code not in seen:
            result.append(instrument)
            seen.add(instrument.ts_code)
    return result
