from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_config, Config
from .utils.log_parser import LogParser, TradeRecord, Decision
from .strategy.iron_condor import ICParams, build_iron_condor_balanced
from .data.bs import black_scholes


@dataclass
class Response:
    text: str

    @staticmethod
    def format_table(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "(no data)"
        # Compute column widths
        headers = list(rows[0].keys())
        widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}
        line = " | ".join(h.ljust(widths[h]) for h in headers)
        sep = "-+-".join("-" * widths[h] for h in headers)
        body = [" | ".join(str(r.get(h, "")).ljust(widths[h]) for h in headers) for r in rows]
        return "\n".join([line, sep, *body])

    @staticmethod
    def format_explanation(decision: Decision, extra: Optional[str] = None) -> str:
        parts = [f"{decision.timestamp}: {decision.message}"]
        if extra:
            parts.append(extra)
        return "\n".join(parts)


class QueryEngine:
    def __init__(self, log_dir: str = "logs/", config_path: str = "config.yaml") -> None:
        self.log_dir = Path(log_dir)
        self.parser = LogParser(self.log_dir)
        self.config_path = Path(config_path)
        self.cfg: Optional[Config] = None
        if self.config_path.exists():
            self.cfg = load_config(self.config_path)

    def parse_question(self, user_input: str) -> Dict[str, Any]:
        q = user_input.strip().lower()
        # Status
        if any(k in q for k in ["status", "health", "state", "what's running", "whats running"]):
            return {"type": "status"}
        # Explanation
        if any(k in q for k in ["why", "explain", "reason", "decision"]):
            if "last" in q:
                return {"type": "explain", "ref": "last"}
            ts = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", q)
            return {"type": "explain", "ref": ts.group(1) if ts else "last"}
        # History/performance
        if any(k in q for k in ["trades", "history", "performance", "pnl", "p&l"]):
            n = re.search(r"last\s+(\d+)", q)
            date_m = re.search(r"(\d{4}-\d{2}-\d{2})", q)
            return {"type": "history", "last": int(n.group(1)) if n else None, "date": date_m.group(1) if date_m else None}
        # Simulation
        if any(k in q for k in ["what if", "simulate", "scenario"]):
            spot = None
            vix = None
            m_spot = re.search(r"spot\s*=\s*([0-9]+(?:\.[0-9]+)?)", q)
            m_vix = re.search(r"vix\s*=\s*([0-9]+(?:\.[0-9]+)?)", q)
            if m_spot:
                spot = float(m_spot.group(1))
            if m_vix:
                vix = float(m_vix.group(1))
            return {"type": "simulate", "spot": spot, "vix": vix}
        # Default to status
        return {"type": "status"}

    def execute_query(self, parsed: Dict[str, Any]) -> Response:
        t = parsed.get("type")
        if t == "status":
            return self.handle_status_query()
        if t == "explain":
            return self.handle_explanation_query(parsed.get("ref", "last"))
        if t == "history":
            return self.handle_history_query({"last": parsed.get("last"), "date": parsed.get("date")})
        if t == "simulate":
            return self.handle_simulation_query({"spot": parsed.get("spot"), "vix": parsed.get("vix")})
        return Response(text="Unknown query type.")

    # Handlers
    def handle_status_query(self) -> Response:
        # Basic operational status from config and last logs
        lines: List[str] = []
        lines.append("Bot status: query interface online.")
        if self.cfg is not None:
            broker = str(self.cfg.get("execution.broker", "paper"))
            dry = bool(self.cfg.get("execution.dry_run", True))
            lines.append(f"Execution: broker={broker}, dry_run={dry}")
        # Last decision/trade from logs
        decs = self.parser.extract_trade_decisions()
        trades = self.parser.parse_structured_logs()
        if decs:
            lines.append(f"Last decision: {decs[0].timestamp} -> {decs[0].message[:80]}")
        if trades:
            tr = trades[0]
            lines.append(
                f"Last trade-like entry: {tr.timestamp} | short_put={tr.short_put} short_call={tr.short_call} width={tr.width} credit={tr.credit}"
            )
        return Response(text="\n".join(lines))

    def handle_explanation_query(self, action_ref: str) -> Response:
        decs = self.parser.extract_trade_decisions()
        if not decs:
            return Response(text="No recent decisions found in logs.")
        dec = decs[0]
        return Response(text=Response.format_explanation(decision=dec))

    def handle_history_query(self, filters: Dict[str, Any]) -> Response:
        trades = self.parser.parse_structured_logs()
        if not trades:
            return Response(text="No trade history found in logs.")
        rows: List[Dict[str, Any]] = []
        for tr in trades:
            rows.append({
                "time": tr.timestamp.strftime("%Y-%m-%d %H:%M"),
                "short_put": tr.short_put or "",
                "short_call": tr.short_call or "",
                "width": tr.width or "",
                "credit": tr.credit or "",
                "maxP": tr.max_profit or "",
                "maxL": tr.max_loss or "",
            })
        # Filters
        date = filters.get("date")
        if date:
            rows = [r for r in rows if r["time"].startswith(date)]
        n = filters.get("last")
        if n:
            rows = rows[: int(n)]
        return Response(text=Response.format_table(rows))

    def handle_simulation_query(self, scenario: Dict[str, Any]) -> Response:
        if self.cfg is None:
            return Response(text="Missing config.yaml; cannot simulate.")
        spot = scenario.get("spot") or float(self.cfg.get("demo.spot", 23500))
        iv = float(self.cfg.get("demo.iv", 0.18))
        r = float(self.cfg.get("backtest.risk_free_rate", 0.06))
        step = float(self.cfg.get("instrument.strike_step", 50))
        lot = int(self.cfg.get("instrument.lot_size", 75))
        width = float(self.cfg.get("strategy.wing_width_points", 400))
        target_distance = float(self.cfg.get("strategy.target_distance_points", 300))
        ic = build_iron_condor_balanced(
            spot=spot,
            lot_size=lot,
            step=step,
            params=ICParams(target_delta=float(self.cfg.get("strategy.target_delta", 0.15)), wing_width_points=width, min_credit_per_ic=float(self.cfg.get("strategy.min_credit_per_ic", 1))),
            target_distance=target_distance,
            price_fn=black_scholes,
            expiry_t=max(1/252, float(self.cfg.get("strategy.min_days_to_expiry", 2)) / 252.0),
            r=r,
            iv=iv,
        )
        if not ic.legs:
            return Response(text="Simulation produced no eligible IC under current constraints.")
        credit = ic.net_credit
        max_profit = credit * lot
        max_loss = max(0.0, (width - credit)) * lot
        sp = next(l.strike for l in ic.legs if l.side == 'SELL' and l.option_type == 'PUT')
        sc = next(l.strike for l in ic.legs if l.side == 'SELL' and l.option_type == 'CALL')
        lines = [
            f"Simulated with spot={spot:.2f}, iv={iv:.2f}, width={width:.0f}, td={target_distance:.0f}",
            f"Short Put: {sp} | Short Call: {sc}",
            f"Credit: {credit:.2f} | Max Profit: {max_profit:.2f} | Max Loss: {max_loss:.2f}",
        ]
        return Response(text="\n".join(lines))

