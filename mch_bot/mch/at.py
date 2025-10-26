from __future__ import annotations


def authenticated_to_trade(rci_value: float, threshold: float) -> bool:
    return rci_value >= threshold

