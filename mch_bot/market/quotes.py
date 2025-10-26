from __future__ import annotations

from typing import Dict, Iterable, Any


def quote_dict(kite, symbols: Iterable[str]) -> Dict[str, Any]:
    syms = list(symbols)
    if not syms:
        return {}
    # kite.quote returns rich dict including OI and volume if available
    data = kite.quote(syms)
    out: Dict[str, Any] = {}
    for k, v in data.items():
        out[k] = v
    return out

