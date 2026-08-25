"""Core instrument models shared by universe and download layers."""

from __future__ import annotations

from dataclasses import dataclass

VALID_EXCHANGES = frozenset({"SH", "SZ"})


def infer_etf_exchange(symbol: str) -> str:
    """Infer the exchange for a six-digit mainland ETF code.

    The rule matches the current AKShare/EastMoney ETF market-id convention used by
    this project. Keeping it here prevents CLI/universe code from duplicating it and
    gives us one place to replace when an upstream source exposes exchange metadata.
    """

    code = symbol.strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"ETF 代码应为 6 位数字: {symbol!r}")
    return "SH" if code.startswith(("5", "6")) else "SZ"


@dataclass(frozen=True, slots=True)
class Instrument:
    """A normalized tradable instrument used by the ingestion pipeline."""

    symbol: str
    exchange: str
    asset_type: str = "ETF"
    name: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip()
        exchange = self.exchange.strip().upper()
        asset_type = self.asset_type.strip().upper()
        name = self.name.strip() if isinstance(self.name, str) and self.name.strip() else None

        if len(symbol) != 6 or not symbol.isdigit():
            raise ValueError(f"ETF 代码应为 6 位数字: {self.symbol!r}")
        if exchange not in VALID_EXCHANGES:
            raise ValueError(f"不支持的交易所后缀: {exchange}")
        if asset_type != "ETF":
            raise ValueError(f"当前只支持 ETF instrument: {self.asset_type!r}")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "asset_type", asset_type)
        object.__setattr__(self, "name", name)

    @property
    def ts_code(self) -> str:
        return f"{self.symbol}.{self.exchange}"

    @classmethod
    def from_ts_code(cls, value: str, **kwargs: object) -> "Instrument":
        """Build an instrument from a bare or suffixed ETF code."""
        raw = value.strip().upper()
        if not raw:
            raise ValueError("ETF 代码不能为空")
        if "." in raw:
            symbol, exchange = raw.rsplit(".", 1)
        else:
            symbol = raw
            exchange = infer_etf_exchange(symbol)
        return cls(symbol=symbol, exchange=exchange, **kwargs)
