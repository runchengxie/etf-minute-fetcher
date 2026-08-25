"""ETF 标的集合发现和代码标准化。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from .models import VALID_EXCHANGES, Instrument, infer_etf_exchange


class UniverseProvider(Protocol):
    """把一种 ETF 标的来源转换为标准化标的列表。"""

    def resolve(self) -> list[Instrument]: ...


def normalize_ts_code(symbol: str) -> str:
    """把裸代码或带后缀代码统一为 ``NNNNNN.SH/SZ``。"""

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
            raise FileNotFoundError(f"ETF 代码文件不存在: {self.path}")
        symbols = [
            line.strip()
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return ExplicitUniverse(symbols).resolve()


@dataclass(frozen=True, slots=True)
class AkshareETFUniverse:
    """通过 AKShare 获取当前或历史沪深 ETF 集合。

    当前集合使用东方财富 ``fund_etf_spot_em``。指定历史日期或基金类型时使用
    同花顺 ETF 快照接口，因为该接口支持查询日期并提供 ``基金类型``。
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
        raw, code_column, name_column, type_column = self._load_frame()
        if raw is None or raw.empty:
            return []

        selected_columns = self._validate_columns(raw, code_column, name_column, type_column)
        instruments = [
            instrument
            for row in raw[selected_columns].itertuples(index=False, name=None)
            if (instrument := self._instrument_from_row(row, type_column)) is not None
        ]
        return _deduplicate(instruments)

    def _load_frame(self) -> tuple[pd.DataFrame | None, str, str, str | None]:
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover - 正常安装会包含该依赖
            raise RuntimeError("未安装 akshare，无法获取 ETF 集合") from exc

        try:
            if self.as_of is not None or self.fund_type is not None:
                return (
                    ak.fund_etf_spot_ths(date=self.as_of or ""),
                    "基金代码",
                    "基金名称",
                    "基金类型",
                )
            return ak.fund_etf_spot_em(), "代码", "名称", None
        except Exception as exc:
            # AKShare 可能抛出网络、解析或上游接口异常，这里统一补充查询范围信息。
            scope = f"（as_of={self.as_of}）" if self.as_of else ""
            raise RuntimeError(f"获取 ETF 集合{scope} 失败: {type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _validate_columns(
        raw: pd.DataFrame,
        code_column: str,
        name_column: str,
        type_column: str | None,
    ) -> list[str]:
        selected_columns = [code_column, name_column] + ([type_column] if type_column else [])
        missing = [column for column in selected_columns if column not in raw.columns]
        if missing:
            raise ValueError(f"AKShare ETF 集合缺少列: {missing}")
        return selected_columns

    def _instrument_from_row(
        self,
        row: tuple[object, ...],
        type_column: str | None,
    ) -> Instrument | None:
        raw_code, raw_name = row[0], row[1]
        raw_fund_type = row[2] if type_column else None
        code = _coerce_code(raw_code)
        name = None if pd.isna(raw_name) else str(raw_name).strip() or None
        fund_type = (
            None if raw_fund_type is None or pd.isna(raw_fund_type) else str(raw_fund_type).strip()
        )
        try:
            instrument = instrument_from_symbol(code, name=name)
        except ValueError as exc:
            raise ValueError(f"AKShare ETF 集合包含非法代码: {raw_code!r}") from exc
        return instrument if self._matches_filters(instrument, name, fund_type) else None

    def _matches_filters(
        self,
        instrument: Instrument,
        name: str | None,
        fund_type: str | None,
    ) -> bool:
        if self.exchange is not None and instrument.exchange != self.exchange:
            return False
        if (
            self.name_contains is not None
            and self.name_contains.casefold() not in (name or "").casefold()
        ):
            return False
        return self.fund_type is None or (fund_type or "").casefold() == self.fund_type.casefold()


def _validate_snapshot_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"--as-of 应为 YYYYMMDD: {value!r}") from exc


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
