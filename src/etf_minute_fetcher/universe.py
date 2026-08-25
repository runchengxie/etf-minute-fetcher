"""ETF universe providers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol

import pandas as pd

from .models import Instrument, infer_exchange


class UniverseProvider(Protocol):
    def get_instruments(self) -> list[Instrument]:
        """Return the instruments in this universe."""


class ExplicitUniverse:
    def __init__(self, symbols: Iterable[str]) -> None:
        self.symbols = list(symbols)

    def get_instruments(self) -> list[Instrument]:
        return _deduplicate(Instrument.from_ts_code(symbol) for symbol in self.symbols)


class FileUniverse(ExplicitUniverse):
    def __init__(self, path: Path) -> None:
        self.path = path

    def get_instruments(self) -> list[Instrument]:
        if not self.path.exists():
            raise FileNotFoundError(f"symbols file 不存在: {self.path}")
        symbols = [
            line.strip()
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return ExplicitUniverse(symbols).get_instruments()


class AkshareETFUniverse:
    """Current listed ETF universe from ``fund_etf_spot_em``."""

    def __init__(self, *, exchange: str | None = None, name_contains: str | None = None) -> None:
        self.exchange = exchange.upper() if exchange else None
        self.name_contains = name_contains.casefold() if name_contains else None
        if self.exchange is not None and self.exchange not in {"SH", "SZ"}:
            raise ValueError(f"不支持的交易所筛选: {exchange!r}")

    def get_instruments(self) -> list[Instrument]:
        import akshare as ak

        frame = ak.fund_etf_spot_em()
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("fund_etf_spot_em 返回值不是 DataFrame")
        if frame.empty:
            return []

        code_column = _find_column(frame, ("代码", "基金代码", "证券代码", "symbol", "ts_code"))
        if code_column is None:
            raise ValueError("fund_etf_spot_em 返回值缺少 ETF 代码列")
        name_column = _find_column(frame, ("名称", "基金简称", "name"))
        exchange_column = _find_column(frame, ("市场", "交易所", "exchange"))

        instruments: list[Instrument] = []
        for _, row in frame.iterrows():
            symbol = _coerce_symbol(row[code_column])
            if symbol is None:
                continue
            exchange = _coerce_exchange(row[exchange_column]) if exchange_column else None
            exchange = exchange or infer_exchange(symbol)
            name = _coerce_text(row[name_column]) if name_column else None
            if self.exchange and exchange != self.exchange:
                continue
            if self.name_contains and self.name_contains not in (name or "").casefold():
                continue
            instruments.append(Instrument(symbol=symbol, exchange=exchange, name=name))

        return _deduplicate(instruments)


def _find_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)


def _coerce_symbol(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().upper()
    if "." in text:
        return Instrument.from_ts_code(text).symbol
    if text.isdigit() and len(text) < 6:
        text = text.zfill(6)
    if len(text) != 6 or not text.isdigit():
        return None
    return text


def _coerce_exchange(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().upper()
    if "SH" in text or "沪" in text:
        return "SH"
    if "SZ" in text or "深" in text:
        return "SZ"
    return None


def _coerce_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    return str(value).strip() or None


def _deduplicate(instruments: Iterable[Instrument]) -> list[Instrument]:
    result: list[Instrument] = []
    seen: set[str] = set()
    for instrument in instruments:
        if instrument.ts_code not in seen:
            result.append(instrument)
            seen.add(instrument.ts_code)
    return result
