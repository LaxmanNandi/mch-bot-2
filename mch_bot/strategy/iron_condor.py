from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ICParams:
    target_delta: float
    wing_width_points: float
    min_credit_per_ic: float


@dataclass
class ICConstraints:
    min_otm_distance: float = 200
    max_otm_distance: float = 500
    require_equal_wings: bool = True
    required_lot_size: int | None = 75


@dataclass
class Leg:
    strike: float
    option_type: str  # CALL or PUT
    side: str         # SELL or BUY
    qty: int
    price: float


@dataclass
class IronCondor:
    legs: List[Leg]

    @property
    def net_credit(self) -> float:
        credit = 0.0
        for leg in self.legs:
            signed = -leg.price if leg.side == "BUY" else leg.price
            credit += signed
        return credit


def pick_strikes_by_delta(spot: float, step: float, target_delta: float) -> Tuple[float, float]:
    # Placeholder: choose strikes at symmetric distance based on a naive mapping from delta
    # For demo, assume ~ delta 0.15 corresponds to ~1.0 std dev; approximate with 2% of spot
    distance = spot * 0.02 if target_delta <= 0.15 else spot * 0.015
    # Round to nearest step
    def round_to(x: float, step: float) -> float:
        return round(x / step) * step
    call_strike = round_to(spot + distance, step)
    put_strike = round_to(spot - distance, step)
    return put_strike, call_strike


def select_balanced_strikes_by_distance(
    spot: float,
    step: float,
    target_distance: float,
    wing_width: float,
) -> Tuple[float, float, float, float]:
    # Ensure target distance positive and wings equal
    if target_distance <= 0:
        target_distance = step
    if wing_width <= 0:
        wing_width = step * 2

    def round_to_down(x: float, step: float) -> float:
        return (int(x // step)) * step

    def round_to_up(x: float, step: float) -> float:
        return (int((x + step - 1) // step)) * step

    short_put = round_to_down(spot - target_distance, step)
    short_call = round_to_up(spot + target_distance, step)
    long_put = short_put - wing_width
    long_call = short_call + wing_width
    return float(short_put), float(long_put), float(short_call), float(long_call)


def validate_balanced_ic(
    spot: float,
    ic: IronCondor,
    constraints: ICConstraints,
    lot_size: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if constraints.required_lot_size is not None and lot_size != constraints.required_lot_size:
        reasons.append(f"Lot size {lot_size} != required {constraints.required_lot_size}")

    if not ic.legs or len(ic.legs) != 4:
        reasons.append("IC must have exactly 4 legs")
        return False, reasons

    # Extract strikes
    sp = next((l.strike for l in ic.legs if l.option_type == "PUT" and l.side == "SELL"), None)
    sc = next((l.strike for l in ic.legs if l.option_type == "CALL" and l.side == "SELL"), None)
    lp = next((l.strike for l in ic.legs if l.option_type == "PUT" and l.side == "BUY"), None)
    lc = next((l.strike for l in ic.legs if l.option_type == "CALL" and l.side == "BUY"), None)

    if sp is None or sc is None or lp is None or lc is None:
        reasons.append("Missing one or more legs for IC validation")
        return False, reasons

    # Core constraints
    if not (sc > spot > sp):
        reasons.append(f"Require short_call({sc}) > spot({spot}) > short_put({sp})")

    width_put = sp - lp
    width_call = lc - sc
    if constraints.require_equal_wings and abs(width_put - width_call) > 1e-6:
        reasons.append(f"Wing widths unequal: put {width_put} vs call {width_call}")

    dist_put = spot - sp
    dist_call = sc - spot
    if abs(dist_put - dist_call) > max(1.0, 0.2 * min(dist_put, dist_call)):
        reasons.append(f"Unbalanced OTM distance: put {dist_put} vs call {dist_call}")

    # OTM distance constraints
    if not (constraints.min_otm_distance <= dist_put <= constraints.max_otm_distance):
        reasons.append(f"PUT distance {dist_put} outside [{constraints.min_otm_distance},{constraints.max_otm_distance}]")
    if not (constraints.min_otm_distance <= dist_call <= constraints.max_otm_distance):
        reasons.append(f"CALL distance {dist_call} outside [{constraints.min_otm_distance},{constraints.max_otm_distance}]")

    return (len(reasons) == 0), reasons


def build_iron_condor(
    spot: float,
    lot_size: int,
    step: float,
    params: ICParams,
    price_fn,
    expiry_t: float,
    r: float,
    iv: float,
) -> IronCondor:
    put_short, call_short = pick_strikes_by_delta(spot, step, params.target_delta)
    put_long = put_short - params.wing_width_points
    call_long = call_short + params.wing_width_points

    # Price legs using provided function (e.g., Black-Scholes)
    ps = price_fn(spot, put_short, expiry_t, r, iv, "PUT")
    pl = price_fn(spot, put_long, expiry_t, r, iv, "PUT")
    cs = price_fn(spot, call_short, expiry_t, r, iv, "CALL")
    cl = price_fn(spot, call_long, expiry_t, r, iv, "CALL")

    # Short credit condor: SELL short strikes, BUY wings
    legs = [
        Leg(strike=put_short, option_type="PUT", side="SELL", qty=lot_size, price=ps),
        Leg(strike=call_short, option_type="CALL", side="SELL", qty=lot_size, price=cs),
        Leg(strike=put_long, option_type="PUT", side="BUY", qty=lot_size, price=pl),
        Leg(strike=call_long, option_type="CALL", side="BUY", qty=lot_size, price=cl),
    ]
    ic = IronCondor(legs=legs)
    if ic.net_credit * lot_size < params.min_credit_per_ic:
        # Not attractive; return empty structure
        return IronCondor(legs=[])
    return ic


def build_iron_condor_balanced(
    spot: float,
    lot_size: int,
    step: float,
    params: ICParams,
    target_distance: float,
    price_fn,
    expiry_t: float,
    r: float,
    iv: float,
) -> IronCondor:
    sp, lp, sc, lc = select_balanced_strikes_by_distance(spot, step, target_distance, params.wing_width_points)

    ps = price_fn(spot, sp, expiry_t, r, iv, "PUT")
    pl = price_fn(spot, lp, expiry_t, r, iv, "PUT")
    cs = price_fn(spot, sc, expiry_t, r, iv, "CALL")
    cl = price_fn(spot, lc, expiry_t, r, iv, "CALL")

    legs = [
        Leg(strike=sp, option_type="PUT", side="SELL", qty=lot_size, price=ps),
        Leg(strike=sc, option_type="CALL", side="SELL", qty=lot_size, price=cs),
        Leg(strike=lp, option_type="PUT", side="BUY", qty=lot_size, price=pl),
        Leg(strike=lc, option_type="CALL", side="BUY", qty=lot_size, price=cl),
    ]
    ic = IronCondor(legs=legs)
    if ic.net_credit * lot_size < params.min_credit_per_ic:
        return IronCondor(legs=[])
    return ic

