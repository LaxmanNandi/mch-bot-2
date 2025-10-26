from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional
import pandas as pd


@dataclass
class UnderlyingBar:
    ts: pd.Timestamp
    close: float
    iv: Optional[float]


def iter_underlying_csv(path: Path, tz: str = "Asia/Kolkata") -> Iterator[UnderlyingBar]:
    df = pd.read_csv(path)
    if "timestamp" not in df.columns or "close" not in df.columns:
        raise ValueError("CSV must contain columns: timestamp, close, [iv]")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(tz)
    for _, row in df.iterrows():
        iv = float(row["iv"]) if "iv" in df.columns and pd.notna(row["iv"]) else None
        yield UnderlyingBar(ts=row["timestamp"], close=float(row["close"]), iv=iv)

