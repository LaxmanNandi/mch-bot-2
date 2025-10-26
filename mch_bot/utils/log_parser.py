from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict


@dataclass
class TradeRecord:
    timestamp: datetime
    short_put: Optional[float]
    short_call: Optional[float]
    width: Optional[float]
    credit: Optional[float]
    max_profit: Optional[float]
    max_loss: Optional[float]
    context: Dict[str, str]


@dataclass
class Decision:
    timestamp: datetime
    message: str
    context: Dict[str, str]


class LogParser:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir

    def _iter_log_files(self) -> List[Path]:
        if not self.log_dir.exists():
            return []
        files = sorted([p for p in self.log_dir.glob("**/*") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
        # Only read up to a handful of latest files to keep it light
        return files[:5]

    def _parse_dt_from_line(self, line: str) -> Optional[datetime]:
        # Expect lines starting with 'YYYY-MM-DD HH:MM:SS,' optionally timezone info is ignored
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", line)
        if not m:
            return None
        try:
            return datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
        except Exception:
            return None

    def parse_structured_logs(self) -> List[TradeRecord]:
        trades: List[TradeRecord] = []
        for f in self._iter_log_files():
            try:
                lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue

            # Single-pass state machine to assemble records across multiple lines
            cur_ts: Optional[datetime] = None
            cur_sp: Optional[float] = None
            cur_sc: Optional[float] = None
            cur_width: Optional[float] = None
            cur_credit: Optional[float] = None
            cur_mp: Optional[float] = None
            cur_ml: Optional[float] = None

            def commit():
                nonlocal cur_ts, cur_sp, cur_sc, cur_width, cur_credit, cur_mp, cur_ml
                if cur_ts and (cur_sp or cur_sc):
                    trades.append(
                        TradeRecord(
                            timestamp=cur_ts,
                            short_put=cur_sp,
                            short_call=cur_sc,
                            width=cur_width,
                            credit=cur_credit,
                            max_profit=cur_mp,
                            max_loss=cur_ml,
                            context={},
                        )
                    )
                cur_ts = None
                cur_sp = None
                cur_sc = None
                cur_width = None
                cur_credit = None
                cur_mp = None
                cur_ml = None

            for raw in lines:
                # Detect block start via timestamp
                ts = self._parse_dt_from_line(raw)
                if ts:
                    cur_ts = ts

                # One-line captures
                m = re.search(r"Short Put:\s*([0-9]+(?:\.[0-9]+)?)", raw)
                if m:
                    try:
                        cur_sp = float(m.group(1))
                    except Exception:
                        pass
                m = re.search(r"Short Call:\s*([0-9]+(?:\.[0-9]+)?)", raw)
                if m:
                    try:
                        cur_sc = float(m.group(1))
                    except Exception:
                        pass
                m = re.search(r"Spread Width:\s*([0-9]+)", raw)
                if m:
                    try:
                        cur_width = float(m.group(1))
                    except Exception:
                        pass
                m = re.search(r"Expected Credit:\s*([0-9]+(?:\.[0-9]+)?)", raw)
                if m:
                    try:
                        cur_credit = float(m.group(1))
                    except Exception:
                        pass
                m = re.search(r"Max Profit:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*Max Loss:\s*([0-9]+(?:\.[0-9]+)?)", raw)
                if m:
                    try:
                        cur_mp = float(m.group(1))
                        cur_ml = float(m.group(2))
                    except Exception:
                        pass
                # When a simulated order line appears, we can commit the current block
                if "Simulated order placement" in raw:
                    commit()

            # Ensure last block committed
            commit()

        # Sort newest first
        trades.sort(key=lambda t: t.timestamp, reverse=True)
        return trades

    def extract_trade_decisions(self) -> List[Decision]:
        decisions: List[Decision] = []
        for f in self._iter_log_files():
            try:
                for raw in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if "Live Market Data:" in raw or "Recommended Iron Condor:" in raw or "IC validation failed" in raw:
                        ts = self._parse_dt_from_line(raw) or datetime.now()
                        decisions.append(Decision(timestamp=ts, message=raw.strip(), context={}))
            except Exception:
                continue
        return decisions
