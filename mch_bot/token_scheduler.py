from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from time import sleep

from apscheduler.schedulers.background import BackgroundScheduler

from .token_refresh import run_refresh_workflow


log = logging.getLogger("token_scheduler")


def schedule_daily(hour: int = 6, minute: int = 0, tz: str = "Asia/Kolkata") -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(run_refresh_workflow, trigger='cron', hour=hour, minute=minute, id='token_refresh')
    scheduler.start()
    log.info(f"Token scheduler started for {hour:02d}:{minute:02d} {tz}")
    try:
        while True:
            sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    h = int(os.getenv("TOKEN_REFRESH_HOUR", "6"))
    m = int(os.getenv("TOKEN_REFRESH_MINUTE", "0"))
    tz = os.getenv("TOKEN_REFRESH_TZ", "Asia/Kolkata")
    schedule_daily(h, m, tz)

