from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from pathlib import Path
from typing import Optional

import numpy as np

from .config import Config
from .logging_utils import setup_logging
from .mch.rci import RCIInputs, rci_score
from .mch.oia import OIAProfile, oia_permit
from .mch.at import authenticated_to_trade
from .data.csv_source import iter_underlying_csv
from .data.bs import black_scholes, black_scholes_delta
from .strategy.iron_condor import (
    ICParams,
    ICConstraints,
    build_iron_condor_balanced,
    validate_balanced_ic,
)
from .risk.position import PositionSizing
from .brokers.base import Order
from .brokers.paper import PaperBroker
from .brokers.zerodha_kite import KiteBroker
from .market.kite_chain import load_instruments, next_weekly_expiry, filter_chain, ltp_dict, nearest_by_strike, strikes_from_chain
from .market.chain_tools import build_chain_points, choose_by_target_delta
from .market.hours import MarketHours
from .utils.ratelimit import RateLimiter
from .market.iv import implied_vol_price
from .market.quotes import quote_dict
# NSE API removed - using only Zerodha Kite for data sources
# from .market import nse as nse
import json
from pathlib import Path as _Path
from .notifications import NotificationManager, NotificationConfig


log = logging.getLogger("engine")
_prev_spot: Optional[float] = None


# --- Simple on-disk state for live-loop re-entry control ---
_STATE_FILE = _Path(".runtime/state.json")
_TRADES_FILE = _Path(".runtime/trades.jsonl")
_NOTIFIER: Optional[NotificationManager] = None


def _load_state() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"position": "flat", "last_entry_ts": None, "last_exit_ts": None}


def _save_state(d: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def _append_trade(rec: dict) -> None:
    try:
        _TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _TRADES_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _get_notifier(cfg: Config) -> Optional[NotificationManager]:
    global _NOTIFIER
    if _NOTIFIER is not None:
        return _NOTIFIER
    if not bool(cfg.get("notifications.enabled", True)):
        return None
    nc = NotificationConfig(
        enabled=True,
        immediate_alerts=bool(cfg.get("notifications.telegram.immediate_alerts", True)),
        daily_summary=bool(cfg.get("notifications.telegram.daily_summary", True)),
        weekly_report=bool(cfg.get("notifications.telegram.weekly_report", True)),
        retry_attempts=int(cfg.get("notifications.retry_attempts", 3)),
        queue_size=int(cfg.get("notifications.queue_size", 50)),
        tz=str(cfg.get("timezone", "Asia/Kolkata")),
    )
    _NOTIFIER = NotificationManager(nc)
    _NOTIFIER.start()
    return _NOTIFIER


@dataclass
class TradeResult:
    entry_time: datetime
    exit_time: datetime
    net_credit_per_unit: float
    net_exit_per_unit: float
    pnl_per_unit: float


def expiry_t_from_days(days: int) -> float:
    return max(0.001, days / 252.0)  # trading year approximation


def compute_stability(values: list[float], lookback: int) -> float:
    if len(values) < max(lookback, 3):
        return 0.5
    recent = np.array(values[-lookback:])
    vol = float(np.std(recent))
    base = float(np.std(np.array(values))) + 1e-9
    st = 1.0 - min(1.0, vol / base)
    return float(max(0.0, min(1.0, st)))


def run_backtest(cfg: Config, data_path: Path) -> None:
    setup_logging()
    tz = cfg.get("timezone", "Asia/Kolkata")
    lot = int(cfg.get("instrument.lot_size", 75))
    r = float(cfg.get("backtest.risk_free_rate", 0.06))
    commission = float(cfg.get("backtest.commission_per_lot", 40.0))
    ps = PositionSizing(
        account_equity=float(cfg.get("risk.account_equity", 1_000_000)),
        max_risk_pct=float(cfg.get("risk.max_risk_per_trade_pct", 2.0)),
    )

    icp = ICParams(
        target_delta=float(cfg.get("strategy.target_delta", 0.15)),
        wing_width_points=float(cfg.get("strategy.wing_width_points", 400)),
        min_credit_per_ic=float(cfg.get("strategy.min_credit_per_ic", 1)),
    )
    icc = ICConstraints(
        min_otm_distance=float(cfg.get("strategy.min_otm_distance", 200)),
        max_otm_distance=float(cfg.get("strategy.max_otm_distance", 500)),
        require_equal_wings=True,
        required_lot_size=int(cfg.get("instrument.lot_size", 75)),
    )
    rci_thr = float(cfg.get("mch.rci_threshold", 0.65))
    vix_bounds = tuple(cfg.get("mch.vix_bounds", [12.0, 22.0]))  # type: ignore
    stability_lookback = int(cfg.get("mch.stability_lookback", 5))

    prices: list[float] = []
    vixes: list[float] = []
    trades: list[TradeResult] = []

    def _as_hhmm_pair(x, default_a: str, default_b: str):
        if not isinstance(x, (list, tuple)) or len(x) != 2:
            return (default_a, default_b)
        a, b = str(x[0]), str(x[1])
        return (a[:5], b[:5])

    entry_window = _as_hhmm_pair(cfg.get("strategy.entry_intraday_window", ["09:30", "10:15"]), "09:30", "10:15")  # noqa
    exit_window = _as_hhmm_pair(cfg.get("strategy.exit_intraday_window", ["14:45", "15:10"]), "14:45", "15:10")   # noqa
    min_dte = int(cfg.get("strategy.min_days_to_expiry", 2))

    entry_bar = None
    entry_ic = None
    entry_credit = 0.0

    for bar in iter_underlying_csv(data_path, tz=tz):
        prices.append(bar.close)
        if bar.iv is not None:
            vixes.append(bar.iv)

        now_hhmm = bar.ts.strftime("%H:%M")

        stability = compute_stability(prices, stability_lookback)
        vix_val = float(vixes[-1]) if vixes else None
        if vix_val is not None and vix_val <= 1.0:
            vix_val *= 100.0  # interpret as decimal IV -> VIX style percent
        adx_val = None  # placeholder; could be computed from prices
        rci = rci_score(
            RCIInputs(
                vix=vix_val,
                vix_bounds=(float(vix_bounds[0]), float(vix_bounds[1])),
                adx=adx_val,
                trend_neutrality_max_adx=float(cfg.get("mch.trend_neutrality_max_adx", 20)),
                stability_score=stability,
            )
        )

        # OIA gate
        oia_ok = oia_permit(
            symbol=str(cfg.get("instrument.symbol", "NIFTY")),
            current_positions=1 if entry_ic else 0,
            profile=OIAProfile(
                allowed_symbols={str(cfg.get("instrument.symbol", "NIFTY"))},
                max_positions=int(cfg.get("risk.max_positions", 1)),
                trading_hours=("09:15", "15:20"),
            ),
            now_hhmm=now_hhmm,
        )

        if entry_ic is None:
            # look for entry
            if entry_window[0] <= now_hhmm <= entry_window[1] and oia_ok and authenticated_to_trade(rci, rci_thr):
                iv_use = float(bar.iv) if bar.iv is not None else 0.18
                target_dist = float(cfg.get("strategy.target_distance_points", 300))
                ic = build_iron_condor_balanced(
                    spot=bar.close,
                    lot_size=lot,
                    step=float(cfg.get("instrument.strike_step", 50)),
                    params=icp,
                    target_distance=target_dist,
                    price_fn=black_scholes,
                    expiry_t=expiry_t_from_days(min_dte),
                    r=r,
                    iv=iv_use,
                )
                ok, reasons = validate_balanced_ic(bar.close, ic, icc, lot)
                if not ok:
                    log.warning(f"IC validation failed: {', '.join(reasons)}")
                elif ic.legs:
                    width = icp.wing_width_points
                    credit = ic.net_credit
                    max_profit = credit * lot
                    max_loss = max(0.0, (width - credit)) * lot
                    log.info(
                        f"Entered IC at {bar.ts} | short_put {next(l.strike for l in ic.legs if l.option_type=='PUT' and l.side=='SELL')} | short_call {next(l.strike for l in ic.legs if l.option_type=='CALL' and l.side=='SELL')} | width {width:.0f} | credit {credit:.2f} | max_profit {max_profit:.2f} | max_loss {max_loss:.2f}"
                    )
                    entry_ic = ic
                    entry_bar = bar
                    entry_credit = ic.net_credit
        else:
            # manage/exit
            should_exit = False
            if exit_window[0] <= now_hhmm <= exit_window[1]:
                should_exit = True
            # price updated exit value
            iv_use = float(bar.iv) if bar.iv is not None else 0.18
            # Compute buyback debit (positive): shorts are bought back (debit += p), longs are sold (debit -= p)
            buyback_debit = 0.0
            for leg in entry_ic.legs:
                p = black_scholes(
                    bar.close, leg.strike, expiry_t_from_days(max(min_dte - 1, 0)), r, iv_use, leg.option_type
                )
                buyback_debit += p if leg.side == "SELL" else -p
            target_buyback = entry_credit * (1 - float(cfg.get("risk.take_profit_pct", 50.0)) / 100.0)
            stop_buyback = entry_credit * (1 + float(cfg.get("risk.stop_loss_pct", 100.0)) / 100.0)
            if buyback_debit <= target_buyback:
                should_exit = True
            if buyback_debit >= stop_buyback:
                should_exit = True

            if should_exit and entry_bar is not None:
                pnl = entry_credit - buyback_debit
                trades.append(
                    TradeResult(
                        entry_time=entry_bar.ts.to_pydatetime(),
                        exit_time=bar.ts.to_pydatetime(),
                        net_credit_per_unit=entry_credit,
                        net_exit_per_unit=buyback_debit,
                        pnl_per_unit=pnl,
                    )
                )
                log.info(f"Exit IC at {bar.ts} pnl {pnl:.2f}")
                entry_ic = None
                entry_bar = None
                entry_credit = 0.0

    # Summary
    if not trades:
        log.info("No trades generated.")
    total = sum(t.pnl_per_unit for t in trades) * lot
    log.info(f"Backtest trades: {len(trades)}, total PnL (per lot): {total:.2f} INR")


def run_live(cfg: Config, force_dry_run: bool = False) -> None:
    setup_logging()
    dry = bool(cfg.get("execution.dry_run", True)) or force_dry_run
    broker_name = str(cfg.get("execution.broker", "paper")).lower()
    broker = None
    if dry or broker_name == "paper":
        broker = PaperBroker(
            slippage_bps=float(cfg.get("execution.slippage_bps", 2.0)),
            commission_per_lot=float(cfg.get("backtest.commission_per_lot", 40.0)),
        )
        log.info("Live loop (paper broker). No real orders will be placed.")
    elif broker_name == "kite":
        broker = KiteBroker()
        log.info("Live loop with Zerodha Kite broker initialized.")
    else:
        log.warning(f"Unknown broker '{broker_name}', falling back to paper broker.")
        broker = PaperBroker()

    # Build a single IC from current market context
    now = datetime.now(timezone.utc)
    lot = int(cfg.get("instrument.lot_size", 75))
    step = float(cfg.get("instrument.strike_step", 50))
    target_delta = float(cfg.get("strategy.target_delta", 0.15))
    wing = float(cfg.get("strategy.wing_width_points", 400))
    min_credit = float(cfg.get("strategy.min_credit_per_ic", 1))
    target_distance = float(cfg.get("strategy.target_distance_points", 300))
    r = float(cfg.get("backtest.risk_free_rate", 0.06))
    min_dte = int(cfg.get("strategy.min_days_to_expiry", 2))

    # Market hours guard
    wd_cfg = cfg.get("market.weekdays", None)
    wd_map = {"MON":0, "TUE":1, "WED":2, "THU":3, "FRI":4, "SAT":5, "SUN":6}
    if isinstance(wd_cfg, (list, tuple)):
        days: set[int] = set()
        for w in wd_cfg:
            if isinstance(w, int):
                days.add(int(w))
            else:
                days.add(wd_map.get(str(w).upper(), 0))
    else:
        days = None

    mh = MarketHours(
        tz=str(cfg.get("timezone", "Asia/Kolkata")),
        open_time=str(cfg.get("market.open", "09:15")),
        close_time=str(cfg.get("market.close", "15:30")),
        holidays=set(cfg.get("market.holidays", []) or []),
        weekdays=days,
    )
    if not mh.is_open(now):
        log.info("Market is closed (per config). Exiting live cycle.")
        return

    # Determine expiry and spot/iv - using only Zerodha Kite
    kite_data = None
    try:
        kite_data = KiteBroker()
        log.info("KiteBroker initialized for live data fetching")
    except Exception as e:
        log.error(f"Failed to initialize KiteBroker: {e}")
        return

    expiry_dt = None
    spot = None
    sigma = None
    vix_val = None

    # Fetch all data from Kite only
    rl = RateLimiter(min_interval_s=float(cfg.get("execution.api_min_interval_s", 0.25)))
    instruments = load_instruments(kite_data.kite)
    underlying = str(cfg.get("instrument.underlying_symbol_zerodha", "NSE:NIFTY 50"))
    vix_symbol = str(cfg.get("data_sources.vix_symbol_kite", "NSE:INDIA VIX"))

    # 1. Fetch spot price from Kite
    try:
        spot = float(ltp_dict(kite_data.kite, [underlying]).get(underlying))
        log.info(f"Kite spot price: {spot}")
    except Exception as e:
        log.error(f"Failed to fetch spot from Kite: {e}")
        return
    rl.wait()

    # 2. Fetch VIX from Kite
    try:
        vix_val = float(ltp_dict(kite_data.kite, [vix_symbol]).get(vix_symbol))
        log.info(f"Kite VIX: {vix_val}")
    except Exception as e:
        log.warning(f"Failed to fetch VIX from Kite: {e}")
        vix_val = None
    rl.wait()

    # 3. Determine expiry date
    weekday = str(cfg.get("instrument.weekly_expiry_weekday", "TUE"))
    expiry_dt = next_weekly_expiry(now, weekday=weekday)
    log.info(f"Calculated expiry date: {expiry_dt.strftime('%d-%b-%Y')}")

    # 4. Fetch options chain and calculate IV from Kite
    if spot is not None and expiry_dt is not None:
        try:
            chain = filter_chain(instruments, underlying_name=str(cfg.get("instrument.symbol", "NIFTY")), expiry_date=expiry_dt)
            sigma_default = float(cfg.get("strategy.iv_assumption", cfg.get("demo.iv", 0.18)))
            points = build_chain_points(kite_data.kite, chain, spot=spot, t_years=max(1/252, (expiry_dt - now).days/365), r=r)
            ivs = [p.iv for p in points if p.iv is not None]
            sigma = float(np.median(np.array(ivs))) if ivs else sigma_default
            log.info(f"Calculated IV (median): {sigma:.4f} from {len(ivs)} points")
        except Exception as e:
            log.warning(f"Failed to calculate IV from Kite chain: {e}")
            sigma = float(cfg.get("strategy.iv_assumption", cfg.get("demo.iv", 0.18)))
            log.info(f"Using fallback IV: {sigma}")

    # Abort if still missing essentials
    if spot is None or expiry_dt is None:
        log.error("Live data unavailable (spot/expiry). Aborting trading cycle.")
        return

    # Track spot for staleness detection
    global _prev_spot
    if _prev_spot is not None and abs(float(spot) - float(_prev_spot)) < 1e-9:
        log.warning("Spot equals previous value; re-fetching to verify data freshness.")
        try:
            rl.wait()
            spot_retry = float(ltp_dict(kite_data.kite, [underlying]).get(underlying))
            if spot_retry and abs(spot_retry - spot) > 1e-9:
                spot = spot_retry
                log.info(f"Spot refreshed: {spot}")
            else:
                log.warning("Spot unchanged after retry - continuing with current value")
        except Exception as e:
            log.warning(f"Failed to refresh spot: {e} - continuing with current value")
    _prev_spot = float(spot)

    # Finalize time to expiry
    t_years = max(0.001, (expiry_dt - now).total_seconds() / (365.0 * 24 * 3600))
    if sigma is None:
        sigma = float(cfg.get("strategy.iv_assumption", cfg.get("demo.iv", 0.18)))

    # Dynamic width via VIX
    def dynamic_width(vix: Optional[float]) -> float:
        if vix is None:
            return wing
        if vix < 15:
            return 300.0
        elif vix < 25:
            return 400.0
        else:
            return 500.0

    wing = dynamic_width(vix_val)

    # Plan: scan OTM distances to hit target credit while obeying max loss
    target_credit_points = float(cfg.get("strategy.target_credit_points", 90))
    max_loss_limit = float(cfg.get("strategy.max_loss_limit", 30000))

    best_ic = None
    best_err = 1e9
    for dist in range(int(cfg.get("strategy.min_otm_distance", 200)), int(cfg.get("strategy.max_otm_distance", 500)) + 1, int(step)):
        cand = build_iron_condor_balanced(
            spot=spot,
            lot_size=lot,
            step=step,
            params=ICParams(target_delta=target_delta, wing_width_points=wing, min_credit_per_ic=min_credit),
            target_distance=float(dist),
            price_fn=black_scholes,
            expiry_t=t_years,
            r=r,
            iv=sigma,
        )
        if not cand.legs:
            continue
        credit_c = cand.net_credit
        width_c = wing
        max_loss_c = max(0.0, (width_c - credit_c)) * lot
        if max_loss_c > max_loss_limit:
            continue
        err = abs(credit_c - target_credit_points)
        if err < best_err:
            best_err = err
            best_ic = cand

    ic = best_ic or build_iron_condor_balanced(
        spot=spot,
        lot_size=lot,
        step=step,
        params=ICParams(target_delta=target_delta, wing_width_points=wing, min_credit_per_ic=min_credit),
        target_distance=target_distance,
        price_fn=black_scholes,
        expiry_t=t_years,
        r=r,
        iv=sigma,
    )
    ok, reasons = validate_balanced_ic(
        spot,
        ic,
        ICConstraints(
            min_otm_distance=float(cfg.get("strategy.min_otm_distance", 200)),
            max_otm_distance=float(cfg.get("strategy.max_otm_distance", 500)),
            require_equal_wings=True,
            required_lot_size=lot,
        ),
        lot,
    )
    if not ok:
        log.warning(f"IC validation failed: {', '.join(reasons)}")
        return
    width = wing
    credit = ic.net_credit
    max_profit = credit * lot
    max_loss = max(0.0, (width - credit)) * lot
    # Approximate probability the spot ends between short strikes
    try:
        from math import log as _ln, sqrt as _sqrt, erf as _erf
        sp_k = next(l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='PUT')
        sc_k = next(l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='CALL')
        mu = (r - 0.5 * sigma * sigma) * t_years
        sigt = sigma * _sqrt(t_years)
        cdf = lambda z: 0.5 * (1.0 + _erf(z / _sqrt(2.0)))
        z_lo = (_ln(sp_k / spot) - mu) / sigt
        z_hi = (_ln(sc_k / spot) - mu) / sigt
        prob_between = max(0.0, min(1.0, cdf(z_hi) - cdf(z_lo)))
    except Exception:
        prob_between = None

    # Enhanced snapshot
    log.info("Live Market Data:")
    log.info(f"- Spot: {spot:.2f}")
    log.info(f"- VIX: {vix_val:.2f}" if vix_val is not None else "- VIX: n/a")
    log.info(f"- Days to expiry: {max(0, int(t_years*365))}")
    log.info(f"- Working IV (median): {sigma:.3f}")
    log.info("Recommended Iron Condor:")
    log.info(f"Short Put: {next(l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='PUT')}")
    log.info(f"Short Call: {next(l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='CALL')}")
    log.info(f"Spread Width: {width:.0f} points")
    log.info(f"Expected Credit: {credit:.2f} points")
    log.info(f"Max Profit: {max_profit:.2f} | Max Loss: {max_loss:.2f}")
    if prob_between is not None:
        log.info(f"Probability of Profit: {prob_between*100:.0f}%")
    if not ic.legs:
        log.info("No eligible IC to place (min credit filter).")
        return

    # Resolve tradingsymbols from instruments if available; else fallback to format
    symbol_root = str(cfg.get("instrument.symbol", "NIFTY"))
    year2 = expiry_dt.strftime("%y")
    mon3 = expiry_dt.strftime("%b").upper()
    day2 = expiry_dt.strftime("%d")

    def fallback_ts(strike: float, opt_type: str) -> str:
        return f"NFO:{symbol_root}{year2}{mon3}{int(strike)}{'CE' if opt_type=='CALL' else 'PE'}"

    def resolve_ts(strike: float, opt_type: str) -> str:
        if isinstance(broker, KiteBroker) and not dry and chain:
            inst = nearest_by_strike(chain, strike, opt_type)
            if inst:
                return f"{inst.exchange}:{inst.tradingsymbol}"
        return fallback_ts(strike, opt_type)

    orders: list[Order] = []
    for leg in ic.legs:
        ts = resolve_ts(leg.strike, leg.option_type)
        side = "BUY" if leg.side == "BUY" else "SELL"
        orders.append(Order(
            symbol=ts,
            expiry=now.strftime("%Y-%m-%d"),
            strike=float(leg.strike),
            option_type=leg.option_type,
            side=side,
            qty=int(leg.qty),
            price=float(leg.price),
        ))

    for o in orders:
        log.info(f"Order: {o.side} {o.qty} {o.symbol} @ {o.price:.2f}")

    if isinstance(broker, PaperBroker):
        broker.place_orders(orders)
        log.info("Simulated order placement with paper broker.")
        # Mark state as active, then immediately flat (paper mode) to enable re-entry in loop
        st = _load_state()
        st["position"] = "active"
        st["last_entry_ts"] = now.isoformat()
        _save_state(st)
        # Send entry alert (paper)
        try:
            nf = _get_notifier(cfg)
            if nf is not None and ic.legs:
                sp = next(l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='PUT')
                sc = next(l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='CALL')
                width = float(cfg.get("strategy.wing_width_points", 400))
                data = {
                    'time_str': now.astimezone().strftime('%I:%M %p'),
                    'spot': spot,
                    'short_put': sp,
                    'long_put': sp - width,
                    'short_call': sc,
                    'long_call': sc + width,
                    'credit_rupees': ic.net_credit * lot,
                    'credit_pts': ic.net_credit,
                    'target_rupees': ic.net_credit * lot * 0.5,
                    'sl_rupees': ic.net_credit * lot * 1.0,
                    'cooldown': int(cfg.get("execution.cooldown_minutes", 0)),
                }
                nf.send_immediate_alert('entry', data)
        except Exception:
            pass
        st["position"] = "flat"
        st["last_exit_ts"] = datetime.now(timezone.utc).isoformat()
        _save_state(st)
    else:
        # Liquidity check via kite.quote (OI and volume)
        min_oi = int(cfg.get("liquidity.min_oi", 1000))
        min_vol = int(cfg.get("liquidity.min_volume", 100))
        try:
            qd = quote_dict(broker.kite, [o.symbol for o in orders])
            for sym, q in qd.items():
                oi = q.get('oi') or 0
                vol = q.get('volume') or 0
                if (isinstance(oi, (int, float)) and oi < min_oi) or (isinstance(vol, (int, float)) and vol < min_vol):
                    log.warning(f"Liquidity insufficient for {sym}: OI={oi}, Vol={vol}")
                    log.warning("Aborting live placement due to liquidity checks.")
                    return
        except Exception as e:
            log.warning(f"Liquidity check skipped due to error: {e}")
        log.info("Placing LIMIT orders with Zerodha Kite.")
        broker.place_orders(orders)
        log.info("Orders sent to broker. Starting simple monitor for TP/SL.")
        # Mark state active
        st = _load_state()
        st["position"] = "active"
        st["last_entry_ts"] = now.isoformat()
        _save_state(st)

        # Simple monitor loop: close when net exit value crosses thresholds
        take_pct = float(cfg.get("risk.take_profit_pct", 50.0))
        stop_pct = float(cfg.get("risk.stop_loss_pct", 100.0))
        entry_credit = ic.net_credit
        target_buyback = entry_credit * (1.0 - take_pct / 100.0)
        stop_buyback = entry_credit * (1.0 + stop_pct / 100.0)

        syms = [o.symbol for o in orders]
        max_secs = int(cfg.get("execution.monitor_seconds", 120))
        poll = float(cfg.get("execution.monitor_poll_seconds", 2.0))
        start = time.time()
        while time.time() - start < max_secs:
            try:
                ltps = ltp_dict(broker.kite, syms)
                # Revalue the condor
                net = 0.0
                for o in orders:
                    p = ltps.get(o.symbol)
                    if p is None:
                        continue
                    # For short legs (SELL), buyback price adds to exit; for long legs, we sell to close
                    sign = 1.0 if o.side == "SELL" else -1.0
                    net += sign * p
                # net represents approximate buyback debit (positive means pay to close shorts, receive for longs)
                if net <= target_buyback:
                    log.info(f"Hit TP: buyback {net:.2f} <= {target_buyback:.2f}. Closing.")
                    break
                if net >= stop_buyback:
                    log.info(f"Hit SL: buyback {net:.2f} >= {stop_buyback:.2f}. Closing.")
                    break
            except Exception as e:
                log.warning(f"Monitor error: {e}")
            time.sleep(poll)

        # Place offsetting orders (marketable by using limit near LTP)
        try:
            ltps = ltp_dict(broker.kite, syms)
        except Exception:
            ltps = {}
        close_orders: list[Order] = []
        for o in orders:
            lp = float(ltps.get(o.symbol, o.price))
            if o.side == "SELL":  # short -> buy back
                px = lp * 1.02  # be more aggressive to fill
                close_orders.append(Order(symbol=o.symbol, expiry=o.expiry, strike=o.strike, option_type=o.option_type, side="BUY", qty=o.qty, price=px))
            else:  # long -> sell
                px = max(0.05, lp * 0.98)
                close_orders.append(Order(symbol=o.symbol, expiry=o.expiry, strike=o.strike, option_type=o.option_type, side="SELL", qty=o.qty, price=px))
        broker.place_orders(close_orders)
        log.info("Close orders sent to broker.")
        # Mark state flat
        st = _load_state()
        st["position"] = "flat"
        st["last_exit_ts"] = datetime.now(timezone.utc).isoformat()
        _save_state(st)
        # Send exit alert (Kite)
        try:
            nf = _get_notifier(cfg)
            if nf is not None:
                # Approx fields from context
                entry_rupees = entry_credit * lot
                # Estimate exit debit using latest ltps
                try:
                    ltps = ltp_dict(broker.kite, syms)
                    exit_debit = sum((ltps.get(o.symbol, o.price)) for o in orders if o.side == 'SELL') \
                                  - sum((ltps.get(o.symbol, o.price)) for o in orders if o.side == 'BUY')
                except Exception:
                    exit_debit = entry_rupees * 0.5
                pnl_rupees = entry_rupees - exit_debit
                pnl_pct = (pnl_rupees / entry_rupees * 100.0) if entry_rupees else 0.0
                # Persist trade record for summaries
                try:
                    tzname = str(cfg.get("timezone", "Asia/Kolkata"))
                    try:
                        from zoneinfo import ZoneInfo
                        local_dt = datetime.now(timezone.utc).astimezone(ZoneInfo(tzname))
                    except Exception:
                        local_dt = datetime.now()
                    date_local = local_dt.strftime('%Y-%m-%d')
                    # Strikes from built IC if available
                    sp = next((l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='PUT'), None)
                    sc = next((l.strike for l in ic.legs if l.side=='SELL' and l.option_type=='CALL'), None)
                    width = float(cfg.get("strategy.wing_width_points", 400))
                    trec = {
                        "date_local": date_local,
                        "entry_ts": st.get("last_entry_ts"),
                        "exit_ts": st.get("last_exit_ts"),
                        "entry_rupees": entry_rupees,
                        "exit_rupees": exit_debit,
                        "pnl_rupees": pnl_rupees,
                        "pnl_pct": pnl_pct,
                        "short_put": sp,
                        "short_call": sc,
                        "width": width,
                        "lots": lot,
                    }
                    _append_trade(trec)
                except Exception:
                    pass
                data = {
                    'time_str': datetime.now().astimezone().strftime('%I:%M %p'),
                    'duration': 'n/a',
                    'entry_rupees': entry_rupees,
                    'exit_rupees': exit_debit,
                    'pnl_rupees': pnl_rupees,
                    'pnl_pct': pnl_pct,
                    'reason': 'Target/SL/Time',
                    'next_ready': 'after cooldown',
                }
                nf.send_immediate_alert('exit', data)
        except Exception:
            pass


def run_live_loop(cfg: Config, interval_seconds: int = 60) -> None:
    """Continuously scan and (re)enter when flat, during market hours.

    - Respects market hours from config
    - After an exit, immediately resumes scanning
    - Sleeps `interval_seconds` between scans
    """
    setup_logging()
    mh = MarketHours(
        tz=str(cfg.get("timezone", "Asia/Kolkata")),
        open_time=str(cfg.get("market.open", "09:15")),
        close_time=str(cfg.get("market.close", "15:30")),
        holidays=set(cfg.get("market.holidays", []) or []),
        weekdays=None,
    )
    log.info("Starting continuous live loop scanner.")
    while True:
        now = datetime.now(timezone.utc)
        if not mh.is_open(now):
            nxt = mh.next_open(now)
            wait = max(5, int((nxt - now).total_seconds()))
            log.info(f"Market closed. Sleeping until next open at {nxt}.")
            time.sleep(min(wait, 3600))
            continue
        state = _load_state()

        # Enforce daily trade cap
        today = now.date().isoformat()
        trades_today_date = state.get("trades_today_date")
        if trades_today_date != today:
            state["trades_today_date"] = today
            state["trades_today_count"] = 0
            _save_state(state)
        max_trades = int(cfg.get("execution.max_trades_per_day", 10))

        # Enforce cooldown after last exit
        cooldown_min = int(cfg.get("execution.cooldown_minutes", 0))
        if state.get("position") == "flat":
            if state.get("trades_today_count", 0) >= max_trades:
                log.info(f"Daily trade limit reached ({state.get('trades_today_count')} >= {max_trades}). Skipping.")
            else:
                in_cooldown = False
                let = state.get("last_exit_ts")
                if let and cooldown_min > 0:
                    try:
                        last_exit = datetime.fromisoformat(let)
                        elapsed = (now - last_exit).total_seconds() / 60.0
                        if elapsed < cooldown_min:
                            in_cooldown = True
                            log.info(f"In cooldown ({elapsed:.1f} < {cooldown_min} min). Skipping entry.")
                    except Exception:
                        pass
                if not in_cooldown:
                    try:
                        prev_entry = state.get("last_entry_ts")
                        # Force dry-run flag from CLI/config remains respected within run_live
                        run_live(cfg, force_dry_run=bool(cfg.get("execution.dry_run", True)))
                        # If an entry happened, last_entry_ts will change; count a trade
                        new_state = _load_state()
                        if new_state.get("last_entry_ts") and new_state.get("last_entry_ts") != prev_entry:
                            new_state["trades_today_count"] = int(new_state.get("trades_today_count", 0)) + 1
                            new_state["trades_today_date"] = today
                            _save_state(new_state)
                    except Exception as e:
                        log.warning(f"live-loop iteration failed: {e}")
        else:
            log.info("Position active; skipping entry this iteration.")
        time.sleep(max(5, int(interval_seconds)))

