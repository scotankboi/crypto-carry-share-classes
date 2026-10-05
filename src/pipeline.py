"""End to end: data -> checks -> carry -> margin -> master strategy -> share classes -> counterparty and
stress -> figures and factsheets.

    python -m src.pipeline              # rebuild everything from data/raw
    python -m src.pipeline --collect    # fetch data/raw first (network; skips series already present)

Every number quoted in the README is written to data/processed/results.json (or validation.json, or the
chapter 2 results) by this run; tests/check_readme.py checks the README against them.
"""
import argparse
import copy
import json
import logging

import numpy as np
import pandas as pd

from . import carry, counterparty as cp, margin, risk, share_classes as sc, strategies as stg, stress, validation
from .config import ROOT, load_config

log = logging.getLogger("pipeline")
RAW, OUT, FIG, REP = ROOT / "data" / "raw", ROOT / "data" / "processed", ROOT / "figures", ROOT / "reports"
CLASSES = ["USDT", "USD", "JPY hedged", "KRW hedged", "BTC hedged"]


def load_raw() -> dict:
    return {p.stem: pd.read_parquet(p) for p in sorted(RAW.glob("*.parquet"))}


def series(df: pd.DataFrame, col: str = "value", scale: float = 1.0) -> pd.Series:
    return df.set_index("date")[col].astype(float) / scale


def daily(hourly: pd.Series, hour: int) -> pd.Series:
    s = hourly[hourly.index.hour == hour]
    s.index = s.index.tz_localize(None).normalize()
    return s


def kline_close(k: pd.DataFrame) -> pd.Series:
    return pd.Series(k["close"].to_numpy(), index=(k["open_time"] + pd.Timedelta(hours=1)))


def ann_by_year(ev: pd.DataFrame) -> dict:
    s = ev.set_index("time")["funding_rate"]
    out = {}
    for y, g in s.groupby(s.index.year):
        yrs = (g.index.max() - g.index.min()).total_seconds() / (365.25 * 86400) + 8 / 8760
        out[int(y)] = float(g.sum() / yrs)
    return out


def ydict(s: pd.Series) -> dict:
    return {str(k.year): round(float(v), 6) for k, v in s.items()}


def log_attribution(led: pd.DataFrame, parts=("funding", "convergence", "costs")) -> dict:
    """Annualised contributions that add up exactly to the annualised log return. Each hour's P&L
    components, as a share of the previous hour's NAV, are scaled by ln(1 + r_t) / r_t (Carino 1999), so
    their sum over the sample is ln(NAV_end / NAV_start)."""
    nav_prev = led["nav"].shift(1).iloc[1:]
    r = (led["nav"].iloc[1:] / nav_prev - 1).to_numpy()
    small = np.abs(r) < 1e-12
    k = np.where(small, 1.0, np.log1p(r) / np.where(small, 1.0, r))
    yrs = (led.index[-1] - led.index[0]).total_seconds() / (365.25 * 86400)
    out = {p: float((led[p].iloc[1:] / nav_prev * k).sum() / yrs) for p in parts}
    out["sum"] = float(sum(out[p] for p in parts))
    out["log_return_ann"] = float(np.log(led["nav"].iloc[-1] / led["nav"].iloc[0]) / yrs)
    out["compounded_return_ann"] = float(np.expm1(out["log_return_ann"]))
    return out


def regime_of(d: pd.Timestamp, events: dict) -> str:
    if d < events["FTX"]:
        return "1. before FTX"
    if d < events["US spot ETFs approved"]:
        return "2. FTX to spot ETFs"
    return "3. after spot ETFs"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    if args.collect:
        from .collect import collect
        collect(cfg)
    for d in (OUT, FIG, REP):
        d.mkdir(parents=True, exist_ok=True)
    raw = load_raw()
    H = cfg["share_classes"]["valuation_hour_utc"]
    L = cfg["strategy"]["leverage"]
    res = {"config": {"leverage": L, "valuation_hour_utc": H, "sample": cfg["sample"]}}
    events = {e["label"]: pd.Timestamp(e["date"]) for e in cfg["events"]}

    sofr = series(raw["sofr"], scale=100)
    tona = series(raw["tona"], scale=100)
    krw_rate = series(raw["krw_rate"], scale=100)
    usdjpy, usdkrw = series(raw["usdjpy"]), series(raw["usdkrw"])
    u = raw["usdtusd_cb_1d"]
    # A Coinbase daily candle opened on day d closes at 24:00 UTC, after day d's NAV hour; its close is
    # first known on day d + 1, so it values the NAV of d + 1 (no look-ahead). usdt_close keeps the
    # candle's own date for reporting the peg.
    usdt_close = pd.Series(u["close"].to_numpy(), index=u["open_time"].dt.tz_localize(None).dt.normalize())
    usdt_usd = sc.usdt_usd_known_by_nav(u)
    btc_usd = daily(kline_close(raw["btcusd_cb_1h"]), H)

    pf, qf = stg.perp_frame(raw, cfg), stg.quarterly_frame(raw, cfg)
    cme = carry.cme_basis(raw["cme_btc_1d"], raw["btcusd_cb_1h"])
    res["validation"] = validation.run(raw, cfg, qf, cme, OUT / "validation.json")
    log.info("data checks done")

    # ---- the carry
    f_avg = (pf["f_binance"] + pf["f_bybit"]) / 2
    weekly = f_avg.groupby(f_avg.index.tz_localize(None).to_period("W-SUN")).agg(["sum", "count"])
    weekly = weekly[weekly["count"] == 168]["sum"] * 365 / 7
    weekly.index = weekly.index.to_timestamp(how="start")
    bp = carry.bai_perron(weekly, cfg["breaks"]["max_breaks"], cfg["breaks"]["min_segment_weeks"])
    q_ann = ((qf["F_binance_q"] / qf["S"] - 1) * 365 / qf["days_to_expiry"]).where(qf["days_to_expiry"] > 7)
    fund_d = {v: carry.funding_daily(pf[f"f_{v}"]) * 365 for v in ("binance", "bybit")}
    hl = raw["funding_hl"].set_index("time")["funding_rate"]
    daily_tab = pd.DataFrame({"funding_binance": fund_d["binance"], "funding_bybit": fund_d["bybit"],
                              "quarterly_basis": daily(q_ann, H)})
    daily_tab["cme_basis"] = cme.loc[~cme["excluded"]].set_index("date")["ann_basis"]
    daily_tab["regime"] = [regime_of(d, events) for d in daily_tab.index]
    daily_tab.to_csv(OUT / "carry_daily.csv", float_format="%.6f")
    by_regime = daily_tab.groupby("regime")[["funding_binance", "funding_bybit", "quarterly_basis", "cme_basis"]].mean()
    # the gap is the mean of daily differences, on days both are observed (the README uses this one definition)
    by_regime["cme_minus_quarterly"] = (daily_tab["cme_basis"] - daily_tab["quarterly_basis"]).groupby(daily_tab["regime"]).mean()
    by_regime["days_both_observed"] = (daily_tab["cme_basis"] - daily_tab["quarterly_basis"]).notna().groupby(daily_tab["regime"]).sum()
    # return on capital: offshore legs need margin 1/L on top of fully funded spot; a CME short needs FCM margin m
    for col in ("funding_binance", "quarterly_basis"):
        by_regime[f"{col}_roc_L{L:g}"] = by_regime[col] * L / (L + 1)
    for mr in cfg["market_data"]["cme_margin_rate"]:
        by_regime[f"cme_roc_margin_{mr:g}"] = by_regime["cme_basis"] / (1 + mr)
    cal = carry.calendar_carry(qf, pf["f_binance"])
    cal.to_csv(OUT / "calendar_carry.csv", index=False, float_format="%.6f")
    usde = raw["usde_supply"].set_index("date")["supply_usd"]
    uw = usde.groupby(usde.index.to_period("W-SUN")).last()
    uw.index = uw.index.to_timestamp(how="start")
    j = pd.concat([weekly.rename("funding"), np.log(uw).rename("log_usde")], axis=1, sort=True).dropna()
    j = j[j.index >= "2024-03-01"]
    res["carry"] = {
        "funding_by_year": {"binance": ann_by_year(raw["funding_bn"]), "bybit": ann_by_year(raw["funding_bb"]),
                            "hyperliquid": ann_by_year(raw["funding_hl"])},
        "funding_full_sample": {v: float(fund_d[v].mean()) for v in fund_d},
        "hyperliquid_vs_cex_since_2023_05": float(hl.sum() / ((hl.index.max() - hl.index.min()).days / 365.25)
                                                  - pf.loc[hl.index.min():, "f_binance"].sum() / ((pf.index[-1] - hl.index.min()).days / 365.25)),
        "regimes_bai_perron": bp, "by_regime": by_regime.round(5).reset_index().to_dict("records"),
        "calendar_carry_mean": cal[["basis_locked_ann", "perp_funding_ann", "calendar_carry_ann"]].mean().to_dict(),
        "calendar_carry_share_positive": float((cal["calendar_carry_ann"] > 0).mean()),
        "calendar_carry_min": float(cal["calendar_carry_ann"].min()), "calendar_carry_max": float(cal["calendar_carry_ann"].max()),
        "calendar_carry_quarters": int(len(cal)),
        "usde_weekly_since_2024_03": {"weeks": int(len(j)), "corr_level": float(j.corr().iloc[0, 1]),
                                      "corr_changes": float(j.diff().dropna().corr().iloc[0, 1]),
                                      "supply_first_bn": float(uw[uw.index >= "2024-03-01"].iloc[0] / 1e9),
                                      "supply_peak_bn": float(uw.max() / 1e9), "supply_peak_week": str(uw.idxmax().date()),
                                      "supply_last_bn": float(uw.iloc[-1] / 1e9)},
        "cme": {"days_used": int((~cme["excluded"]).sum()), "mean_ann_basis": float(cme.loc[~cme["excluded"], "ann_basis"].mean()),
                "close_alignment": carry.cme_close_alignment(cme, raw["btcusd_cb_1h"])},
    }
    log.info("carry done")

    # ---- margin model and leverage
    sp = raw["spot_bn_1h"]
    close, high = kline_close(sp), pd.Series(sp["high"].to_numpy(), index=(sp["open_time"] + pd.Timedelta(hours=1)))
    close = close.loc[cfg["sample"]["margin_history_start"]:]
    high = high.loc[close.index.min():]
    mm = max(cfg["venues"][v]["maintenance_margin"] for v in ("binance", "bybit"))
    band, lag = cfg["strategy"]["rebalance_band"], cfg["strategy"]["emergency_lag_hours"]
    mg_args = (close, high, cfg["margin"]["leverage_grid"], cfg["margin"]["topup_lag_hours"], mm,
               cfg["margin"]["evt_threshold_quantile"], cfg["margin"]["reference_probability_annual"])
    fr = margin.frontier(*mg_args, band=band)            # from the band edge: what the engine allows
    fr_target = margin.frontier(*mg_args, band=0.0)      # from the target margin 1/L, for comparison
    fr.to_csv(OUT / "margin_frontier.csv", index=False, float_format="%.6f")
    lmax = margin.max_leverage(fr, lag)
    res["margin"] = {"frontier_band_edge": fr.round(6).to_dict("records"), "frontier_target": fr_target.round(6).to_dict("records"),
                     "band": band, "engine_lag_h": lag, "maintenance": mm,
                     "reference_probability_annual": cfg["margin"]["reference_probability_annual"],
                     "max_leverage_by_lag_band_edge": {int(T): margin.max_leverage(fr, T) for T in cfg["margin"]["topup_lag_hours"]},
                     "max_leverage_by_lag_target": {int(T): margin.max_leverage(fr_target, T) for T in cfg["margin"]["topup_lag_hours"]},
                     "config_leverage": L, "max_leverage_below_reference_engine_lag": lmax,
                     "history": [str(close.index.min()), str(close.index.max())]}
    log.info("margin done")

    # ---- master strategy
    ledgers, navs, cand = {}, {}, {}
    for name in cfg["master"]["candidates"]:
        led = stg.run_master(name, raw, cfg)
        ledgers[name], navs[name] = led, daily(led["nav"], H)
    common = max(n.index.min() for n in navs.values()) + pd.Timedelta(days=1)
    for name, n in navs.items():
        s_ = risk.stats(n.loc[common:], sofr)
        cand[name] = {**s_, "liquidation_flags": int(ledgers[name]["flags"].str.contains("liquidation").sum()),
                      "emergency_rebalances": int(ledgers[name]["flags"].str.contains("emergency").sum())}
    for name, lg in ledgers.items():
        cand[name]["attribution_log_ann"] = log_attribution(lg.loc[pd.Timestamp(common, tz="UTC") + pd.Timedelta(hours=H):])
    # how much the basis each book is short moves day to day (perp: Binance; quarterly: the held contract)
    common_utc = pd.Timestamp(common, tz="UTC")
    b_perp = daily((pf["F_binance"] / pf["S"] - 1).loc[common_utc:], H).diff().std()
    b_q = daily((qf["F_binance_q"] / qf["S"] - 1).where(~qf["roll_binance_q"]).loc[common_utc:], H).diff().std()
    if "quarterly_carry" in ledgers:
        # carry locked at each roll (contracts at entry x entry basis) vs convergence actually realised
        lq, locked, realised = ledgers["quarterly_carry"], 0.0, 0.0
        for _, g in qf.groupby("symbol", sort=False):
            locked += lq.loc[g.index[0], "Q"] * (g["F_binance_q"].iloc[0] - g["S"].iloc[0])
            realised += lq.loc[g.index, "convergence"].sum()
        yq = (lq.index[-1] - lq.index[0]).total_seconds() / (365.25 * 86400)
        cand["quarterly_carry"]["locked_carry_ann_of_nav"] = float(locked / lq["nav"].mean() / yq)
        cand["quarterly_carry"]["share_of_locked_carry_realised"] = float(realised / locked)
        cand["quarterly_carry"]["basis_daily_change_sd_vs_perp"] = float(b_q / b_perp)
    master = max(cand, key=lambda k: (round(cand[k]["sharpe"], 6), -abs(cand[k]["max_drawdown"])))
    led, nav = ledgers[master], navs[master]
    years = (led.index[-1] - led.index[0]).total_seconds() / (365.25 * 86400)
    attribution = log_attribution(led.loc[pd.Timestamp(nav.index[0], tz="UTC") + pd.Timedelta(hours=H):])
    sens = {}
    for label, over in (("regular_tier_fees", cfg["costs"]["regular_tier"]),):
        sens[label] = risk.stats(daily(stg.run_master(master, raw, cfg, costs=over)["nav"], H), sofr)["ann_return"]
    lev = {}
    for Lx in (1, 2, 3):
        c2 = copy.deepcopy(cfg)
        c2["strategy"]["leverage"] = Lx
        lx = stg.run_master(master, raw, c2)
        flagged = lx.index[lx["flags"].str.contains("liquidation")]
        nav_x = daily(lx["nav"], H)
        s_x = risk.stats(nav_x, sofr)
        usd_net = sc.apply_fees(sc.usd_index(nav_x, usdt_usd), cfg["share_classes"]["management_fee"],
                                cfg["share_classes"]["performance_fee"])["nav"]
        lev[Lx] = {"ann_return": s_x["ann_return"], "sharpe": s_x["sharpe"], "max_drawdown": s_x["max_drawdown"],
                   "usd_class_net_ann_return": risk.stats(usd_net)["ann_return"],
                   "liquidation_flags": int(len(flagged)), "flags": []}
        for t in flagged:                    # the hour's bars on each venue, to judge whether it was a wick
            row_ = {"hour_end": str(t), "venues": [f.split("_", 1)[1] for f in lx.at[t, "flags"].split(",") if f.startswith("liquidation_")]}
            for key, k in (("binance_perp", "perp_bn_1h"), ("bybit_perp", "perp_bb_1h"), ("binance_spot", "spot_bn_1h")):
                bar = raw[k].loc[raw[k]["open_time"] + pd.Timedelta(hours=1) == t]
                if len(bar):
                    row_[key] = {"open": float(bar["open"].iloc[0]), "high": float(bar["high"].iloc[0]),
                                 "close": float(bar["close"].iloc[0]), "high_vs_open": float(bar["high"].iloc[0] / bar["open"].iloc[0] - 1)}
            lev[Lx]["flags"].append(row_)
    # leverage as a trade-off: return against modelled annual liquidation probability (engine lag)
    pe = fr[fr["topup_lag_h"] == lag].set_index("leverage")
    pt = fr_target[fr_target["topup_lag_h"] == lag].set_index("leverage")
    ref = cfg["margin"]["reference_probability_annual"]
    res["leverage_tradeoff"] = {
        "base_case_leverage": L, "topup_lag_h": lag, "reference_probability_annual": ref,
        "rows": {str(Lx): {"master_ann_return": lev[Lx]["ann_return"], "master_sharpe": lev[Lx]["sharpe"],
                           "usd_class_net_ann_return": lev[Lx]["usd_class_net_ann_return"],
                           "p_annual_target_margin": float(pt.loc[Lx, "p_annual"]), "p_annual_band_edge": float(pe.loc[Lx, "p_annual"]),
                           "empirical_episodes_band_edge": int(pe.loc[Lx, "episodes"]),
                           "backtest_liquidation_flags": lev[Lx]["liquidation_flags"]} for Lx in lev},
        "base_case_above_reference": bool(pe.loc[L, "p_annual"] > ref),
        "base_case_band_edge_from_tail_only": bool(pe.loc[L, "episodes"] == 0 and pe.loc[L, "p_annual"] == pe.loc[L, "p_annual_evt"])}
    cash_usd = (1 + sofr.reindex(nav.index).ffill().bfill() / 360).cumprod()
    on = lambda x: x.reindex(nav.index).ffill().bfill()
    res["rates"] = {"window": [str(nav.index[0].date()), str(nav.index[-1].date())],
                    "sofr_mean": float(on(sofr).mean()), "tona_mean": float(on(tona).mean()), "krw_3m_mean": float(on(krw_rate).mean()),
                    "sofr_calendar_years": ydict(risk.calendar_returns(cash_usd)),
                    "master_minus_sofr_calendar_years": ydict(risk.calendar_returns(nav) - risk.calendar_returns(cash_usd))}
    res["master"] = {"candidates": cand, "chosen": master, "rule": cfg["master"]["rule"], "comparison_from": str(common.date()),
                     "stats": risk.stats(nav, sofr), "calendar_years": ydict(risk.calendar_returns(nav)),
                     "attribution_log_ann": attribution, "max_abs_identity_error_usdt": float(led["check"].abs().max()),
                     "cost_sensitivity_ann_return": sens, "leverage_ann_return": lev,
                     "beta_btc": risk.beta(nav, btc_usd)}
    pd.DataFrame({"nav_usdt": nav}).to_csv(OUT / "master_nav_daily.csv", float_format="%.2f")
    log.info("master: %s", master)

    # ---- share classes
    scfg = cfg["share_classes"]
    usdt_idx = nav / nav.iloc[0]
    usd_idx = sc.usd_index(nav, usdt_usd)
    gross = {"USDT": usdt_idx, "USD": usd_idx}
    hedged = {}
    for ccy, fx, rate in (("JPY", usdjpy, tona), ("KRW", usdkrw, krw_rate)):
        hedged[ccy] = sc.hedged_class(usd_idx, fx, sofr, rate, scfg["cross_currency_basis_bps"][ccy] / 1e4)
        gross[f"{ccy} hedged"] = hedged[ccy]["index"]
    tc = cfg["venues"]["binance"]["perp_taker"] + cfg["costs"]["perp_half_spread_bps"] / 1e4
    hedge_pnl = {"perp": sc.hedge_pnl_per_btc(pf, "binance", H), "quarterly": sc.hedge_pnl_per_btc(qf, "binance_q", H)}
    btc_perp = sc.btc_class(usd_idx, btc_usd, hedge_pnl["perp"], scfg["btc_hedge_margin"], tc)
    btc_coin = sc.btc_class(usd_idx, btc_usd, hedge_pnl["perp"], scfg["btc_hedge_margin"], tc, margin_in_btc=True)
    btc_netted = sc.btc_class(usd_idx, btc_usd, hedge_pnl["perp"], 0.0, tc)
    gross["BTC hedged"] = btc_perp["index"]
    qstart = qf.index[0].tz_localize(None).normalize() + pd.Timedelta(days=1)
    usd_q = usd_idx.loc[qstart:] / usd_idx.loc[qstart:].iloc[0]
    btc_q = sc.btc_class(usd_q, btc_usd, hedge_pnl["quarterly"], scfg["btc_hedge_margin"], tc)
    btc_perp_q = btc_perp["index"].loc[qstart:] / btc_perp["index"].loc[qstart:].iloc[0]
    bx = btc_usd.reindex(usd_idx.index).ffill()
    unhedged_btc = usd_idx / (bx / bx.iloc[0])
    rf = {"USDT": (sofr, 360), "USD": (sofr, 360), "JPY hedged": (tona, 365), "KRW hedged": (krw_rate, 365), "BTC hedged": (None, 365)}
    net, cls = {}, {}
    for k in CLASSES:
        fees = sc.apply_fees(gross[k], scfg["management_fee"], scfg["performance_fee"])
        net[k] = fees["nav"]
        r_, dc = rf[k]
        cls[k] = {"gross": risk.stats(gross[k], r_, dc), "net": risk.stats(net[k], r_, dc),
                  "net_calendar_years": ydict(risk.calendar_returns(net[k])),
                  "fees_paid_ann": float((fees["mgmt_fee"].sum() + fees["perf_paid"].sum()) / fees["assets"].mean()
                                         / ((fees.index[-1] - fees.index[0]).days / 365.25)),
                  "gross_minus_usd_ann": float(risk.stats(gross[k])["ann_return"] - risk.stats(usd_idx)["ann_return"])}
    sens_basis = {}
    for ccy, fx, rate in (("JPY", usdjpy, tona), ("KRW", usdkrw, krw_rate)):
        h2 = sc.hedged_class(usd_idx, fx, sofr, rate, scfg["basis_sensitivity_bps"][ccy] / 1e4)
        sens_basis[ccy] = {"basis_bps": scfg["basis_sensitivity_bps"][ccy], "gross_ann_return": risk.stats(h2["index"])["ann_return"]}
    hedge_cost_by_year = {}
    for ccy in ("JPY", "KRW"):
        hedge_cost_by_year[ccy] = ydict(risk.calendar_returns(gross[f"{ccy} hedged"]) - risk.calendar_returns(usd_idx))
    hedge_cost_by_year["BTC (perp hedge)"] = ydict(risk.calendar_returns(gross["BTC hedged"]) - risk.calendar_returns(usd_idx))
    f_bar = float(pf["f_binance"].sum() / years)
    res["classes"] = {
        "stats": cls, "basis_sensitivity": sens_basis, "hedge_cost_by_year": hedge_cost_by_year,
        "btc_hedge_instrument": {"from": str(qstart.date()), "perp": risk.stats(btc_perp_q)["ann_return"],
                                 "quarterly": risk.stats(btc_q["index"])["ann_return"],
                                 "margin_shortfall_days": int(btc_perp["margin_shortfall"].sum())},
        "btc_construction": {
            "usdt_margin_not_netted": {"ann_return": cls["BTC hedged"]["gross"]["ann_return"],
                                       "predicted": (1 - scfg["btc_hedge_margin"]) * cls["USD"]["gross"]["ann_return"] - f_bar},
            "coin_margined_not_netted": {"ann_return": risk.stats(btc_coin["index"])["ann_return"],
                                         "predicted": (1 - scfg["btc_hedge_margin"]) * (cls["USD"]["gross"]["ann_return"] - f_bar)},
            "netted": {"ann_return": risk.stats(btc_netted["index"])["ann_return"],
                       "predicted": cls["USD"]["gross"]["ann_return"] - f_bar, "minus_f_over_L_plus_1": -f_bar / (L + 1)}},
        "btc_class_calendar_years_gross": ydict(risk.calendar_returns(gross["BTC hedged"])),
        "btc_unhedged_translation": risk.stats(unhedged_btc), "hold_btc_usd": risk.stats(bx),
        "btc_class_algebra": {"funding_ann": f_bar, "L": L, "m": scfg["btc_hedge_margin"],
                              "master_gross_ann": cls["USD"]["gross"]["ann_return"],
                              "predicted": (1 - scfg["btc_hedge_margin"]) * cls["USD"]["gross"]["ann_return"] - f_bar,
                              "observed": cls["BTC hedged"]["gross"]["ann_return"]},
        "usdt_peg": {"min": float(usdt_close.min()), "min_date": str(usdt_close.idxmin().date()),
                     "usd_minus_usdt_ann": float(cls["USD"]["gross"]["ann_return"] - cls["USDT"]["gross"]["ann_return"])},
    }
    pd.DataFrame({k: net[k] for k in CLASSES}).to_csv(OUT / "class_nav_net.csv", float_format="%.4f")
    pd.DataFrame({k: gross[k] for k in CLASSES} | {"BTC unhedged (reference)": unhedged_btc}).to_csv(OUT / "class_index_gross.csv", float_format="%.6f")
    log.info("classes done")

    # ---- counterparty
    share = cp.exposures(led, list(cfg["strategy"]["weights"]), H)
    share.index = share.index.tz_localize(None).normalize()
    el = cp.expected_loss(share, cfg["counterparty"]["pd_annual"], cfg["counterparty"]["lgd_usd"])
    el.to_csv(OUT / "counterparty_expected_loss.csv", index=False, float_format="%.6f")
    rec = cp.ftx_recovery(cfg["counterparty"]["ftx"], btc_usd, usd_idx)
    pdate = pd.Timestamp(cfg["counterparty"]["ftx"]["petition_date"])
    replay = cp.default_replay(share.loc[pdate], rec, scfg["btc_hedge_margin"], "binance")
    res["counterparty"] = {"exposure_share_mean": share.mean().to_dict(), "exposure_share_max": share.max().to_dict(),
                           "exposure_share_on_petition_date": share.loc[pdate].to_dict(), "expected_loss": el.to_dict("records"),
                           "ftx_recovery": rec, "default_replay": replay.to_dict("records")}
    log.info("counterparty done")

    # ---- 10 October 2025
    st = cfg["stress"]
    t0 = pd.Timestamp(st["oct10_start"], tz="UTC")
    row = led.loc[t0]
    sp1, pb1, pby1 = raw["spot_bn_1m_oct2025"], raw["perp_bn_1m_oct2025"], raw["perp_bb_1m_oct2025"]
    px = lambda k: float(k.loc[k["open_time"] < t0, "close"].iloc[-1])
    Q = float(row["Q"])
    w = cfg["strategy"]["weights"]
    state = {"nav": float(row["nav"]), "Q": Q, "n": {v: w[v] * Q for v in w}, "E": {v: float(row[f"E_{v}"]) for v in w},
             "S0": px(sp1), "F0": {"binance": px(pb1), "bybit": px(pby1)}}
    res["stress_oct10"] = stress.oct10(sp1, {"binance": pb1, "bybit": pby1}, state, t0, pd.Timestamp(st["oct10_end"], tz="UTC"),
                                       st["readd_minutes"], {v: cfg["venues"][v]["maintenance_margin"] for v in w})
    day = nav.loc["2025-10-09":"2025-10-12"]
    res["stress_oct10"]["master_daily_returns"] = {str(k.date()): float(v) for k, v in day.pct_change().dropna().items()}
    log.info("stress done")

    if not args.no_figures:
        from . import factsheet, plots
        plots.make_all(cfg, res, raw, pf, qf, cme, weekly, bp, daily_tab, fr, led, nav, gross, net, unhedged_btc, bx, hedged,
                       btc_perp, share, FIG)
        for k in CLASSES:
            factsheet.build(cfg, res, k, net[k], gross[k], REP / f"factsheet_{k.lower().replace(' ', '_')}.pdf")
        log.info("figures and factsheets done")
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=lambda x: x.isoformat() if hasattr(x, "isoformat")
                                                 else (float(x) if isinstance(x, (np.floating, np.integer)) else str(x))))
    # chapter 2: a BTC-native yield from options (needs this run's BTC class, written above)
    from .vol_overlay import pipeline as vol
    vol.main(cfg, raw, figures=not args.no_figures)
    log.info("done")


if __name__ == "__main__":
    main()
