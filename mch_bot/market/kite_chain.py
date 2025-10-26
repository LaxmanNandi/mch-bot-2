from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pytz

from kiteconnect import KiteConnect


CACHE = Path('.secrets/kite_instruments.json')


@dataclass
class Instrument:
    instrument_token: int
    exchange: str
    tradingsymbol: str
    name: str
    segment: str
    strike: float
    instrument_type: str  # CE/PE/others
    expiry: Optional[datetime]


def _parse_expiry(x) -> Optional[datetime]:
    if not x:
        return None
    try:
        return datetime.strptime(x, "%Y-%m-%d")
    except Exception:
        try:
            return datetime.fromisoformat(x)
        except Exception:
            return None


def load_instruments(kite: KiteConnect, force_refresh: bool = False) -> List[Instrument]:
    if CACHE.exists() and not force_refresh:
        try:
            raw = json.loads(CACHE.read_text(encoding='utf-8'))
            out: List[Instrument] = []
            for r in raw:
                exp = _parse_expiry(r.get('expiry'))
                out.append(Instrument(
                    instrument_token=int(r['instrument_token']),
                    exchange=r['exchange'],
                    tradingsymbol=r['tradingsymbol'],
                    name=r.get('name') or '',
                    segment=r['segment'],
                    strike=float(r.get('strike') or 0.0),
                    instrument_type=r.get('instrument_type') or '',
                    expiry=exp,
                ))
            return out
        except Exception:
            pass

    data = kite.instruments("NFO")
    result: List[Instrument] = []
    serializable = []
    for d in data:
        exp = d.get('expiry')
        exp_dt = None
        if exp:
            if isinstance(exp, datetime):
                exp_dt = exp
            else:
                exp_dt = _parse_expiry(str(exp))
        itype = d.get('instrument_type') or ''
        result.append(Instrument(
            instrument_token=int(d['instrument_token']),
            exchange=d['exchange'],
            tradingsymbol=d['tradingsymbol'],
            name=d.get('name') or '',
            segment=d['segment'],
            strike=float(d.get('strike') or 0.0),
            instrument_type=itype,
            expiry=exp_dt,
        ))
        serializable.append({
            "instrument_token": int(d['instrument_token']),
            "exchange": d['exchange'],
            "tradingsymbol": d['tradingsymbol'],
            "name": d.get('name') or '',
            "segment": d['segment'],
            "strike": float(d.get('strike') or 0.0),
            "instrument_type": itype,
            "expiry": exp_dt.strftime('%Y-%m-%d') if exp_dt else None,
        })
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(serializable), encoding='utf-8')
    return result


def next_weekly_expiry(now: datetime, weekday: str = "TUE", tz: str = "Asia/Kolkata") -> datetime:
    # Compute next occurrence of given weekday in local TZ
    tzinfo = pytz.timezone(tz)
    local_now = now.astimezone(tzinfo)
    weekday_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}
    target = weekday_map.get(weekday.upper(), 3)
    days_ahead = (target - local_now.weekday()) % 7
    if days_ahead == 0 and local_now.hour >= 15:
        days_ahead = 7
    exp_local = (local_now + timedelta(days=days_ahead)).replace(hour=15, minute=30, second=0, microsecond=0)
    return exp_local.astimezone(pytz.UTC)


def filter_chain(
    instruments: List[Instrument],
    underlying_name: str = "NIFTY",
    expiry_date: Optional[datetime] = None,
) -> List[Instrument]:
    out = [i for i in instruments if i.name.upper() == underlying_name.upper() and i.instrument_type in ("CE", "PE")]
    if expiry_date:
        # Compare date only
        ed = expiry_date.date()
        out = [i for i in out if i.expiry and i.expiry.date() == ed]
    return out


def ltp_dict(kite: KiteConnect, symbols: Iterable[str]) -> Dict[str, float]:
    syms = list(symbols)
    if not syms:
        return {}
    data = kite.ltp(syms)
    out: Dict[str, float] = {}
    for key, val in data.items():
        out[key] = float(val.get('last_price'))
    return out


def nearest_by_strike(chain: List[Instrument], strike: float, opt_type: str) -> Optional[Instrument]:
    candidates = [i for i in chain if i.instrument_type.upper() == ("CE" if opt_type == "CALL" else "PE")]
    if not candidates:
        return None
    best = min(candidates, key=lambda i: abs(i.strike - strike))
    return best


def strikes_from_chain(chain: List[Instrument]) -> List[float]:
    return sorted({float(i.strike) for i in chain})


