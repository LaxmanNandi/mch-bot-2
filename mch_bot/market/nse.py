from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


NSE_BASE = "https://www.nseindia.com"
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HDRS)
    # Warm up cookies (NSE requires initial GET to set cookies)
    try:
        s.get(NSE_BASE, timeout=5)
    except Exception:
        pass
    return s


@dataclass
class NSESpot:
    symbol: str
    spot: float
    ts: datetime


def fetch_spot_index(symbol: str = "NIFTY 50") -> Optional[NSESpot]:
    s = _session()
    try:
        url = f"{NSE_BASE}/api/quote-equity?symbol={requests.utils.quote(symbol)}"
        # For indices, use quote-index
        if "NIFTY" in symbol.upper():
            url = f"{NSE_BASE}/api/quote-index?index={requests.utils.quote(symbol)}"
        r = s.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        # For index, "data" -> [ { last, ... } ]
        if "data" in data and isinstance(data["data"], list) and data["data"]:
            last = float(data["data"][0].get("last", 0.0))
        else:
            last = float(data.get("priceInfo", {}).get("lastPrice", 0.0))
        ts = datetime.now(timezone.utc)
        return NSESpot(symbol=symbol, spot=last, ts=ts)
    except Exception:
        return None


def fetch_vix() -> Optional[Tuple[float, datetime]]:
    # India VIX as index name
    s = _session()
    try:
        url = f"{NSE_BASE}/api/quote-index?index={requests.utils.quote('INDIA VIX')}"
        r = s.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        if "data" in data and isinstance(data["data"], list) and data["data"]:
            last = float(data["data"][0].get("last", 0.0))
            return last, datetime.now(timezone.utc)
    except Exception:
        return None
    return None


def fetch_option_chain_indices(symbol: str = "NIFTY") -> Optional[Dict[str, Any]]:
    s = _session()
    try:
        url = f"{NSE_BASE}/api/option-chain-indices?symbol={requests.utils.quote(symbol)}"
        r = s.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def nearest_expiry_from_chain(chain_json: Dict[str, Any], now: datetime) -> Optional[str]:
    rec = chain_json.get("records", {})
    exps = rec.get("expiryDates", [])
    if not exps:
        return None
    # Choose the first non-passed expiry
    for e in exps:
        try:
            # Dates in format '28-Nov-2024'
            dt = datetime.strptime(e, "%d-%b-%Y").replace(tzinfo=now.tzinfo)
            if dt >= now:
                return e
        except Exception:
            continue
    return exps[0]


def chain_for_expiry(chain_json: Dict[str, Any], expiry: str) -> List[Dict[str, Any]]:
    data = chain_json.get("records", {}).get("data", [])
    out: List[Dict[str, Any]] = []
    for row in data:
        if str(row.get("expiryDate")) == expiry:
            out.append(row)
    return out


def extract_chain_points(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Normalize entries with strike, CE/PE LTP, OI, volume
    pts: List[Dict[str, Any]] = []
    for r in rows:
        strike = float(r.get("strikePrice", 0.0))
        ce = r.get("CE") or {}
        pe = r.get("PE") or {}
        pts.append({
            "strike": strike,
            "ce_ltp": float(ce.get("lastPrice") or 0.0),
            "pe_ltp": float(pe.get("lastPrice") or 0.0),
            "ce_oi": int(ce.get("openInterest") or 0),
            "pe_oi": int(pe.get("openInterest") or 0),
            "ce_vol": int(ce.get("totalTradedVolume") or 0),
            "pe_vol": int(pe.get("totalTradedVolume") or 0),
        })
    return pts


def is_data_fresh(server_ts: Optional[str], now: datetime) -> bool:
    if not server_ts:
        return True
    try:
        # Example: '24-May-2024 15:20:00'
        dt = datetime.strptime(server_ts, "%d-%b-%Y %H:%M:%S").replace(tzinfo=now.tzinfo)
        # consider fresh if within 15 minutes
        return abs((now - dt).total_seconds()) < 900
    except Exception:
        return True

