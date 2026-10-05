"""Chapter 2: can a bitcoin investor earn a yield in bitcoin by selling options?

    python -m src.vol_overlay.pipeline        (also run at the end of python -m src.pipeline)

Writes data/processed/vol_overlay/results.json, the monthly tables, figures/vol_overlay/*.png and
reports/factsheet_btc_covered_call.pdf.
"""
import json
import logging

import numpy as np
import pandas as pd

from .. import share_classes as sc
from ..config import ROOT, load_config
from ..pipeline import load_raw
from . import covered_call as cc, options as bs, short_vol as sv, vrp

log = logging.getLogger("vol_overlay")
OUT, FIG = ROOT / "data" / "processed" / "vol_overlay", ROOT / "figures" / "vol_overlay"


def monthly_stats(r: pd.Series) -> dict:
    """r: monthly returns (decimal). Compounded annual return, annualised volatility, worst month."""
    years = len(r) / 12
    g = float((1 + r).prod())
    nav = (1 + r).cumprod()
    return {"months": int(len(r)), "ann_return": g ** (1 / years) - 1, "ann_vol": float(r.std() * np.sqrt(12)),
            "worst_month": float(r.min()), "best_month": float(r.max()), "share_positive": float((r > 0).mean()),
            "max_drawdown": float((nav / nav.cummax() - 1).min())}


def main(cfg: dict | None = None, raw: dict | None = None, figures: bool = True) -> dict:
    cfg = cfg or load_config()
    raw = raw or load_raw()
    OUT.mkdir(parents=True, exist_ok=True)
    vo = cfg["vol_overlay"]
    H = vo["roll_hour_utc"]
    dv = raw["deribit_dvol_1h"].set_index("ts")["open"]
    dvol_08 = vrp.daily_at(dv, H)
    deliv = raw["deribit_delivery"].set_index("date")["price"]
    b = raw["btcusd_cb_1h"]
    px_08 = vrp.daily_at(pd.Series(b["close"].to_numpy(), index=b["open_time"] + pd.Timedelta(hours=1)), H)
    fb = raw["funding_bn"]
    f = pd.Series(fb["funding_rate"].to_numpy(), index=fb["time"].dt.floor("h"))
    funding_daily = f.groupby((f.index - pd.Timedelta(hours=H)).ceil("D").tz_localize(None)).sum()
    trades = cc.parse(raw["deribit_option_trades_rolls"])
    calib = cc.calibrate(trades, dvol_08)
    res = {"calibration": calib, "option_trades": int(len(trades))}

    # ---- the forward each roll window's options are priced off, and a repricing check
    rl = cc.roll_times(vo["first_expiry"], vo["last_expiry"], H)
    wf = trades.attrs["window_forwards"]
    tw = wf.reindex(pd.MultiIndex.from_tuples(list(zip(rl[:-1], rl[1:])), names=["roll", "expiry"]))
    days_ = np.array([(b - a).total_seconds() / 86400 for a, b in zip(rl[:-1], rl[1:])])
    both = tw.dropna(subset=["parity_ratio", "iv_ratio"])
    fm = trades[(trades["T"] > 20 / 365) & (trades["T"] < 40 / 365) & (trades["iv"] > 0) & (trades["price"] >= 0.001)]
    reprice = {}
    for name, F in (("index", fm["index_price"]), ("forward", fm["forward"])):
        model = np.where(fm["cp"] == "C", bs.call_btc(F, fm["strike"], fm["T"], fm["iv"] / 100),
                         bs.put_btc(F, fm["strike"], fm["T"], fm["iv"] / 100))
        err = pd.Series(model / fm["price"].to_numpy() - 1, index=fm.index)
        reprice[name] = {cp_: {"median": float(err[fm["cp"] == cp_].median()), "median_abs": float(err[fm["cp"] == cp_].abs().median())}
                         for cp_ in ("C", "P")}
    res["forward"] = {"target_windows": int(len(tw)), "source_counts": tw["source"].value_counts().to_dict(),
                      "ratio_median": float(tw["ratio"].median()), "ratio_min": float(tw["ratio"].min()), "ratio_max": float(tw["ratio"].max()),
                      "ann_basis_mean": float(((tw["ratio"].to_numpy() - 1) * 365 / days_).mean()),
                      "parity_vs_iv_implied_bp_median_abs": float(((both["parity_ratio"] - both["iv_ratio"]).abs() * 1e4).median()),
                      "windows_with_both": int(len(both)),
                      "reprice_front_month_trades": int(len(fm)), "reprice_relative_error": reprice}
    rolls_ = cc.roll_times(vo["first_expiry"], vo["last_expiry"], H)
    dd = raw["deribit_delivery"]["date"]
    per_roll = trades.groupby("roll").size()
    hours = pd.date_range(dv.index.min(), dv.index.max(), freq="h")
    res["data_checks"] = {"rolls": len(rolls_),
                          "rolls_with_exactly_one_delivery_price": int(sum((dd == r.tz_localize(None).normalize()).sum() == 1 for r in rolls_)),
                          "trades_per_roll_window": {"min": int(per_roll.min()), "median": float(per_roll.median()), "max": int(per_roll.max())},
                          "dvol_hours_missing": int(len(hours.difference(dv.index))), "dvol_first": str(dv.index.min())}

    # ---- the volatility premium
    t = vrp.vrp_table(dvol_08, px_08, vo["rv_days"])
    t = t.loc[vo["first_expiry"]:]
    t.to_csv(OUT / "vrp_daily.csv", float_format="%.6f")
    res["vrp"] = {"first": str(t.index.min().date()), "last": str(t.index.max().date()),
                  "dvol_mean": float(t["dvol"].mean()), "rv_mean": float(t["rv_fwd"].mean()),
                  "vrp_vol_mean": float(t["vrp_vol"].mean()), "share_days_positive": float((t["vrp_vol"] > 0).mean()),
                  "by_year": {str(y): {k: float(v) for k, v in g[["dvol", "rv_fwd", "vrp_vol"]].mean().items()}
                              for y, g in t.groupby(t.index.year)}}

    # ---- covered calls and the short straddle
    tables, perp_cost = {}, cfg["venues"]["binance"]["perp_taker"] + cfg["costs"]["perp_half_spread_bps"] / 1e4
    for d in vo["call_deltas"]:
        tables[f"cc_{int(d * 100)}d"] = cc.run(trades, deliv, dvol_08, cfg, d, calib)
    tables["straddle"] = sv.run(trades, deliv, dvol_08, funding_daily, cfg, perp_cost, calib)
    for k, v in tables.items():
        v.to_csv(OUT / f"{k}_monthly.csv", index=False, float_format="%.6f")
    res["covered_calls"] = {}
    for d in vo["call_deltas"]:
        o = tables[f"cc_{int(d * 100)}d"]
        wide = cc.run(trades, deliv, dvol_08, cfg, d, calib, spread_multiplier=vo["half_spread_sensitivity"])
        ov = o[o["source"] == "trades"]
        usd = (1 + o["ret_btc"]) * (1 + o["btc_usd_return"]) - 1
        rally = o["btc_usd_return"] > 0.10
        res["covered_calls"][f"{int(d * 100)}d"] = {
            **monthly_stats(o["ret_btc"]), "from_trades": int((o["source"] == "trades").sum()),
            "premium_mean": float(o["premium"].mean()), "costs_mean": float((o["spread_cost"] + o["fee"] + o["settlement_fee"]).mean()),
            "payoff_mean": float(o["payoff"].mean()), "share_months_paid_out": float((o["payoff"] > 0).mean()),
            "moneyness_mean": float(o["moneyness"].mean()), "iv_minus_dvol_mean": float((o["iv"] - o["dvol"]).mean()),
            "trade_minus_fallback_premium": float((ov["premium"] - ov["fallback_price"]).mean()),
            "ann_return_3x_spreads": monthly_stats(wide["ret_btc"])["ann_return"],
            "usd_ann_return": monthly_stats(usd)["ann_return"], "btc_usd_ann_return": monthly_stats(o["btc_usd_return"])["ann_return"],
            "rally_months": int(rally.sum()), "rally_months_mean_btc_return": float(o.loc[rally, "ret_btc"].mean()),
            "rally_months_mean_btc_price_return": float(o.loc[rally, "btc_usd_return"].mean()),
            "worst_month_expiry": str(o.loc[o["ret_btc"].idxmin(), "expiry"].date())}
    s = tables["straddle"]
    wide = sv.run(trades, deliv, dvol_08, funding_daily, cfg, perp_cost, calib, spread_multiplier=vo["half_spread_sensitivity"])
    per = lambda c: float((s[c] / s["S0"]).mean())
    res["straddle"] = {"usd_on_notional": monthly_stats(s["ret_notional"]), "btc": monthly_stats(s["ret_btc"]),
                       "from_trades": int((s["source"] == "trades").sum()),
                       "iv_mean": float(s["iv"].mean()), "dvol_mean": float(s["dvol"].mean()), "rv_mean": float(s["rv"].mean()),
                       "atm_vrp_mean": float((s["iv"] - s["rv"]).mean()), "dvol_minus_atm_iv_mean": float((s["dvol"] - s["iv"]).mean()),
                       "share_months_iv_above_rv": float((s["iv"] > s["rv"]).mean()),
                       "decomposition_per_notional": {"premium_minus_payoff": per("premium_usd") - per("payoff_usd"),
                                                      "hedge_pnl": per("hedge_pnl_usd"), "spread": -per("spread_usd"),
                                                      "fees": -per("fees_usd"), "hedge_costs": -per("hedge_cost_usd"),
                                                      "total": per("pnl_usd")},
                       "corr_with_varswap_approx": float(s[["ret_notional", "varswap_approx"]].corr().iloc[0, 1]),
                       "varswap_approx_mean": float(s["varswap_approx"].mean()),
                       "ann_return_3x_spreads": monthly_stats(wide["ret_notional"])["ann_return"],
                       "worst_month_expiry": str(s.loc[s["ret_notional"].idxmin(), "expiry"].date())}

    # ---- the BTC investor's alternatives (BTC terms, monthly over the same roll periods)
    g = pd.read_csv(ROOT / "data" / "processed" / "class_index_gross.csv", index_col=0, parse_dates=True)["BTC hedged"]
    rolls = tables["cc_25d"][["roll", "expiry"]]
    at = lambda d: float(g.asof(d.tz_localize(None).normalize()))
    carry = pd.Series([at(e) / at(r) - 1 for r, e in zip(rolls["roll"], rolls["expiry"])])
    alts = {"hold BTC": pd.Series(np.zeros(len(rolls))), "basis carry, BTC-hedged class": carry,
            "covered call, 25-delta": tables["cc_25d"]["ret_btc"], "covered call, 10-delta": tables["cc_10d"]["ret_btc"],
            "short straddle, delta-hedged (1x)": s["ret_btc"]}
    res["btc_investor"] = {k: monthly_stats(v.reset_index(drop=True)) for k, v in alts.items()}
    res["btc_investor_window"] = [str(rolls["roll"].iloc[0].date()), str(rolls["expiry"].iloc[-1].date())]

    # ---- does a premium signal help? sell only when DVOL exceeds the volatility of the past 30 days
    r_ = np.log(px_08).diff()
    rv_past = np.sqrt(365 / vo["rv_days"] * (r_ ** 2).rolling(vo["rv_days"]).sum())
    sig_on = pd.Series([float(dvol_08.loc[d.tz_localize(None).normalize()]) / 100 >
                        float(rv_past.loc[d.tz_localize(None).normalize()]) for d in s["roll"]])
    res["signal"] = {"rule": "sell at a roll only if DVOL > realised volatility of the previous 30 days",
                     "months_on": int(sig_on.sum()), "months": int(len(sig_on))}
    for k, col in (("cc_25d", "ret_btc"), ("straddle", "ret_notional")):
        rr = tables[k][col]
        res["signal"][k] = {"mean_on": float(rr[sig_on].mean()), "mean_off": float(rr[~sig_on].mean()),
                            "ann_return_always": monthly_stats(rr)["ann_return"],
                            "ann_return_signal": monthly_stats(rr.where(sig_on, 0.0))["ann_return"]}

    # ---- stress months and the link to funding
    stress = {}
    for m in vo["stress_months"]:
        i = tables["cc_25d"].index[tables["cc_25d"]["expiry"].dt.strftime("%Y-%m") == m]
        if len(i):
            j = i[0]
            stress[m] = {"period": [str(tables["cc_25d"].at[j, "roll"].date()), str(tables["cc_25d"].at[j, "expiry"].date())],
                         "btc_price": float(tables["cc_25d"].at[j, "btc_usd_return"]),
                         "cc_25d_btc": float(tables["cc_25d"].at[j, "ret_btc"]), "cc_10d_btc": float(tables["cc_10d"].at[j, "ret_btc"]),
                         "straddle_usd_notional": float(s.at[j, "ret_notional"]), "straddle_iv": float(s.at[j, "iv"]),
                         "straddle_rv": float(s.at[j, "rv"])}
    res["stress_months"] = stress
    fund = pd.Series([float(funding_daily.loc[r.tz_localize(None).normalize():e.tz_localize(None).normalize()].sum()
                            / ((e - r).days / 365)) for r, e in zip(s["roll"], s["expiry"])])
    j = pd.DataFrame({"funding": fund, "atm_vrp": s["iv"] - s["rv"], "dvol_vrp": s["dvol"] - s["rv"], "iv": s["iv"]})
    res["vrp_vs_funding"] = {"corr_funding_atm_vrp": float(j["funding"].corr(j["atm_vrp"])),
                             "corr_funding_iv": float(j["funding"].corr(j["iv"])), "months": int(len(j))}
    j.assign(roll=s["roll"]).to_csv(OUT / "vrp_vs_funding.csv", index=False, float_format="%.6f")

    # ---- a BTC class built on the 25-delta covered call, after the same assumed fees
    o = tables["cc_25d"]
    idx = pd.DatetimeIndex(o["expiry"].dt.tz_localize(None).dt.normalize())
    gross = pd.Series(np.r_[1.0, o["btc_held"].to_numpy()], index=idx.insert(0, o["roll"].iloc[0].tz_localize(None).normalize()))
    fees = sc.apply_fees(gross, cfg["share_classes"]["management_fee"], cfg["share_classes"]["performance_fee"])
    net = fees["nav"] / 100
    yrs = (gross.index[-1] - gross.index[0]).days / 365.25
    res["covered_call_class"] = {"gross": monthly_stats(gross.pct_change().dropna()), "net": monthly_stats(net.pct_change().dropna()),
                                 "management_fee_ann": float(fees["mgmt_fee"].sum() / fees["assets"].mean() / yrs),
                                 "performance_fee_ann": float(fees["perf_paid"].sum() / fees["assets"].mean() / yrs),
                                 "quarters_with_performance_fee": int((fees["perf_paid"] > 0).sum())}
    if figures:
        from . import plots
        plots.make_all(cfg, res, t, tables, alts, j, gross, net, FIG)
        from . import factsheet
        factsheet.build(cfg, res, gross, net, tables["cc_25d"], ROOT / "reports" / "factsheet_btc_covered_call.pdf")
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=lambda x: float(x) if isinstance(x, (np.floating, np.integer)) else str(x)))
    log.info("vol overlay done")
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
