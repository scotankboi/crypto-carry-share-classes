"""Hedged-book engine: long spot BTC (fully funded, held at a custodian) against short legs on one or
more venues (perpetuals, or dated futures rolled at expiry). Hourly, in USDT.

State per hour t:
    Q        spot BTC held long;  n_v  contracts short on leg v (1 contract = 1 BTC), sum_v n_v = Q
    E_v      margin equity on leg v (USDT);  cash  USDT outside the venues
    NAV      cash + Q * S_t + sum_v E_v

Each leg supplies, per hour: F_mtm (price at which the open position is marked at t), F (price going
forward; differs from F_mtm only when the leg rolls into a new contract at t), f (funding rate settled
at t, paid on the mark notional) and roll (the position is closed and re-opened at t).

The change in NAV splits exactly into three parts (checked every hour):
    funding      sum_v n_v * f_v,t * F_mtm_v,t
    convergence  sum_v n_v * [(F_v,t-1 - S_t-1) - (F_mtm_v,t - S_t)]      basis carried and released
    costs        spot and perp fees and half-spreads, delivery fees on rolls
A dated future earns its carry through convergence: its basis shrinks to zero at expiry.

Rebalancing resets every leg to n_v = w_v Q and E_v = n_v F_v / L, by trading spot and moving cash:
    weekly (scheduled) and whenever a leg's margin ratio E_v / (n_v F_v) leaves 1/L (1 +/- band),
    executed `lag` hours after the breach. A leg below maintenance margin at its intrahour high is
    flagged as a liquidation event.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class LegCosts:
    trade: float          # per unit of notional traded: taker fee + half spread
    roll: float = 0.0     # per unit of notional settled at a roll (delivery fee)


def _target_cost(Q_new: float, Q: float, n: dict, w: dict, S: float, F: dict, c_spot: float, legs: dict) -> float:
    return abs(Q_new - Q) * S * c_spot + sum(abs(w[v] * Q_new - n[v]) * F[v] * legs[v].trade for v in w)


def run(df: pd.DataFrame, legs: dict[str, LegCosts], weights: dict[str, float], *, leverage: float, band: float,
        maintenance: dict[str, float], capital: float, spot_cost: float, rebalance_due: pd.Series, lag: int = 1) -> pd.DataFrame:
    """df columns: S, and per leg v: F_mtm_<v>, F_<v>, f_<v>, roll_<v>, H_<v> (intrahour high of the held contract)."""
    target = 1.0 / leverage
    vs = list(weights)
    Q, cash = 0.0, capital
    n = dict.fromkeys(vs, 0.0)
    E = dict.fromkeys(vs, 0.0)
    rows, prev, pending = [], None, None
    arr = {c: df[c].to_numpy() for c in df.columns}
    due = rebalance_due.reindex(df.index, fill_value=False).to_numpy()
    for i, ts in enumerate(df.index):
        S = arr["S"][i]
        Fm = {v: arr[f"F_mtm_{v}"][i] for v in vs}
        F = {v: arr[f"F_{v}"][i] for v in vs}
        comp = {"funding": 0.0, "convergence": 0.0, "costs": 0.0}
        flags = []
        nav_before = cash + Q * (prev["S"] if prev else S) + sum(E.values())
        if prev is not None and Q > 0:
            for v in vs:
                comp["convergence"] += n[v] * ((prev["F"][v] - prev["S"]) - (Fm[v] - S))
                E[v] -= n[v] * (Fm[v] - prev["F"][v])
                fund = n[v] * arr[f"f_{v}"][i] * Fm[v]
                comp["funding"] += fund
                E[v] += fund
                if arr[f"roll_{v}"][i]:
                    c = n[v] * (Fm[v] * legs[v].roll + F[v] * legs[v].trade)
                    E[v] -= c
                    comp["costs"] -= c
                    flags.append(f"roll_{v}")
                hi = arr[f"H_{v}"][i]
                if E[v] - n[v] * (hi - Fm[v]) < maintenance[v] * n[v] * hi:
                    flags.append(f"liquidation_{v}")
                ratio = E[v] / (n[v] * F[v])
                if pending is None and not (target * (1 - band) <= ratio <= target * (1 + band)):
                    pending = i + lag
                    flags.append(f"breach_{v}")
        if i == 0 or due[i] or (pending is not None and i >= pending):
            nav = cash + Q * S + sum(E.values())
            denom = S + sum(weights[v] * F[v] * target for v in vs)
            Q_new = nav / denom
            for _ in range(4):
                Q_new = (nav - _target_cost(Q_new, Q, n, weights, S, F, spot_cost, legs)) / denom
            cost = _target_cost(Q_new, Q, n, weights, S, F, spot_cost, legs)
            Q = Q_new
            for v in vs:
                n[v] = weights[v] * Q
                E[v] = n[v] * F[v] * target
            cash = nav - cost - Q * S - sum(E.values())
            comp["costs"] -= cost
            flags.append("enter" if i == 0 else ("rebalance" if due[i] else "emergency"))
            pending = None
        nav = cash + Q * S + sum(E.values())
        rows.append({"ts": ts, "S": S, "Q": Q, "cash": cash, "nav": nav, **{f"E_{v}": E[v] for v in vs},
                     **{f"ratio_{v}": E[v] / (n[v] * F[v]) if n[v] > 0 else np.nan for v in vs},
                     **comp, "check": nav - nav_before - sum(comp.values()), "flags": ",".join(flags)})
        prev = {"S": S, "F": F}
    return pd.DataFrame(rows).set_index("ts")
