"""Storage interfaces for normalized minute bars."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Protocol

import pandas as pd

from .models import Instrument


class BarStorage(Protocol):
    def symbol_dir(self, instrument: Instrument) -> Path:
        ...

    def exists(self, instrument: Instrument, trade_date: str) -> bool:
        ...

    def write(self, instrument: Instrument, trade_date: str, frame: pd.DataFrame) -> Path | None:
        ...


class ParquetStorage:
    """Write one atomic Parquet file per instrument and trade date."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def symbol_dir(self, instrument: Instrument) -> Path:
        return self.root / instrument.ts_code

    def partition_path(self, instrument: Instrument, trade_date: str) -> Path:
        return self.symbol_dir(instrument) / f"trade_date={trade_date}" / "part.parquet"

    def exists(self, instrument: Instrument, trade_date: str) -> bool:
        return self.partition_path(instrument, trade_date).exists()

    def write(self, instrument: Instrument, trade_date: str, frame: pd.DataFrame) -> Path | None:
        if frame is None or frame.empty:
            return None
        part_dir = self.partition_path(instrument, trade_date).parent
        part_dir.mkdir(parents=True, exist_ok=True)
        out_path = part_dir / "part.parquet"
        tmp_path = part_dir / f".part.parquet.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            frame.to_parquet(tmp_path, index=False, engine="pyarrow")
            tmp_path.replace(out_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return out_path
