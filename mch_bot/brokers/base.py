from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional


Side = Literal["BUY", "SELL"]
OptType = Literal["CALL", "PUT"]


@dataclass
class Order:
    symbol: str
    expiry: str  # YYYY-MM-DD
    strike: float
    option_type: OptType
    side: Side
    qty: int
    price: float  # limit price


@dataclass
class Fill:
    order: Order
    fill_price: float


class BrokerBase:
    name: str = "base"

    def place_orders(self, orders: List[Order]) -> List[Fill]:  # pragma: no cover - interface
        raise NotImplementedError

