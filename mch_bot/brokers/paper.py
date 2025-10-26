from __future__ import annotations

from typing import List
from .base import BrokerBase, Order, Fill


class PaperBroker(BrokerBase):
    name = "paper"

    def __init__(self, slippage_bps: float = 2.0, commission_per_lot: float = 40.0) -> None:
        self.slippage_bps = slippage_bps
        self.commission_per_lot = commission_per_lot

    def place_orders(self, orders: List[Order]) -> List[Fill]:
        fills: List[Fill] = []
        for o in orders:
            slip = o.price * (self.slippage_bps / 10000.0)
            exec_price = o.price + slip if o.side == "BUY" else o.price - slip
            fills.append(Fill(order=o, fill_price=exec_price))
        return fills

