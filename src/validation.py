"""Data checks, written to data/processed/validation.json. Each check says what it compares; nothing is
silently repaired (forward-filled gaps are counted here and reported in the README)."""
import json

import numpy as np
import pandas as pd

from .strategies import hourly_index


def _gaps(k: pd.DataFrame, idx: pd.DatetimeIndex) -> int:
    have = set((k["open_time"] + pd.Timedelta(hours=1)).dt.as_unit("ns"))
    return int(sum(1 for t in idx if t not in have))


def run(raw: dict, cfg: dict, qframe: pd.DataFrame, cme: pd.DataFrame, path) -> dict:
    idx = hourly_index(cfg)
    out = {"hours_in_sample": int(len(idx))}
    out["missing_hours"] = {k: _gaps(raw[k], idx) for k in ("spot_bn_1h", "perp_bn_1h", "perp_bb_1h", "btcusd_cb_1h")}
    fb, fy = raw["funding_bn"].set_index("time")["funding_rate"], raw["funding_bb"].set_index("time")["funding_rate"]
    fb.index, fy.index = fb.index.floor("h"), fy.index.floor("h")
    inside = lambda s: s[(s.index > idx[0] - pd.Timedelta(hours=1)) & (s.index <= idx[-1])]
    j = pd.concat([inside(fb), inside(fy)], axis=1, keys=["binance", "bybit"]).dropna()
    out["funding"] = {"binance_settlements": int(len(inside(fb))), "bybit_settlements": int(len(inside(fy))),
                      "expected_8h_settlements": int(len(idx) / 8), "common": int(len(j)),
                      "corr_binance_bybit": float(j.corr().iloc[0, 1]),
                      "mean_abs_diff_bp": float((j["binance"] - j["bybit"]).abs().mean() * 1e4)}
    p = raw["usdtusd_cb_1d"]
    out["usdt_usd"] = {"first": str(p["open_time"].min().date()), "min_close": float(p["close"].min()),
                       "min_close_date": str(p.loc[p["close"].idxmin(), "open_time"].date()),
                       "days_assumed_at_par_before_first": int((p["open_time"].min().tz_localize(None) - pd.Timestamp(cfg["sample"]["start_utc"])).days)}
    end = pd.Timestamp(cfg["sample"]["end_utc"]).normalize()
    out["last_observation"] = {k: str(raw[k]["date"].max().date()) for k in ("sofr", "usdjpy", "usdkrw", "krw_rate", "tona")}
    out["forward_filled_days_at_end"] = {k: int((end - raw[k]["date"].max()).days) for k in ("usdjpy", "usdkrw")}
    rolls = qframe.index[qframe["roll_binance_q"]]
    out["quarterly"] = {"first_hour": str(qframe.index[0]), "rolls": int(len(rolls)),
                        "rolls_with_next_contract_priced": int(qframe.loc[rolls, "F_binance_q"].notna().sum()),
                        # basis of the expiring contract one hour before settlement: near zero if it converges
                        "basis_1h_before_expiry_bp_median": float(((qframe["F_binance_q"].shift(1) / qframe["S"].shift(1) - 1)
                                                                   .loc[rolls].abs().median()) * 1e4),
                        "basis_1h_before_expiry_bp_max": float(((qframe["F_binance_q"].shift(1) / qframe["S"].shift(1) - 1)
                                                                .loc[rolls].abs().max()) * 1e4)}
    out["cme"] = {"days": int(len(cme)), "excluded_near_expiry_or_roll": int(cme["excluded"].sum()),
                  "spot_missing": int(cme["S"].isna().sum())}
    q = raw["spot_bn_1h"]
    s = q.set_index(q["open_time"] + pd.Timedelta(hours=1))["close"]
    cb = raw["btcusd_cb_1h"].set_index(raw["btcusd_cb_1h"]["open_time"] + pd.Timedelta(hours=1))["close"]
    jj = pd.concat([s, cb], axis=1, keys=["binance_usdt", "coinbase_usd"]).dropna()
    gap = (jj["binance_usdt"] / jj["coinbase_usd"] - 1) * 1e4
    out["binance_vs_coinbase_bp"] = {"median": float(gap.median()), "p01": float(gap.quantile(0.01)), "p99": float(gap.quantile(0.99))}
    path.write_text(json.dumps(out, indent=1, default=lambda x: float(x) if isinstance(x, np.floating) else str(x)))
    return out
