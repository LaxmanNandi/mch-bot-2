from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from kiteconnect import KiteConnect

from .base import BrokerBase, Order, Fill


SECRETS_DIR = Path('.secrets')
SECRETS_DIR.mkdir(exist_ok=True)
SECRETS_FILE = SECRETS_DIR / 'kite.json'


def _load_secrets_file() -> dict:
    if SECRETS_FILE.exists():
        try:
            return json.loads(SECRETS_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _save_secrets_file(obj: dict) -> None:
    SECRETS_DIR.mkdir(exist_ok=True)
    SECRETS_FILE.write_text(json.dumps(obj, indent=2), encoding='utf-8')


class KiteBroker(BrokerBase):
    name = "kite"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        secrets = _load_secrets_file()
        self.api_key = api_key or os.getenv("KITE_API_KEY") or secrets.get("api_key")
        self.api_secret = api_secret or os.getenv("KITE_API_SECRET") or secrets.get("api_secret")
        self.access_token = access_token or os.getenv("KITE_ACCESS_TOKEN") or secrets.get("access_token")

        if not self.api_key:
            raise RuntimeError("KiteBroker: missing api_key. Set env KITE_API_KEY or use kite-auth CLI.")

        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)

    def set_access_token(self, access_token: str) -> None:
        self.access_token = access_token
        self.kite.set_access_token(access_token)
        secrets = _load_secrets_file()
        secrets.update({"api_key": self.api_key, "access_token": access_token})
        if self.api_secret:
            secrets["api_secret"] = self.api_secret
        _save_secrets_file(secrets)

    def exchange_request_token(self, request_token: str) -> str:
        if not self.api_secret:
            raise RuntimeError("KiteBroker: missing api_secret to exchange request_token.")
        resp = self.kite.generate_session(request_token, api_secret=self.api_secret)
        access_token = resp["access_token"]
        self.set_access_token(access_token)
        return access_token

    def place_orders(self, orders: List[Order]) -> List[Fill]:
        if not self.access_token:
            raise RuntimeError("KiteBroker: no access_token set. Run kite-auth or set KITE_ACCESS_TOKEN.")

        fills: List[Fill] = []
        for o in orders:
            # Expect symbol as full Zerodha tradingsymbol (e.g., NFO:NIFTY25OCT23500CE)
            if ":" in o.symbol:
                exchange, tradingsymbol = o.symbol.split(":", 1)
            else:
                # Default to NFO if not provided
                exchange, tradingsymbol = "NFO", o.symbol

            variety = self.kite.VARIETY_REGULAR
            order_type = self.kite.ORDER_TYPE_LIMIT
            product = self.kite.PRODUCT_NRML
            transaction_type = self.kite.TRANSACTION_TYPE_BUY if o.side == "BUY" else self.kite.TRANSACTION_TYPE_SELL

            placed = self.kite.place_order(
                variety=variety,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=o.qty,
                product=product,
                order_type=order_type,
                price=round(float(o.price), 2),
                validity=self.kite.VALIDITY_DAY,
            )
            # Zerodha returns order_id; we don’t get a fill price immediately for LIMIT orders
            fills.append(Fill(order=o, fill_price=o.price))
        return fills

