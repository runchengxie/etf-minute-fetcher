"""Shared instrument models and symbol normalization."""

from __future__ import annotations

from dataclasses import dataclass

_VALID_EXCHANGES = {"SH", "SZ"}


def infer_exchange(symbol: str) -> str:
    """Infer the exchange for a six-digit mainland ETF code."""
    if len(symbol) != 6 or not symbol.isdigit():
        raise ValueError(f"ETF 代码应为 6 位数字: {symbol!r}")
    return "SH" if symbol.startswith(("5", "6")) else "SZ"


@dataclass(frozen=True, slots=True)
class Instrument:
    """A normalized tradable instrument."""

    symbol: str
    exchange: str
    asset_type: str = "ETF"
    name: str | None = None
    list_date: str | None = None
    delist_date: str | None = None

    def __post_init__(self) -> None:
        if len(self.symbol) != 6 or not self.symbol.isdigit():
            raise ValueError(f"ETF 代码应为 6 位数字: {self.symbol!r}")
        exchange = self.exchange.upper()
        if exchange not in _VALID_EXCHANGES:
            raise ValueError(f"不支持的交易所后缀: {self.exchange!r}")
        object.__setattr__(self, "exchange", exchange)

    @property
    def ts_code(self) -> str:
        return f"{self.symbol}.{self.exchange}"

    @classmethod
    def from_ts_code(cls, value: str, **kwargs: object) -> "Instrument":
        raw = value.strip().upper()
        if not raw:
            raise ValueError("ETF 代码不能为空")
        if "." in raw:
            symbol, exchange = raw.rsplit(".", 1)
        else:
            symbol = raw
            exchange = infer_exchange(symbol)
        if exchange not in _VALID_EXCHANGES:
            raise ValueError(f"不支持的交易所后缀: {raw}")
        if len(symbol) != 6 or not symbol.isdigit():
            raise ValueError(f"ETF 代码应为 6 位数字: {value!r}")
        return cls(symbol=symbol, exchange=exchange, **kwargs)
