from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import pytz


@dataclass
class MarketHours:
    tz: str = "Asia/Kolkata"
    open_time: str = "09:15"  # HH:MM local
    close_time: str = "15:30"
    weekdays: set[int] = None  # 0=Mon .. 6=Sun
    holidays: set[str] = None  # YYYY-MM-DD strings in local tz

    def __post_init__(self):
        if self.weekdays is None:
            self.weekdays = {0, 1, 2, 3, 4}
        if self.holidays is None:
            self.holidays = set()

    def is_open(self, now_utc: datetime) -> bool:
        tzinfo = pytz.timezone(self.tz)
        local = now_utc.astimezone(tzinfo)
        if local.weekday() not in self.weekdays:
            return False
        if local.strftime('%Y-%m-%d') in self.holidays:
            return False
        ot = time.fromisoformat(self.open_time)
        ct = time.fromisoformat(self.close_time)
        return ot <= local.time() <= ct

    def next_open(self, now_utc: datetime) -> datetime:
        tzinfo = pytz.timezone(self.tz)
        local = now_utc.astimezone(tzinfo)
        ot = time.fromisoformat(self.open_time)
        # move forward in days until a non-holiday weekday
        d = 0
        while True:
            candidate = (local + timedelta(days=d)).date().strftime('%Y-%m-%d')
            wd = (local + timedelta(days=d)).weekday()
            if wd in self.weekdays and candidate not in self.holidays:
                open_local = tzinfo.localize(datetime.combine((local + timedelta(days=d)).date(), ot))
                if d == 0 and local.time() <= ot:
                    return open_local.astimezone(pytz.UTC)
                if d > 0:
                    return open_local.astimezone(pytz.UTC)
            d += 1

