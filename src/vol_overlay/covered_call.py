"""BTC-denominated covered calls: hold 1 BTC and sell one monthly call against it each month.

At 08:00 UTC on each monthly expiry (the last Friday) the expiring call settles and a call on the next
monthly expiry is sold. The monthly return in BTC is
    R_m = premium - fee - max(S_T - K, 0) / S_T - settlement fee
with S_T the Deribit delivery price (the index's 08:00 average) on the expiry date.

The forward. Deribit quotes implied volatility against each expiry's forward, so options are priced
with the forward as the underlying (options.py), and no Deribit futures history is collected. For each
roll window and expiry, the forward is taken as a ratio to the index, F / S:
  * put-call parity (primary): F = K / (1 - (c - p)) for each call and put traded at the same strike
    within 5 minutes of each other, near the money (|ln(K / S)| < 0.1), divided by their mean index
    price; the window's ratio is the median, used when there are at least 5 such pairs;
  * otherwise, the median over near-the-money trades (forward delta 0.15-0.85, price >= 0.005 BTC) of
    the forward at which Black-76 at the trade's quoted IV reproduces its price.
The forward at the roll is the delivery price S0 times that ratio. Repricing every front-month trade
at its own IV with this forward is the check (vol_overlay/results.json, "forward").

Premium from trades: among calls on the target expiry traded within +/- the window of the roll, take
the strike whose median forward delta is closest to the target (and within max_delta_miss), and price
it at the roll's forward with the median implied volatility of its trades. It is sold below that
price by vega x the half-spread. Fallback when no strike qualifies: Black-76 at DVOL + skew, with
the strike solved from the target delta. Both are computed every month so they can be compared.

Calibration (`calibrate`): from all front-month trades in the roll windows, per delta bucket,
    half-spread = median distance of taker sells below Deribit's mark price, in vol points
    skew        = median (trade implied volatility - DVOL at the roll), in vol points
"""
import numpy as np
import pandas as pd

from ..carry import last_friday
from . import options as bs


def roll_times(first: str, last: str, hour: int) -> list[pd.Timestamp]:
    return [(last_friday(m.year, m.month) + pd.Timedelta(hours=hour)).tz_localize("UTC")
            for m in pd.period_range(first[:7], last[:7], freq="M")]


PARITY_MINUTES, PARITY_MIN_PAIRS, NEAR_MONEY_LOG = 5, 5, 0.1


def _expiry_strike_cp(trades: pd.DataFrame) -> pd.DataFrame:
    p = trades["instrument_name"].str.split("-", expand=True)
    out = trades.copy()
    out["expiry"] = pd.to_datetime(p[1], format="%d%b%y").dt.tz_localize("UTC") + pd.Timedelta(hours=8)
    out["strike"] = p[2].astype(float)
    out["cp"] = p[3]
    out["T"] = (out["expiry"] - out["timestamp"]).dt.total_seconds() / (365.25 * 86400)
    return out


def window_forwards(t: pd.DataFrame) -> pd.DataFrame:
    """Forward / index ratio per (roll, expiry): put-call parity when there are enough pairs, else the
    median IV-implied forward of near-the-money trades (module docstring)."""
    keys = ["roll", "expiry"]
    q = t[(t["iv"] > 0) & (t["T"] > 1 / 365)].sort_values("timestamp")
    # 1. parity pairs
    c, p = q[q["cp"] == "C"], q[q["cp"] == "P"]
    m = pd.merge_asof(c, p[keys + ["strike", "timestamp", "price", "index_price"]], on="timestamp", by=keys + ["strike"],
                      direction="nearest", tolerance=pd.Timedelta(minutes=PARITY_MINUTES), suffixes=("", "_p"))
    m = m.dropna(subset=["price_p"])
    m = m[np.abs(np.log(m["strike"] / m["index_price"])) < NEAR_MONEY_LOG]
    m = m.assign(ratio=bs.parity_forward(m["price"], m["price_p"], m["strike"]) / ((m["index_price"] + m["index_price_p"]) / 2))
    par = m.groupby(keys)["ratio"].agg(parity_ratio="median", parity_pairs="size")
    # 2. IV-implied forward per trade
    d_idx = pd.Series(bs.call_delta(q["index_price"], q["strike"], q["T"], q["iv"] / 100), index=q.index)
    near = q[(q["price"] >= 0.005) & d_idx.between(0.15, 0.85)]
    f = bs.implied_forward(near["price"], near["strike"], near["T"], near["iv"] / 100, near["cp"] == "C",
                           0.7 * near["index_price"], 1.4 * near["index_price"])
    ivr = (pd.Series(f, index=near.index) / near["index_price"]).groupby([near[k] for k in keys]).agg(["median", "size"])
    ivr.columns = ["iv_ratio", "iv_trades"]
    out = ivr.join(par, how="outer")
    use_parity = out["parity_pairs"].fillna(0) >= PARITY_MIN_PAIRS
    out["ratio"] = np.where(use_parity, out["parity_ratio"], out["iv_ratio"])
    out["source"] = np.where(use_parity, "parity", np.where(out["iv_ratio"].notna(), "iv", "index"))
    out["ratio"] = out["ratio"].fillna(1.0)
    return out


def parse(trades: pd.DataFrame) -> pd.DataFrame:
    """Adds expiry, strike, call/put, T, the window's forward ratio F / index (window_forwards), the
    forward at the trade (index price x ratio) and the forward delta of each trade."""
    out = _expiry_strike_cp(trades)
    wf = window_forwards(out)
    key = pd.MultiIndex.from_arrays([out["roll"], out["expiry"]])
    out["fwd_ratio"] = wf["ratio"].reindex(key).fillna(1.0).to_numpy()
    out["forward"] = out["index_price"] * out["fwd_ratio"]
    with np.errstate(divide="ignore", invalid="ignore"):
        out["delta_call"] = bs.call_delta(out["forward"], out["strike"], out["T"], out["iv"] / 100)
    out.attrs["window_forwards"] = wf
    return out


def forward_ratio(tr: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> float:
    """F / index for expiry t1 in the roll window at t0 (1.0, the index, if nothing traded)."""
    w = tr.loc[(tr["roll"] == t0) & (tr["expiry"] == t1), "fwd_ratio"]
    return float(w.iloc[0]) if len(w) else 1.0


def traded_strikes(tr: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp, window: pd.Timedelta, cp: str) -> pd.DataFrame:
    w = tr[(tr["expiry"] == t1) & (tr["cp"] == cp) & (tr["timestamp"] >= t0 - window) & (tr["timestamp"] <= t0 + window)
           & (tr["iv"] > 0)]
    if w.empty:
        return pd.DataFrame(columns=["strike", "delta", "iv", "trades", "btc_volume"])
    g = w.groupby("strike")
    return pd.DataFrame({"delta": g["delta_call"].median(), "iv": g["iv"].median() / 100, "trades": g.size(),
                         "btc_volume": g["amount"].sum()}).reset_index()


BUCKETS = {0.1: (0.05, 0.15), 0.25: (0.15, 0.35), 0.5: (0.40, 0.60)}


def calibrate(tr: pd.DataFrame, dvol_08: pd.Series) -> dict:
    """Median half-spread (taker sells below mark) and skew (IV - DVOL), in vol points, per delta bucket."""
    t = tr[(tr["T"] > 20 / 365) & (tr["T"] < 40 / 365) & (tr["iv"] > 0)].copy()
    vega_pt = bs.vega_usd(t["forward"], t["strike"], t["T"], t["iv"] / 100) / t["forward"] / 100
    t["below_mark"] = (t["mark_price"] - t["price"]) / vega_pt
    t["absdelta"] = np.where(t["cp"] == "C", t["delta_call"], 1 - t["delta_call"])
    dv = dvol_08.reindex(t["roll"].dt.tz_localize(None).dt.normalize()).to_numpy()
    t["skew"] = t["iv"] - dv
    out = {"trades_used": int(len(t)), "half_spread": {}, "skew": {}}
    for target, (a, b) in BUCKETS.items():
        sel = t[(t["absdelta"] >= a) & (t["absdelta"] < b) & ((t["cp"] == "C") | (target == 0.5))]
        out["half_spread"][target] = float(sel.loc[sel["direction"] == "sell", "below_mark"].median())
        out["skew"][target] = float(sel["skew"].median())
    return out


def _fees(price: np.ndarray | float, fee: float, cap: float):
    return np.minimum(fee, cap * price)


def run(trades: pd.DataFrame, delivery: pd.Series, dvol_08: pd.Series, cfg: dict, target: float, calib: dict,
        spread_multiplier: float = 1.0) -> pd.DataFrame:
    vo = cfg["vol_overlay"]
    rolls = roll_times(vo["first_expiry"], vo["last_expiry"], vo["roll_hour_utc"])
    window = pd.Timedelta(minutes=vo["trade_window_minutes"])
    skew = calib["skew"][target] / 100
    half_spread = calib["half_spread"][target] * spread_multiplier
    rows = []
    for t0, t1 in zip(rolls[:-1], rolls[1:]):
        S0 = float(delivery.loc[t0.tz_localize(None).normalize()])
        ST = float(delivery.loc[t1.tz_localize(None).normalize()])
        T = (t1 - t0).total_seconds() / (365.25 * 86400)
        F0 = S0 * forward_ratio(trades, t0, t1)
        dv = float(dvol_08.loc[t0.tz_localize(None).normalize()]) / 100
        fb_sig = dv + skew
        fb_K = float(bs.strike_for_delta(F0, T, fb_sig, target))
        fb_price = float(bs.call_btc(F0, fb_K, T, fb_sig))
        ks = traded_strikes(trades, t0, t1, window, "C")
        row = {"roll": t0, "expiry": t1, "days": T * 365.25, "S0": S0, "F0": F0, "ST": ST, "dvol": dv,
               "fallback_strike": fb_K, "fallback_price": fb_price, "strikes_traded": int(len(ks))}
        pick = None
        if len(ks):
            ks["miss"] = (ks["delta"] - target).abs()
            best = ks.sort_values(["miss", "btc_volume"], ascending=[True, False]).iloc[0]
            if best["miss"] <= vo["max_delta_miss"]:
                pick = best
        if pick is not None:
            K, sig, src = float(pick["strike"]), float(pick["iv"]), "trades"
            row.update(trade_strike=K, trade_iv=sig, trade_delta=float(pick["delta"]), trade_count=int(pick["trades"]))
        else:
            K, sig, src = fb_K, fb_sig, "fallback"
        price = float(bs.call_btc(F0, K, T, sig))
        haircut = float(bs.vega_usd(F0, K, T, sig)) / F0 * half_spread / 100
        fee = float(_fees(price, vo["option_fee"], vo["option_fee_cap"]))
        payoff = max(ST - K, 0.0) / ST
        sfee = float(_fees(payoff, vo["settlement_fee"], vo["option_fee_cap"])) if payoff > 0 else 0.0
        row.update(source=src, strike=K, iv=sig, delta=float(bs.call_delta(F0, K, T, sig)), moneyness=K / S0 - 1,
                   premium=price, spread_cost=haircut, fee=fee, payoff=payoff, settlement_fee=sfee,
                   ret_btc=price - haircut - fee - payoff - sfee, btc_usd_return=ST / S0 - 1)
        rows.append(row)
    out = pd.DataFrame(rows)
    out["btc_held"] = (1 + out["ret_btc"]).cumprod()
    return out
