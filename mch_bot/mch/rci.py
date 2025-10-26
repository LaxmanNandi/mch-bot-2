from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RCIInputs:
    vix: Optional[float]
    vix_bounds: tuple[float, float]
    adx: Optional[float]
    trend_neutrality_max_adx: float
    stability_score: float  # 0..1, based on recent regime stability


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def rci_score(inp: RCIInputs) -> float:
    parts: list[float] = []

    # VIX regime: preferred inside bounds
    if inp.vix is not None:
        lo, hi = inp.vix_bounds
        if lo <= inp.vix <= hi:
            parts.append(1.0)
        else:
            # softly penalize proportional to distance from bounds
            dist = min(abs(inp.vix - lo), abs(inp.vix - hi))
            parts.append(1.0 / (1.0 + dist / 5.0))
    # Trend neutrality via ADX (lower is better for condors)
    if inp.adx is not None:
        if inp.adx <= inp.trend_neutrality_max_adx:
            parts.append(1.0)
        else:
            parts.append(clamp(1.0 - (inp.adx - inp.trend_neutrality_max_adx) / 30.0, 0.0, 1.0))

    # Stability over recent bars
    parts.append(clamp(inp.stability_score, 0.0, 1.0))

    if not parts:
        return 0.5
    return sum(parts) / len(parts)

