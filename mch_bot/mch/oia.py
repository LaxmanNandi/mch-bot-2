from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass
class OIAProfile:
    allowed_symbols: set[str]
    max_positions: int
    trading_hours: tuple[str, str]  # "HH:MM", "HH:MM" local time


def within_time_window(now_hhmm: str, window: tuple[str, str]) -> bool:
    start, end = window
    return start <= now_hhmm <= end


def oia_permit(
    symbol: str,
    current_positions: int,
    profile: OIAProfile,
    now_hhmm: str,
) -> bool:
    if symbol not in profile.allowed_symbols:
        return False
    if current_positions >= profile.max_positions:
        return False
    if not within_time_window(now_hhmm, profile.trading_hours):
        return False
    return True

