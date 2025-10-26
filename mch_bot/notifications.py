from __future__ import annotations

import logging
import os
import threading
import time
from queue import Queue, Empty
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler


log = logging.getLogger("notifications")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v is not None else default


@dataclass
class NotificationConfig:
    enabled: bool = True
    immediate_alerts: bool = True
    daily_summary: bool = True
    weekly_report: bool = True
    retry_attempts: int = 3
    queue_size: int = 50
    tz: str = "Asia/Kolkata"


class NotificationManager:
    def __init__(self, config: NotificationConfig) -> None:
        self.config = config
        self.bot_token = _env("TELEGRAM_BOT_TOKEN")
        # Prefer explicit chat id; fall back to allowed ids list (first)
        chat = _env("TELEGRAM_CHAT_ID")
        if not chat:
            allowed = _env("TELEGRAM_ALLOWED_IDS")
            if allowed:
                chat = allowed.split(",")[0].strip()
        self.chat_id = chat
        self._q: "Queue[Dict[str, Any]]" = Queue(maxsize=config.queue_size)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="notif-worker", daemon=True)
        self._started = False
        self._scheduler: Optional[BackgroundScheduler] = None

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()
        if self.config.daily_summary or self.config.weekly_report:
            self.schedule_reports()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
        except Exception:
            pass

    # Public API
    def send_immediate_alert(self, alert_type: str, data: Dict[str, Any]) -> None:
        if not self.config.enabled or not self.config.immediate_alerts:
            return
        msg = self._format_immediate(alert_type, data)
        if not msg:
            return
        self._enqueue(msg)

    def schedule_reports(self) -> None:
        try:
            from pytz import timezone  # optional; falls back to string tz if unavailable
            tz = timezone(self.config.tz)
        except Exception:
            tz = self.config.tz
        self._scheduler = BackgroundScheduler(timezone=tz)
        if self.config.daily_summary:
            self._scheduler.add_job(self._daily_summary, 'cron', hour=16, minute=0, id='daily')
        if self.config.weekly_report:
            self._scheduler.add_job(self._weekly_report, 'cron', day_of_week='sun', hour=20, minute=0, id='weekly')
        self._scheduler.start()

    # Internal
    def _enqueue(self, text: str) -> None:
        try:
            self._q.put_nowait({"text": text})
        except Exception:
            log.warning("Notification queue is full; dropping message")

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except Empty:
                continue
            try:
                self._send_telegram_message(item["text"], parse_mode='HTML')
            except Exception as e:
                log.warning(f"Notification send failed: {e}")
            finally:
                self._q.task_done()

    def _send_telegram_message(self, message: str, parse_mode: str = 'HTML') -> None:
        if not self.bot_token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": int(self.chat_id), "text": message, "parse_mode": parse_mode}
        backoff = 1.0
        for attempt in range(self.config.retry_attempts):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    return
                log.warning(f"Telegram send attempt {attempt+1} failed: {resp.status_code} {resp.text}")
            except Exception as e:
                log.warning(f"Telegram send error (attempt {attempt+1}): {e}")
            time.sleep(backoff)
            backoff *= 2

    # Formatting
    def _format_immediate(self, alert_type: str, d: Dict[str, Any]) -> Optional[str]:
        try:
            if alert_type == 'entry':
                t = d.get('time_str', '')
                spot = d.get('spot')
                sp = d.get('short_put')
                pl = d.get('long_put')
                sc = d.get('short_call')
                cl = d.get('long_call')
                credit_rupees = d.get('credit_rupees')
                credit_pts = d.get('credit_pts')
                target_rupees = d.get('target_rupees')
                sl_rupees = d.get('sl_rupees')
                cooldown = d.get('cooldown')
                return (
                    f"🎯 <b>IRON CONDOR ENTERED</b>\n"
                    f"⏰ {t} | 📈 NIFTY: {spot:.2f}\n\n"
                    f"🛡️ <b>STRUCTURE</b>:\n"
                    f"• SELL {int(sp)} PE\n"
                    f"• BUY {int(pl)} PE\n"
                    f"• SELL {int(sc)} CE\n"
                    f"• BUY {int(cl)} CE\n\n"
                    f"💰 <b>CREDIT:</b> ₹{credit_rupees:,.0f} ({credit_pts:.0f} pts)\n"
                    f"🎯 <b>TARGET:</b> ₹{target_rupees:,.0f} (50%)\n"
                    f"🛑 <b>STOP LOSS:</b> ₹{sl_rupees:,.0f} (100%)\n"
                    f"⏳ <b>COOLDOWN:</b> {cooldown} min after exit"
                )
            if alert_type == 'exit':
                t = d.get('time_str', '')
                duration = d.get('duration', '')
                entry_rupees = d.get('entry_rupees')
                exit_rupees = d.get('exit_rupees')
                pnl_rupees = d.get('pnl_rupees')
                pnl_pct = d.get('pnl_pct')
                reason = d.get('reason', 'Closed')
                next_ready = d.get('next_ready', '')
                return (
                    f"✅ <b>TRADE CLOSED - PROFIT</b>\n"
                    f"⏰ {t} | 🕐 Duration: {duration}\n\n"
                    f"📊 <b>PERFORMANCE</b>:\n"
                    f"• Entry: ₹{entry_rupees:,.0f} credit\n"
                    f"• Exit: ₹{exit_rupees:,.0f} debit\n"
                    f"• P&L: ₹{pnl_rupees:,.0f} (+{pnl_pct:.1f}%)\n"
                    f"• Reason: {reason}\n\n"
                    f"⏳ Next trade available: {next_ready}"
                )
        except Exception as e:
            log.warning(f"Immediate alert formatting failed: {e}")
        return None

    # Scheduled
    def _daily_summary(self) -> None:
        # Summarize today's trades from .runtime/trades.jsonl
        try:
            from pathlib import Path
            import json
            from datetime import datetime
            # Get local date in configured tz
            try:
                from zoneinfo import ZoneInfo
                today_local = datetime.now(ZoneInfo(self.config.tz)).strftime('%Y-%m-%d')
            except Exception:
                today_local = datetime.now().strftime('%Y-%m-%d')
            trades_path = Path('.runtime/trades.jsonl')
            trades = []
            if trades_path.exists():
                for line in trades_path.read_text(encoding='utf-8').splitlines():
                    try:
                        rec = json.loads(line)
                        if rec.get('date_local') == today_local:
                            trades.append(rec)
                    except Exception:
                        continue
            count = len(trades)
            pnl_total = sum(float(t.get('pnl_rupees', 0.0)) for t in trades)
            wins = sum(1 for t in trades if float(t.get('pnl_rupees', 0.0)) > 0)
            losses = sum(1 for t in trades if float(t.get('pnl_rupees', 0.0)) <= 0 and t.get('pnl_rupees') is not None)
            best = max(trades, key=lambda t: float(t.get('pnl_rupees', -1e18)), default=None)
            worst = min(trades, key=lambda t: float(t.get('pnl_rupees', 1e18)), default=None)
            msg = [
                f"📊 <b>DAILY PERFORMANCE - {today_local}</b>",
                "🕔 4:00 PM Report\n",
                f"📈 Trades today: {count}",
                f"✅ Wins: {wins} | ❌ Losses: {losses}",
                f"💰 Total P&L: ₹{pnl_total:,.0f}",
            ]
            if best:
                msg.append(f"🏆 Best Trade: ₹{float(best.get('pnl_rupees', 0.0)):,.0f}")
            if worst:
                msg.append(f"📉 Worst Trade: ₹{float(worst.get('pnl_rupees', 0.0)):,.0f}")
            self._enqueue("\n".join(msg))
        except Exception as e:
            log.warning(f"Daily summary failed: {e}")

    def _weekly_report(self) -> None:
        try:
            from pathlib import Path
            import json
            from datetime import datetime, timedelta
            # Range: last 7 days local
            try:
                from zoneinfo import ZoneInfo
                now_local = datetime.now(ZoneInfo(self.config.tz))
            except Exception:
                now_local = datetime.now()
            days = [(now_local - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
            trades_path = Path('.runtime/trades.jsonl')
            trades = []
            if trades_path.exists():
                for line in trades_path.read_text(encoding='utf-8').splitlines():
                    try:
                        rec = json.loads(line)
                        if rec.get('date_local') in days:
                            trades.append(rec)
                    except Exception:
                        continue
            count = len(trades)
            pnl_total = sum(float(t.get('pnl_rupees', 0.0)) for t in trades)
            wins = sum(1 for t in trades if float(t.get('pnl_rupees', 0.0)) > 0)
            losses = sum(1 for t in trades if float(t.get('pnl_rupees', 0.0)) <= 0 and t.get('pnl_rupees') is not None)
            msg = (
                f"📋 <b>WEEKLY REPORT</b>\n"
                f"Days: {days[-1]} ➜ {days[0]}\n\n"
                f"📈 Trades: {count}\n"
                f"✅ Wins: {wins} | ❌ Losses: {losses}\n"
                f"💰 Total P&L: ₹{pnl_total:,.0f}"
            )
            self._enqueue(msg)
        except Exception as e:
            log.warning(f"Weekly report failed: {e}")
