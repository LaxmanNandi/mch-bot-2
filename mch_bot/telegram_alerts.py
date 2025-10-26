from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from collections import deque

import requests


SECRETS_DIR = Path('.secrets')
TELEGRAM_FILE = SECRETS_DIR / 'telegram.json'


def _load_token_and_chats() -> tuple[Optional[str], List[int]]:
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chats: List[int] = []

    if TELEGRAM_FILE.exists():
        try:
            data = json.loads(TELEGRAM_FILE.read_text(encoding='utf-8'))
            token = token or data.get('bot_token')
            chats = [int(x) for x in data.get('allowed_chat_ids', []) if str(x).strip()]
        except Exception:
            pass

    env_ids = os.getenv('TELEGRAM_ALLOWED_IDS')
    if env_ids:
        for x in env_ids.split(','):
            x = x.strip()
            if not x:
                continue
            try:
                chats.append(int(x))
            except Exception:
                pass
    one = os.getenv('TELEGRAM_CHAT_ID')
    if one:
        try:
            chats.append(int(one))
        except Exception:
            pass

    chats = sorted(list({int(x) for x in chats}))
    return token, chats


def _send_telegram_sync(token: str, chat_id: int, text: str, html: bool = True) -> bool:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': text}
        if html:
            payload['parse_mode'] = 'HTML'
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _fmt_time_12(dt: datetime) -> str:
    return dt.strftime('%I:%M %p').lstrip('0')


def _fmt_currency(v: float, symbol: str = '₹') -> str:
    try:
        return f"{symbol}{v:,.0f}"
    except Exception:
        return f"{symbol}{v}"


# Patterns
IMMEDIATE_PATTERNS: Dict[str, List[str]] = {
    # Consider an entry when orders have been sent or placement simulated, not for every leg line
    'entry': ['Simulated order placement', 'Orders sent to broker', 'Entered IC at'],
    'exit': ['Hit TP:', 'Hit SL:'],
    'error': ['ERROR', 'CRITICAL', 'IC validation failed', 'Failed', 'exception', 'traceback'],
    'startup': ['Live loop', 'Bot Started', 'Bot Stopped'],
    'vix_spike': ['VIX spike detected'],
}

HOURLY_PATTERNS: Dict[str, List[str]] = {
    'scan': ['Live Market Data:', 'Recommended Iron Condor:'],
    'rejected': ['No eligible IC', 'IC validation failed'],
    'monitoring': ['Orders sent to broker', 'Simulated order placement', 'Monitoring'],
}


class HourlyBuffer:
    def __init__(self) -> None:
        self.scans: List[str] = []
        self.rejections: List[str] = []
        self.monitoring: List[str] = []
        self.start: Optional[datetime] = None
        self.end: Optional[datetime] = None

    def add(self, category: str, line: str, ts: datetime) -> None:
        if self.start is None:
            self.start = ts
        self.end = ts
        if category == 'scan':
            self.scans.append(line)
        elif category == 'rejected':
            self.rejections.append(line)
        elif category == 'monitoring':
            self.monitoring.append(line)

    def clear(self) -> None:
        self.__init__()


def _ts_from_line(line: str) -> datetime:
    # Expect lines like 'YYYY-MM-DD HH:MM:SS,ms LEVEL ...'
    try:
        prefix = line.split(' ', 2)[:2]
        dt = datetime.fromisoformat(' '.join(prefix).replace(',', '.'))
        return dt
    except Exception:
        return datetime.now()


def _categorize(line: str) -> Tuple[Optional[str], Optional[str]]:
    low = line.lower()
    for cat, pats in IMMEDIATE_PATTERNS.items():
        for p in pats:
            if p.lower() in low:
                return 'immediate', cat
    for cat, pats in HOURLY_PATTERNS.items():
        for p in pats:
            if p.lower() in low:
                return 'hourly', cat
    return None, None


def _format_rupees_in_text(text: str) -> str:
    # @ 43.44 -> @ ₹43
    text = re.sub(r"@\s*([0-9]+(?:\.[0-9]+)?)", lambda m: f"@ {_fmt_currency(float(m.group(1)))}", text)
    # Credit/P&L/Profit/Loss/Target numbers -> ₹ formatted
    def _fmt_named_amount(m):
        label = m.group(1)
        amt = _fmt_currency(float(m.group(2)))
        return f"{label}: {amt}"
    text = re.sub(r"(?i)\b(Credit|P&L|Profit|Loss|Target|max profit|max loss)\s*:?\s*([0-9]+(?:\.[0-9]+)?)", _fmt_named_amount, text)
    return text


def _fmt_immediate(cat: str, line: str) -> str:
    ts = _ts_from_line(line)
    t12 = _fmt_time_12(ts)
    body = _format_rupees_in_text(line.strip())
    if cat == 'entry':
        return f"📊 <b>IRON CONDOR ENTERED</b>\n\n🕐 {t12}\n{body}"
    if cat == 'exit':
        return f"✅ <b>POSITION UPDATE</b>\n\n🕐 {t12}\n{body}"
    if cat == 'error':
        return f"🚨 <b>BOT ERROR</b>\n\n🕐 {t12}\n{body}"
    if cat == 'startup':
        return f"🤖 <b>MCH Bot Event</b>\n\n🕐 {t12}\n{body}"
    if cat == 'vix_spike':
        return f"⚡ <b>VIX ALERT</b>\n\n🕐 {t12}\n{body}"
    return body


def _extract_ic_from_buffer(lines: List[str]) -> Optional[Dict[str, float]]:
    # Find the most recent "Recommended Iron Condor:" block and parse its details
    idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if 'Recommended Iron Condor:' in lines[i]:
            idx = i
            break
    if idx == -1:
        return None
    sp = sc = width = exp_credit = max_profit = max_loss = None
    spot = None
    # Look a few lines above for spot
    for j in range(max(0, idx - 6), idx):
        m = re.search(r"-\s*Spot:\s*([0-9]+(?:\.[0-9]+)?)", lines[j])
        if m:
            try:
                spot = float(m.group(1))
            except Exception:
                pass
    for k in range(idx + 1, min(idx + 12, len(lines))):
        s = lines[k]
        m = re.search(r"Short Put:\s*([0-9]+(?:\.[0-9]+)?)", s)
        if m:
            try:
                sp = float(m.group(1))
            except Exception:
                pass
        m = re.search(r"Short Call:\s*([0-9]+(?:\.[0-9]+)?)", s)
        if m:
            try:
                sc = float(m.group(1))
            except Exception:
                pass
        m = re.search(r"Spread Width:\s*([0-9]+)", s)
        if m:
            try:
                width = float(m.group(1))
            except Exception:
                pass
        m = re.search(r"Expected Credit:\s*([0-9]+(?:\.[0-9]+)?)", s)
        if m:
            try:
                exp_credit = float(m.group(1))
            except Exception:
                pass
        m = re.search(r"Max Profit:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*Max Loss:\s*([0-9]+(?:\.[0-9]+)?)", s)
        if m:
            try:
                max_profit = float(m.group(1))
                max_loss = float(m.group(2))
            except Exception:
                pass
    if sp is None or sc is None or width is None:
        return None
    return {
        'spot': spot if spot is not None else 0.0,
        'sp': sp,
        'sc': sc,
        'width': width,
        'exp_credit': exp_credit if exp_credit is not None else 0.0,
        'max_profit': max_profit if max_profit is not None else 0.0,
        'max_loss': max_loss if max_loss is not None else 0.0,
    }


def _fmt_entry_consolidated(ts: datetime, ic: Dict[str, float]) -> str:
    t12 = _fmt_time_12(ts)
    sp = ic['sp']; sc = ic['sc']; w = ic['width']
    pl = sp - w; cl = sc + w
    credit_pts = ic.get('exp_credit', 0.0)
    max_p = ic.get('max_profit', 0.0)
    max_l = ic.get('max_loss', 0.0)
    credit_rupees = max_p if max_p else credit_pts * 75.0
    spot = ic.get('spot', 0.0)
    lines = [
        "📊 <b>IRON CONDOR ENTERED</b>",
        "",
        f"🕐 {t12} | 📍 NIFTY: {spot:.2f}",
        "",
        "<b>Structure:</b>",
        f"🔴 SELL {int(sp)} PE", f"🟢 BUY {int(pl)} PE",
        f"🔴 SELL {int(sc)} CE", f"🟢 BUY {int(cl)} CE",
        "",
        f"💰 <b>Credit:</b> {_fmt_currency(credit_rupees)} ({credit_pts:.0f} pts)",
        f"📏 Width: {int(w)} points",
        f"🎯 <b>Max Profit:</b> {_fmt_currency(max_p)} | 🛑 <b>Max Loss:</b> {_fmt_currency(max_l)}",
    ]
    return "\n".join(lines)


def _fmt_hourly(buf: HourlyBuffer) -> Optional[str]:
    if not buf.start and not (buf.scans or buf.rejections or buf.monitoring):
        return None
    start = buf.start or datetime.now()
    end = buf.end or datetime.now()
    hdr = f"📋 <b>Hourly Summary</b>\n🕐 {_fmt_time_12(start)} - {_fmt_time_12(end)}\n"
    parts = [hdr]
    parts.append("\n📊 <b>Market Activity</b>:")
    parts.append(f"• {len(buf.scans)} market scans")
    parts.append(f"• {len(buf.monitoring)} monitoring updates")
    parts.append("\n💡 <b>Opportunities</b>:")
    parts.append(f"• {len(buf.rejections)} rejected (risk filters)")
    if not (buf.scans or buf.rejections or buf.monitoring):
        parts.append("\nAll quiet.")
    return "\n".join(parts)


def _summary_scheduler(send_func, token: str, chats: List[int], buf: HourlyBuffer, interval_minutes: int = 60):
    # Fire on the hour (or every interval) precisely
    while True:
        now = datetime.now()
        if interval_minutes == 60:
            # next top of the hour
            nxt = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        else:
            nxt = now + timedelta(minutes=interval_minutes)
            nxt = nxt.replace(second=0, microsecond=0)
        sleep_s = max(1, (nxt - now).total_seconds())
        time.sleep(sleep_s)
        try:
            msg = _fmt_hourly(buf)
            if msg:
                for cid in chats:
                    send_func(token, cid, msg, html=True)
            buf.clear()
        except Exception:
            # ignore scheduler errors
            buf.clear()
            continue


def tail_file(path: Path, patterns: Iterable[str], poll_s: float = 1.5) -> None:
    token, chats = _load_token_and_chats()
    if not token or not chats:
        raise RuntimeError("Telegram alerts require bot token and allowed_chat_ids. Use telegram-setup and /id, then allow.")

    # Hourly buffer and scheduler
    buf = HourlyBuffer()
    t = threading.Thread(target=_summary_scheduler, args=(_send_telegram_sync, token, chats, buf, 60), daemon=True)
    t.start()

    pos = 0
    recent = deque(maxlen=200)
    last_entry_sig: Optional[str] = None
    while True:
        try:
            if not path.exists():
                time.sleep(poll_s)
                continue
            with path.open('r', encoding='utf-8', errors='ignore') as f:
                f.seek(pos)
                for line in f:
                    txt = line.strip()
                    if not txt:
                        continue
                    recent.append(txt)
                    scope, cat = _categorize(txt)
                    if scope == 'immediate' and cat:
                        if cat == 'entry':
                            ic = _extract_ic_from_buffer(list(recent))
                            if ic:
                                ts = _ts_from_line(txt)
                                sig = f"{int(ic['sp'])}-{int(ic['sc'])}-{int(ic['width'])}-{ts.strftime('%Y%m%d%H%M')}"
                                # Deduplicate entries within the same minute
                                if sig != last_entry_sig:
                                    last_entry_sig = sig
                                    msg = _fmt_entry_consolidated(ts, ic)
                                    for cid in chats:
                                        _send_telegram_sync(token, cid, msg, html=True)
                            else:
                                msg = _fmt_immediate(cat, txt)
                                for cid in chats:
                                    _send_telegram_sync(token, cid, msg, html=True)
                        else:
                            msg = _fmt_immediate(cat, txt)
                            for cid in chats:
                                _send_telegram_sync(token, cid, msg, html=True)
                    elif scope == 'hourly' and cat:
                        buf.add(cat, txt, _ts_from_line(txt))
                    else:
                        # Not matched: ignore to avoid spam
                        pass
                pos = f.tell()
        except Exception:
            time.sleep(poll_s)
        time.sleep(poll_s)
