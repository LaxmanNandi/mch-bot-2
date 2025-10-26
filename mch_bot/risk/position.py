from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSizing:
    account_equity: float
    max_risk_pct: float  # e.g., 2.0

    def max_risk_amount(self) -> float:
        return self.account_equity * (self.max_risk_pct / 100.0)

