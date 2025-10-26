from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
import numpy as np

from .kite_chain import Instrument, ltp_dict, nearest_by_strike, strikes_from_chain
from .iv import implied_vol_price
from ..data.bs import black_scholes_delta


@dataclass
class ChainPoint:
    instrument: Instrument
    ltp: float
    iv: Optional[float]
    delta: Optional[float]


def build_chain_points(
    kite,
    chain: List[Instrument],
    spot: float,
    t_years: float,
    r: float,
    max_strikes_away: int = 20,
) -> List[ChainPoint]:
    # Batch fetch LTPs
    symbols = [f"{i.exchange}:{i.tradingsymbol}" for i in chain]
    quotes = ltp_dict(kite, symbols)
    points: List[ChainPoint] = []
    for inst in chain:
        sym = f"{inst.exchange}:{inst.tradingsymbol}"
        ltp = quotes.get(sym)
        if ltp is None:
            continue
        iv = implied_vol_price(ltp, spot, float(inst.strike), t_years, r, "CALL" if inst.instrument_type == "CE" else "PUT")
        delta = None
        if iv is not None:
            delta = black_scholes_delta(spot, float(inst.strike), t_years, r, iv, "CALL" if inst.instrument_type == "CE" else "PUT")
        points.append(ChainPoint(instrument=inst, ltp=float(ltp), iv=iv, delta=delta))
    return points


def choose_by_target_delta(points: List[ChainPoint], target_delta: float) -> Tuple[Optional[ChainPoint], Optional[ChainPoint]]:
    # Return (PUT_short, CALL_short)
    ce = [p for p in points if p.instrument.instrument_type == "CE" and p.delta is not None]
    pe = [p for p in points if p.instrument.instrument_type == "PE" and p.delta is not None]
    if not ce or not pe:
        return None, None
    put_short = min(pe, key=lambda p: abs(abs(p.delta) - target_delta))
    call_short = min(ce, key=lambda p: abs(abs(p.delta) - target_delta))
    return put_short, call_short

