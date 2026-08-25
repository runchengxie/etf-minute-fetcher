"""标的选择和下载层共用的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass

VALID_EXCHANGES = frozenset({"SH", "SZ"})


def infer_etf_exchange(symbol: str) -> str:
    """按当前沪深 ETF 代码规则推断 6 位代码所属交易所。

    规则与项目当前使用的 AKShare 和东方财富市场编号约定一致。统一放在这里可以避免
    CLI 和标的选择代码重复判断。以后上游能稳定提供交易所字段时，也只需要替换这一处。
    """

    code = symbol.strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"ETF 代码应为 6 位数字: {symbol!r}")
    return "SH" if code.startswith(("5", "6")) else "SZ"


@dataclass(frozen=True, slots=True)
class Instrument:
    """下载流程使用的标准化可交易标的。"""

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
            raise ValueError(f"当前只支持 ETF 标的: {self.asset_type!r}")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "asset_type", asset_type)
        object.__setattr__(self, "name", name)

    @property
    def ts_code(self) -> str:
        return f"{self.symbol}.{self.exchange}"
