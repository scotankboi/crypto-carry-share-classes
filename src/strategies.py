"""The two candidate master strategies, as inputs to the engine.

    perp_carry       long spot BTC, short the USDT-margined perpetual on Binance and Bybit (weights
                     from config), funding every 8 hours; venue weights and margin reset weekly
    quarterly_carry  long spot BTC, short Binance's USDT-margined quarterly future, held to expiry and
                     rolled into the next quarter at 08:00 UTC on expiry day (it settles to the index,
                     taken here as the spot price at that hour)

Both books are delta-neutral in BTC and settle in USDT: economically they are a USDT deposit plus the
carry. That is why the USDT share class is the native one (src/share_classes.py).
"""
import numpy as np
import pandas as pd

from . import engine


def hourly_index(cfg: dict) -> pd.DatetimeIndex:
    s = cfg["sample"]
    return pd.date_range(pd.Timestamp(s["start_utc"], tz="UTC") + pd.Timedelta(hours=1), pd.Timestamp(s["end_utc"], tz="UTC"),
                         freq="h").as_unit("ns")


def _close(k: pd.DataFrame, idx: pd.DatetimeIndex, col: str = "close") -> pd.Series:
    """Kline closes keyed by hour end; gaps forward-filled (and counted by the validation step)."""
    s = pd.Series(k[col].to_numpy(), index=(k["open_time"] + pd.Timedelta(hours=1)).dt.as_unit("ns"))
    return s[~s.index.duplicated()].reindex(idx).ffill()


def _funding(ev: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.Series:
    """Settlements stamped at (or a few ms after) the hour are credited in the hour ending at that time."""
    t = ev["time"].dt.floor("h")
    return pd.Series(ev["funding_rate"].to_numpy(), index=t).groupby(level=0).sum().reindex(idx, fill_value=0.0)


def perp_frame(raw: dict, cfg: dict) -> pd.DataFrame:
    idx = hourly_index(cfg)
    df = pd.DataFrame(index=idx)
    df["S"] = _close(raw["spot_bn_1h"], idx)
    for v, k, f in (("binance", "perp_bn_1h", "funding_bn"), ("bybit", "perp_bb_1h", "funding_bb")):
        df[f"F_mtm_{v}"] = df[f"F_{v}"] = _close(raw[k], idx)
        df[f"H_{v}"] = _close(raw[k], idx, "high")
        df[f"f_{v}"] = _funding(raw[f], idx)
        df[f"roll_{v}"] = False
    return df


def held_quarterly(q: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Per hour: the contract held (the earliest expiry strictly after the hour), its price, and at an
    expiry hour the settlement of the expiring contract and the price of the next one."""
    q = q.assign(ts=(q["open_time"] + pd.Timedelta(hours=1)).dt.as_unit("ns"))
    px = q.pivot_table(index="ts", columns="symbol", values="close").reindex(idx).ffill()
    hi = q.pivot_table(index="ts", columns="symbol", values="high").reindex(idx)
    exp = q.groupby("symbol")["expiry"].first().sort_values()
    out = pd.DataFrame(index=idx)
    held = np.searchsorted(exp.to_numpy(), idx.to_numpy(), side="right")      # first expiry > t
    out["symbol"] = exp.index.to_numpy()[held]
    out["expiry"] = exp.to_numpy()[held]
    out["F"] = [px.at[t, s] for t, s in zip(idx, out["symbol"])]
    out["H"] = [hi.at[t, s] if not np.isnan(hi.at[t, s]) else px.at[t, s] for t, s in zip(idx, out["symbol"])]
    out["roll"] = idx.isin(exp.to_numpy())
    out["days_to_expiry"] = (out["expiry"] - idx).dt.total_seconds() / 86400
    return out


def quarterly_frame(raw: dict, cfg: dict) -> pd.DataFrame:
    idx = hourly_index(cfg)
    df = pd.DataFrame(index=idx)
    df["S"] = _close(raw["spot_bn_1h"], idx)
    h = held_quarterly(raw["quarterly_bn_1h"], idx)
    df["F_binance_q"] = h["F"]
    df["F_mtm_binance_q"] = np.where(h["roll"], df["S"], h["F"])     # the expiring contract settles to the index
    df["H_binance_q"] = h["H"]
    df["f_binance_q"] = 0.0
    df["roll_binance_q"] = h["roll"]
    df["days_to_expiry"] = h["days_to_expiry"]
    df["symbol"] = h["symbol"]
    return df.loc[df["F_binance_q"].first_valid_index():]      # quarterly data start on 2021-02-03


def weekly_due(idx: pd.DatetimeIndex, weekday: int) -> pd.Series:
    return pd.Series((idx.weekday == weekday) & (idx.hour == 0), index=idx)


def run_master(name: str, raw: dict, cfg: dict, leverage: float | None = None, costs: dict | None = None) -> pd.DataFrame:
    st, v, c = cfg["strategy"], cfg["venues"], cfg["costs"]
    L = leverage or st["leverage"]
    over = costs or {}                       # cost sensitivity: {"spot_taker": .., "perp_taker": ..}
    spot_cost = over.get("spot_taker", c["spot_taker"]) + c["spot_half_spread_bps"] / 1e4
    if name == "perp_carry":
        df = perp_frame(raw, cfg)
        legs = {k: engine.LegCosts(over.get("perp_taker", v[k]["perp_taker"]) + c["perp_half_spread_bps"] / 1e4)
                for k in ("binance", "bybit")}
        weights = st["weights"]
        mm = {k: v[k]["maintenance_margin"] for k in legs}
    elif name == "quarterly_carry":
        df = quarterly_frame(raw, cfg)
        legs = {"binance_q": engine.LegCosts(over.get("perp_taker", v["binance"]["perp_taker"]) + c["perp_half_spread_bps"] / 1e4,
                                             v["binance"]["delivery_fee"])}
        weights = {"binance_q": 1.0}
        mm = {"binance_q": v["binance"]["maintenance_margin"]}
    else:
        raise ValueError(name)
    return engine.run(df, legs, weights, leverage=L, band=st["rebalance_band"], maintenance=mm, capital=st["capital_usdt"],
                      spot_cost=spot_cost, rebalance_due=weekly_due(df.index, st["rebalance_weekday"]),
                      lag=st["emergency_lag_hours"])
