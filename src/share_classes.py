"""Share-class engine: one master strategy, several investors, each paid in their own currency.

All series are daily at the valuation hour (17:00 UTC: never earlier than New York noon, the time of
FRED's FX rates, in summer or winter). The master's NAV V_t is in
USDT, its native unit: a long-spot / short USDT-margined perp book is economically a USDT deposit plus
the carry. Gross class indices (before fees):

    USDT     G_t = V_t / V_0
    USD      G_t = (V_t p_t) / (V_0 p_0),  p = USD price of one USDT (peg risk is on the whole book)
    JPY, KRW currency-hedged: the class holds master units worth A_t USD and sells USD forward each
             month for the class currency (notional = the class's USD value at the roll). The forward
             is priced by covered interest parity with an optional cross-currency basis b,
                 F_t(T) / X_t = (1 + (i_ccy + b) tau_ccy) / (1 + i_USD tau_USD),
             and marked to market daily:  NAV_t = A_t X_t + N (K - F_t(T)) / (1 + i_ccy tau_ccy).
             At each roll the forward's value is settled into master units and a new one is struck.
             The hedge costs roughly i_USD - i_ccy - b a year; intramonth P&L stays unhedged.
    BTC      BTC-hedged: the class keeps a long BTC position equal to its NAV in BTC, rebalanced daily,
             in a perpetual (paying its funding) or a quarterly future (paying its basis as it rolls
             down), with a share m of NAV set aside as margin for it (not invested in the master):
                 W_t = A_t + C_t (USD),  C_t += h * hedge P&L per BTC,  NAV_t = W_t / S_t
             Either way the long hedge pays the price of BTC leverage, the same carry the master earns.
             Base case: the hedge margin is held in USDT and the hedge is a separate long position, not
             netted against the master's short. Two alternatives:
               coin-margined  (margin_in_btc) the margin m is held in BTC, so it is itself long BTC and
                              the hedge covers only the (1 - m) invested:  r_BTC ~ (1 - m)(r - f)
               netted         (margin_share = 0) the whole NAV is in the master and the class's long is
                              netted against the master's short on the same accounts, so no separate
                              margin is needed:  r_BTC ~ r - f ~ -f / (L + 1) - costs

Fees (per class, in the class currency): a management fee accrued daily (ACT/365) and a performance
fee on gains above the high-water mark, accrued daily as a liability and crystallised at quarter
ends. Each class is modelled as a single investor with no flows, so no equalisation is needed.
"""
import numpy as np
import pandas as pd


def usdt_usd_known_by_nav(candles: pd.DataFrame) -> pd.Series:
    """USDT-USD price to use for each day's NAV, from daily candles (open_time, close). A candle opened at
    00:00 UTC on day d closes at 24:00, after day d's NAV hour, so its close is first used on day d + 1."""
    s = pd.Series(candles["close"].to_numpy(), index=candles["open_time"].dt.tz_localize(None).dt.normalize())
    s.index = s.index + pd.Timedelta(days=1)
    return s


def usd_index(master_usdt: pd.Series, usdt_usd: pd.Series) -> pd.Series:
    p = usdt_usd.reindex(master_usdt.index).ffill().fillna(1.0)
    v = master_usdt * p
    return v / v.iloc[0]


def hedged_class(usd_idx: pd.Series, fx: pd.Series, i_usd: pd.Series, i_ccy: pd.Series, basis: float,
                 ccy_days: float = 365.0) -> pd.DataFrame:
    """Currency-hedged class (class currency per USD = fx). Rates as decimals; basis as a decimal."""
    idx = usd_idx.index
    X = fx.reindex(idx).ffill().bfill().to_numpy()
    iu = i_usd.reindex(idx).ffill().bfill().to_numpy()
    ic = i_ccy.reindex(idx).ffill().bfill().to_numpy()
    g = usd_idx.to_numpy()
    month = idx.to_period("M")
    roll = np.r_[True, month[1:] != month[:-1]]
    roll_dates = idx[roll]
    next_roll = pd.Series(roll_dates[1:].append(pd.DatetimeIndex([idx[-1] + pd.Timedelta(days=31)])), index=roll_dates)
    A = None
    rows = []
    N = K = T = None
    for i, t in enumerate(idx):
        if i == 0:
            A = 1.0 / X[0]                       # one unit of class currency invested
        else:
            A *= g[i] / g[i - 1]
        mtm = 0.0
        if N is not None:
            days = max((T - t).days, 0)
            fwd = X[i] * (1 + (ic[i] + basis) * days / ccy_days) / (1 + iu[i] * days / 360)
            mtm = N * (K - fwd) / (1 + ic[i] * days / ccy_days)
        nav = A * X[i] + mtm
        settled = 0.0
        if roll[i]:
            A += mtm / X[i]                      # settle the expiring forward into master units
            settled, mtm = mtm, 0.0
            T = next_roll[t]
            days = (T - t).days
            N = A                                # hedge the class's whole USD value
            K = X[i] * (1 + (ic[i] + basis) * days / ccy_days) / (1 + iu[i] * days / 360)
            nav = A * X[i]
        rows.append({"date": t, "nav": nav, "usd_assets": A, "fwd_mtm": mtm, "settled": settled, "fx": X[i],
                     "carry_points_ann": (iu[i] - ic[i] - basis)})
    out = pd.DataFrame(rows).set_index("date")
    out["index"] = out["nav"] / out["nav"].iloc[0]
    return out


def hedge_pnl_per_btc(frame: pd.DataFrame, leg: str, hour: int) -> pd.Series:
    """Daily P&L of a long 1-BTC position in a hedge instrument, summed over the hours between two
    valuation times: mark-to-market on the contract held, minus funding paid (perpetuals); a dated
    future settles to spot at expiry and the next one is entered at its own price (no P&L at the roll)."""
    F, Fm, f = frame[f"F_{leg}"], frame[f"F_mtm_{leg}"], frame[f"f_{leg}"]
    pnl = (Fm - F.shift(1)) - Fm * f
    day = (pnl.index - pd.Timedelta(hours=hour)).ceil("D").tz_localize(None)
    return pnl.iloc[1:].groupby(day[1:]).sum()


def btc_class(usd_idx: pd.Series, btc_usd: pd.Series, hedge_pnl: pd.Series, margin_share: float,
              trade_cost: float, margin_in_btc: bool = False) -> pd.DataFrame:
    """BTC-hedged class. hedge_pnl: daily P&L of a long 1-BTC hedge position (hedge_pnl_per_btc).
    margin_in_btc: the hedge margin is held in BTC (coin-margined), so only the part of NAV invested in
    the master (A) is hedged; otherwise the hedge covers the whole NAV (W)."""
    idx = usd_idx.index
    S = btc_usd.reindex(idx).ffill().to_numpy()
    hp = hedge_pnl.reindex(idx).fillna(0.0).to_numpy()
    g = usd_idx.to_numpy()
    W = S[0]                                     # one BTC worth of USD
    C = margin_share * W
    A = W - C
    h = (A if margin_in_btc else W) / S[0]
    rows = []
    for i, t in enumerate(idx):
        pnl = cost = 0.0
        if i > 0:
            A *= g[i] / g[i - 1]
            if margin_in_btc:
                C *= S[i] / S[i - 1]             # BTC held as margin moves with BTC
            pnl = h * hp[i]
            C += pnl
            W = A + C
            h_new = ((1 - margin_share) * W if margin_in_btc else W) / S[i]
            cost = abs(h_new - h) * S[i] * trade_cost
            W -= cost
            C = margin_share * W
            A = W - C
            h = (A if margin_in_btc else W) / S[i]
        rows.append({"date": t, "nav_btc": W / S[i], "usd_value": W, "hedge_pnl": pnl, "cost": cost, "btc_usd": S[i],
                     "margin_shortfall": C < 0})
    out = pd.DataFrame(rows).set_index("date")
    out["index"] = out["nav_btc"] / out["nav_btc"].iloc[0]
    return out


def apply_fees(gross_index: pd.Series, mgmt: float, perf: float, start_nav: float = 100.0) -> pd.DataFrame:
    """Net NAV per share from a gross index. Management fee accrued daily (ACT/365) on assets;
    performance fee accrued daily on gains above the high-water mark and crystallised at quarter ends."""
    idx = gross_index.index
    r = gross_index.pct_change().fillna(0.0).to_numpy()
    days = np.r_[0, np.diff(idx.to_numpy()).astype("timedelta64[D]").astype(float)]
    q = idx.to_period("Q")
    crystallise = np.r_[q[1:] != q[:-1], True]           # last valuation day of each quarter
    B, hwm = start_nav, start_nav
    rows = []
    for i, t in enumerate(idx):
        mg = 0.0
        if i > 0:
            mg = B * mgmt * days[i] / 365
            B = B * (1 + r[i]) - mg
        accrued = perf * max(0.0, B - hwm)
        paid = 0.0
        if crystallise[i] and i > 0 and accrued > 0:
            paid, B, accrued = accrued, B - accrued, 0.0
            hwm = B
        rows.append({"date": t, "nav": B - accrued, "assets": B, "mgmt_fee": mg, "perf_accrued": accrued,
                     "perf_paid": paid, "hwm": hwm})
    return pd.DataFrame(rows).set_index("date")
