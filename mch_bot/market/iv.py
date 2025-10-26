from __future__ import annotations

import math
from ..data.bs import black_scholes


def implied_vol_price(
    price: float,
    s: float,
    k: float,
    t: float,
    r: float,
    option_type: str,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-4,
    max_iter: int = 100,
) -> float | None:
    """Bisection implied volatility from option price. Returns None if not bracketing."""
    # Ensure the target is bracketed
    plo = black_scholes(s, k, t, r, lo, option_type)
    phi = black_scholes(s, k, t, r, hi, option_type)
    if not (min(plo, phi) <= price <= max(plo, phi)):
        return None
    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        pm = black_scholes(s, k, t, r, mid, option_type)
        if abs(pm - price) < tol:
            return mid
        # Decide which side to keep
        if (plo - price) * (pm - price) <= 0:
            b = mid
            phi = pm
        else:
            a = mid
            plo = pm
    return 0.5 * (a + b)
