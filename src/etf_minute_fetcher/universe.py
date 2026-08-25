"""ETF universe discovery and symbol normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    """Resolve current or historical mainland ETF membership via AKShare.

    Current discovery uses EastMoney's ``fund_etf_spot_em``. Historical snapshots
    and fund-type filtering use the THS ETF snapshot endpoint because it accepts a
    query date and exposes ``基金类型``.
    """

    exchange: str | None = None
    name_contains: str | None = None
    fund_type: str | None = None
    as_of: str | None = None

    def __post_init__(self) -> None:
        if self.exchange is not None:
            normalized = self.exchange.strip().upper()
            if normalized not in VALID_EXCHANGES:
                raise ValueError(f"不支持的交易所后缀: {self.exchange}")
            object.__setattr__(self, "exchange", normalized)
        if self.name_contains is not None:
            value = self.name_contains.strip()
            object.__setattr__(self, "name_contains", value or None)
        if self.fund_type is not None:
            value = self.fund_type.strip()
            object.__setattr__(self, "fund_type", value or None)
        if self.as_of is not None:
            _validate_snapshot_date(self.as_of)

    def resolve(self) -> list[Instrument]:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover - package dependency in normal installs
            raise RuntimeError("未安装 akshare，无法获取 ETF universe") from exc

        try:
            if self.as_of is not None or self.fund_type is not None:
                raw = ak.fund_etf_spot_ths(date=self.as_of or "")
                code_column = "基金代码"
                name_column = "基金名称"
                type_column = "基金类型"
            else:
                raw = ak.fund_etf_spot_em()
                code_column = "代码"
                name_column = "名称"
                type_column = None
        except Exception as exc:  # noqa: BLE001
            scope = f"（as_of={self.as_of}）" if self.as_of else ""
            raise RuntimeError(f"获取 ETF universe{scope} 失败: {type(exc).__name__}: {exc}") from exc

        if raw is None or raw.empty:
            return []

        required = [code_column, name_column]
        if type_column is not None:
            required.append(type_column)
        missing = [column for column in required if column not in raw.columns]
        if missing:
            raise ValueError(f"AKShare ETF universe 缺少列: {missing}")

        instruments: list[Instrument] = []
        selected_columns = [code_column, name_column] + ([type_column] if type_column else [])
        for row in raw[selected_columns].itertuples(index=False, name=None):
            raw_code, raw_name = row[0], row[1]
            raw_fund_type = row[2] if type_column else None
            code = _coerce_code(raw_code)
            name = None if pd.isna(raw_name) else str(raw_name).strip() or None
            fund_type = None if raw_fund_type is None or pd.isna(raw_fund_type) else str(raw_fund_type).strip()
            try:
                instrument = instrument_from_symbol(code, name=name)
            except ValueError as exc:
                raise ValueError(f"AKShare ETF universe 包含非法代码: {raw_code!r}") from exc

            if self.exchange is not None and instrument.exchange != self.exchange:
                continue
            if self.name_contains is not None and self.name_contains.casefold() not in (name or "").casefold():
                continue
            if self.fund_type is not None and (fund_type or "").casefold() != self.fund_type.casefold():
                continue
            instruments.append(instrument)
        return _deduplicate(instruments)


def _validate_snapshot_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"universe as_of 应为 YYYYMMDD: {value!r}") from exc


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
