"""标准化 ETF 分钟行情的数据存储接口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


class BarStorage(Protocol):
    def exists(self, output_dir: Path, trade_date: str) -> bool: ...

    def write(self, df: pd.DataFrame, output_dir: Path, trade_date: str) -> Path | None: ...


@dataclass(frozen=True, slots=True)
class ParquetBarStorage:
    """按交易日使用 Hive 风格目录分区的 Parquet 存储。"""

    filename: str = "part.parquet"

    def partition_path(self, output_dir: Path, trade_date: str) -> Path:
        return Path(output_dir) / f"trade_date={trade_date}" / self.filename

    def exists(self, output_dir: Path, trade_date: str) -> bool:
        return self.partition_path(output_dir, trade_date).exists()

    def write(self, df: pd.DataFrame, output_dir: Path, trade_date: str) -> Path | None:
        if df is None or df.empty:
            return None
        out_path = self.partition_path(output_dir, trade_date)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_name(f".{out_path.name}.tmp")
        try:
            df.to_parquet(tmp_path, index=False, engine="pyarrow")
            tmp_path.replace(out_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return out_path
