from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RateLimiter:
    min_interval_s: float
    _last: float = 0.0

    def wait(self) -> None:
        now = time.time()
        dt = now - self._last
        if dt < self.min_interval_s:
            time.sleep(self.min_interval_s - dt)
        self._last = time.time()

