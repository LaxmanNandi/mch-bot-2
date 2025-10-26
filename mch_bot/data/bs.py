from __future__ import annotations

import math


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    option_type: str,
) -> float:
    if t <= 0 or sigma <= 0:
        intrinsic = max(0.0, s - k) if option_type == "CALL" else max(0.0, k - s)
        return intrinsic
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if option_type == "CALL":
        return s * _phi(d1) - k * math.exp(-r * t) * _phi(d2)
    else:
        return k * math.exp(-r * t) * _phi(-d2) - s * _phi(-d1)


def black_scholes_delta(
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    option_type: str,
) -> float:
    if t <= 0 or sigma <= 0:
        if option_type == "CALL":
            return 1.0 if s > k else 0.0
        else:
            return -1.0 if s < k else 0.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    if option_type == "CALL":
        return _phi(d1)
    else:
        return _phi(d1) - 1.0
