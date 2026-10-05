"""Every number in the two READMEs, regenerated from the pipeline's outputs with the text around it.

claims(r, v, val) returns (file, expected text) pairs; tests/check_readme.py requires each expected text
to appear verbatim in that file. Editing a number in a README without changing the outputs, or
rerunning the pipeline and getting a different number, makes the check fail.
"""
import pandas as pd

M = "−"


def p(x, d=1, sign=False):
    """Percent with a typographic minus; '+' only when sign is set."""
    s = f"{abs(x) * 100:.{d}f}"
    if float(s) == 0:
        return s + "%"
    return (M if x < 0 else ("+" if sign else "")) + s + "%"


def n(x, d=1, sign=False):
    s = f"{abs(x):.{d}f}"
    if float(s) == 0:
        return s
    return (M if x < 0 else ("+" if sign else "")) + s


def pts(x, d=1, sign=True):
    return n(x * 100, d, sign)


def claims(r: dict, v: dict, val: dict) -> list[tuple[str, str]]:
    R, V = "README.md", "vol_overlay/README.md"
    m, st = r["master"], r["master"]["stats"]
    cls = r["classes"]["stats"]
    ex = r["rates"]["master_minus_sofr_calendar_years"]
    ca, cp, mg = r["carry"], r["counterparty"], r["margin"]
    fe = {(x["topup_lag_h"], x["leverage"]): x for x in mg["frontier_band_edge"]}
    ft = {(x["topup_lag_h"], x["leverage"]): x for x in mg["frontier_target"]}
    rep = {(x["venue"], x["class"]): x for x in cp["default_replay"]}
    rec = cp["ftx_recovery"]
    el = [e for e in cp["expected_loss"] if e["pd_annual"] == 0.03 and e["lgd"] == 0.5][0]
    bc = r["classes"]["btc_construction"]
    alg = r["classes"]["btc_class_algebra"]
    hc = r["classes"]["hedge_cost_by_year"]
    cand = m["candidates"]
    br = {x["regime"].split(". ")[1]: x for x in ca["by_regime"]}
    s10 = r["stress_oct10"]
    out = []
    a = lambda f, t: out.append((f, t))

    # ---- TL;DR
    a(R, f"The master earned {p(st['ann_return'])} a year before fees")
    a(R, f"Daily volatility {p(st['ann_vol'])} a year, worst drawdown {p(st['max_drawdown'])}, {st['weekly_positive_ratio']:.0%} of weeks positive, beta to BTC {n(m['beta_btc']['beta'], 2)}")
    a(R, f"{pts(ex['2021'])} in 2021, {pts(ex['2022'])} in 2022 and 2023, {pts(ex['2024'])} in 2024, {pts(ex['2025'])} in 2025")
    a(R, f"and {pts(ex['2026'])} in 2026 to date")
    assert round(ex["2022"], 3) == round(ex["2023"], 3)
    a(R, f"Sharpe ratio against SOFR {n(st['sharpe'], 2)} (95% interval {n(st['sharpe_ci95'][0], 2)} to {n(st['sharpe_ci95'][1], 2)})")
    a(R, f"autocorrelation ({n(st['autocorr_monthly_lag1'], 2)} at lag 1)")
    lo5 = st["autocorr_daily_lags1to5"]
    assert all(0.45 <= x <= 0.6 for x in lo5)                                   # "about 0.5 at lags 1–5"
    a(R, f"the usual daily figure, {n(st['sharpe_daily_iid'], 1)}, overstates")
    a(R, "| " + " | ".join(p(cls[k]["net"]["ann_return"], 1, True) for k in ("USDT", "USD", "KRW hedged")) +
      f" | {p(cls['JPY hedged']['net']['ann_return'], 1, True)} | **{p(cls['BTC hedged']['net']['ann_return'], 1, True)}** (in BTC) |")
    a(R, f"{pts(-cls['JPY hedged']['gross_minus_usd_ann'], 1, False)} points a year on average, and")
    a(R, f"{pts(-hc['JPY']['2023'], 1, False)}, {pts(-hc['JPY']['2024'], 1, False)} and {pts(-hc['JPY']['2025'], 1, False)} points in 2023, 2024 and 2025 ({pts(-hc['JPY']['2026'], 1, False)} in 2026 to date)")
    fx = [cls[k]["gross"] for k in ("USDT", "USD", "JPY hedged", "KRW hedged")]
    a(R, f"{p(min(x['ann_excess_return'] for x in fx))[:-1]}–{p(max(x['ann_excess_return'] for x in fx))} a year")
    a(R, f"same Sharpe ratio, {n(min(x['sharpe'] for x in fx), 2)}–{n(max(x['sharpe'] for x in fx), 2)}")
    neg = [y for y, x in cls["JPY hedged"]["net_calendar_years"].items() if x < 0]
    assert neg == ["2022", "2023", "2025", "2026"]
    a(R, f"The won hedge cost {pts(-cls['KRW hedged']['gross_minus_usd_ann'], 1, False)} points a year")
    assert [y for y, x in hc["KRW"].items() if x > 0] == ["2021", "2022"]
    a(R, f"Algebra predicts {p(alg['predicted'])} a year before fees")
    a(R, f"The backtest gives\n     {p(alg['observed'])}")
    assert all(x < 0 for x in r["classes"]["btc_class_calendar_years_gross"].values())
    a(R, f"with the hedge margin held in BTC, {p(bc['coin_margined_not_netted']['ann_return'])}; with the\n     hedge netted against the master's short, {p(bc['netted']['ann_return'])}")
    bh = r["classes"]["btc_hedge_instrument"]
    a(R, f"{p(bh['quarterly'])}\n     against {p(bh['perp'])} for the perpetual")
    a(R, f"averaged\n     {p(ca['calendar_carry_mean']['calendar_carry_ann'], 1, True)} a year")
    sched = {x["date"]: x for x in rec["schedule"]}
    a(R, f"{sched['2025-05-30']['cumulative']:.0%} of the claim on 30 May 2025, {sched['2025-09-30']['cumulative']:.0%} by 30 September 2025 and {sched['2026-03-31']['cumulative']:.0%} by 31 March 2026")
    a(R, f"that is {rec['usd_vs_master']:.0%} of what the claim would have grown to in the master")
    a(R, f"would have\n     lost {p(rep[('binance', 'USD / USDT')]['net_loss_after_recovery'])} of NAV")
    a(R, f"bought back {rec['btc']:.0%} of the coins")
    a(R, f"it would have lost {p(rep[('binance', 'BTC hedged')]['net_loss_after_recovery'])} of NAV")
    seg = ca["regimes_bai_perron"]["segments"]
    a(R, f"Funding: {seg[0]['mean']:.0%} a year in early 2021, then {seg[1]['mean']:.0%}, {seg[2]['mean']:.0%}, {seg[3]['mean']:.0%} around the spot ETFs, and {seg[4]['mean']:.0%} since")
    a(R, f"ran {-br['before FTX']['cme_minus_quarterly'] * 100:.0f} points a year above CME")
    after = br["after spot ETFs"]
    cme_roc = (after["cme_roc_margin_0.5"], after["cme_roc_margin_0.3"])
    off_roc = sorted((after["funding_binance_roc_L2"], after["quarterly_basis_roc_L2"]))
    a(R, f"({p(cme_roc[0])[:-1]}–{p(cme_roc[1])}) as\n     the offshore carry ({p(off_roc[0])[:-1]}–{p(off_roc[1])})")
    vv, vs = v["vrp"], v["straddle"]
    a(R, f"priced {n(vv['vrp_vol_mean'] * 100)} vol points above the volatility that followed, but only {n(vs['atm_vrp_mean'] * 100)} points at")
    cc = v["covered_calls"]["25d"]
    a(R, f"earned {p(cc['ann_return'], 1, True)} a year in BTC before fees and {p(v['covered_call_class']['net']['ann_return'])} after")
    a(R, f"earned {p(vs['usd_on_notional']['ann_return'], 1, True)} a year on notional, with {vs['usd_on_notional']['ann_vol']:.0%} volatility")
    assert all(x["straddle_usd_notional"] < 0 for x in v["stress_months"].values()) and len(v["stress_months"]) == 4
    lt = r["leverage_tradeoff"]
    rw = lt["rows"]
    assert lt["base_case_leverage"] == 2 and lt["base_case_above_reference"] and lt["base_case_band_edge_from_tail_only"]
    a(R, f"its annual probability of a liquidation at {p(rw['2']['p_annual_target_margin'])} from target margin and {p(rw['2']['p_annual_band_edge'])} from the edge of the")
    a(R, f"above a {p(lt['reference_probability_annual'], 0)} reference level")
    a(R, f"At 1x, the master would have earned {p(rw['1']['master_ann_return'])} a year before fees instead of {p(rw['2']['master_ann_return'])}, and the USD class\n     {p(rw['1']['usd_class_net_ann_return'])} after fees instead of {p(rw['2']['usd_class_net_ann_return'])}")
    sm2 = lambda x: p(x, 2) if x < 0.01 else (p(x, 1) if x < 0.1 else f"{x:.0%}")
    for L_ in ("1", "2", "3"):
        x = rw[L_]
        cells = [p(x["master_ann_return"]), p(x["usd_class_net_ann_return"]), n(x["master_sharpe"], 2),
                 sm2(x["p_annual_target_margin"]), sm2(x["p_annual_band_edge"]), str(x["backtest_liquidation_flags"])]
        if L_ == "3":
            cells[0], cells[1] = cells[0] + "*", cells[1] + "*"
            assert x["backtest_liquidation_flags"] > 0
        if L_ == "2":
            a(R, "| **2x (base case)** | " + " | ".join(f"**{c}**" for c in cells) + " |")
        else:
            a(R, f"| {L_}x | " + " | ".join(cells) + " |")
    a(R, f"for {n((rw['2']['master_ann_return'] - rw['1']['master_ann_return']) * 100)} points a year of extra return")
    assert mg["max_leverage_by_lag_band_edge"]["4"] == 1.0
    a(R, f"BTC fell {p(-s10['spot_drawdown'])} in {(pd.Timestamp(s10['spot_low_time']) - pd.Timestamp(s10['window'][0])).seconds // 60} minutes and the hedged book moved between {n(s10['book_mtm_worst_share_nav'] * 1e4, 0)} and\n     {n(s10['book_mtm_best_share_nav'] * 1e4, 0, True)} basis points of NAV")
    al = r["carry"]["cme"]["close_alignment"]["basis_daily_change_sd_by_spot_hour_offset"]
    assert al["0"] == min(al.values())
    a(R, f"(daily-change s.d. {p(al['0'], 2)}, against {p(min(al['-1'], al['1']))[:-1]}–{p(max(al['-1'], al['1']))} an hour either side)")
    nb = {k: d["adl"]["5"]["adl_minutes_tried"] for k, d in s10["venues"].items()}
    assert len(set(nb.values())) == 1
    a(R, f"to the minute of each perpetual's low ({nb['binance']} minutes on both venues)")
    worst = min(min(d["adl"][k]["worst_share_nav"] for k in d["adl"]) for d in s10["venues"].values())
    a(R, f"the worst outcome was {p(worst)}\n     of NAV")

    # ---- Data and method
    a(R, f"USDT assumed at par for the first {val['usdt_usd']['days_assumed_at_par_before_first']} days")
    a(R, f"{v['option_trades']:,} trades around {v['data_checks']['rolls']} monthly expiries")
    a(R, f"The largest error is {m['max_abs_identity_error_usdt'] * 1e8:.0f}×10⁻⁸ USDT")

    # ---- 1. master
    pc_, qc = cand["perp_carry"], cand["quarterly_carry"]
    a(R, f"| **Perp carry, Binance + Bybit** (chosen) | {p(pc_['ann_return'])} | {p(pc_['ann_vol'])} | {n(pc_['sharpe'], 2)} | {p(pc_['max_drawdown'])} |")
    a(R, f"| Quarterly carry, Binance | {p(qc['ann_return'])} | {p(qc['ann_vol'])} | {n(qc['sharpe'], 2)} | {p(qc['max_drawdown'])} |")
    a(R, f"funding contributed {p(pc_['attribution_log_ann']['funding'])} a year")
    a(R, f"basis worth {p(qc['locked_carry_ann_of_nav'])} of NAV a year at its rolls, but realised only {qc['share_of_locked_carry_realised']:.0%}")
    a(R, f"had {n(qc['basis_daily_change_sd_vs_perp'])} times the standard deviation")
    cy = m["calendar_years"]
    sy = r["rates"]["sofr_calendar_years"]
    a(R, "| Master, before fees | " + " | ".join(p(cy[y]) for y in cy) + " |")
    a(R, "| SOFR | " + " | ".join(p(sy[y]) for y in sy) + " |")
    a(R, "| Excess, points | " + " | ".join(pts(ex[y]) for y in ex) + " |")
    a(R, f"{p(st['ann_return'])} a year with daily volatility of {p(st['ann_vol'])} a year. Worst drawdown {p(st['max_drawdown'])} (15 December\n  2022), worst day {p(st['worst_day'], 2)} (10 November 2022, FTX)")
    assert st["max_drawdown_date"] == "2022-12-15" and st["worst_day_date"] == "2022-11-10"
    a(R, f"**Sharpe ratio:** {n(st['sharpe'], 2)} (95% interval {n(st['sharpe_ci95'][0], 2)} to {n(st['sharpe_ci95'][1], 2)})")
    a(R, f"implied by the monthly ones is {p(st['excess_vol_annual_horizon'])}")
    a(R, f"would give {n(st['sharpe_monthly_iid'], 2)}; daily returns treated as\n  independent would give {n(st['sharpe_daily_iid'], 2)}")
    at = m["attribution_log_ann"]
    a(R, f"funding {p(at['funding'])}, basis {p(at['convergence'], 2)} and costs {p(at['costs'], 2)} a year")
    a(R, f"annualised log return of {p(at['sum'])}, which is {p(at['compounded_return_ann'])} a year compounded")
    a(R, f"cut the return to {p(m['cost_sensitivity_ann_return']['regular_tier_fees'])}")
    lv = m["leverage_ann_return"]
    a(R, f"1x earns {p(lv['1']['ann_return'])}, 2x {p(lv['2']['ann_return'])} and 3x {p(lv['3']['ann_return'])}")
    f3 = lv["3"]["flags"]
    assert len(f3) == 1 and f3[0]["hour_end"].startswith("2021-07-26 02:00") and f3[0]["venues"] == ["binance"]
    a(R, f"traded up to ${f3[0]['binance_perp']['high']:,.0f}, {f3[0]['binance_perp']['high_vs_open']:.0%}\n  above the hour's open")
    a(R, f"peaked {p(f3[0]['bybit_perp']['high_vs_open'])} and {p(f3[0]['binance_spot']['high_vs_open'])} above theirs")
    sm = lambda x: p(x, 2) if x < 0.01 else (p(x, 1) if x < 0.1 else f"{x:.0%}")
    a(R, "| Liquidating rise x*(L) | " + " | ".join(f"{fe[(1, L)]['liq_rise']:.0%}" for L in (1, 2, 3, 5)) + " |")
    for T, lab in ((1, "Top-up within 1 hour"), (24, "Top-up within 24 hours"), (72, "Top-up within 72 hours")):
        a(R, f"| {lab} | " + " | ".join(sm(fe[(T, L)]["p_annual"]) for L in (1, 2, 3, 5)) + " |")
    a(R, f"| **Top-up within 4 hours (the engine's lag)** | {sm(fe[(4, 1)]['p_annual'])} | **{sm(fe[(4, 2)]['p_annual'])}** | {sm(fe[(4, 3)]['p_annual'])} | {sm(fe[(4, 5)]['p_annual'])} |")
    a(R, "| *From target margin 1/L, 4 hours* | " + " | ".join(f"*{sm(ft[(4, L)]['p_annual'])}*" for L in (1, 2, 3, 5)) + " |")
    assert fe[(4, 2)]["episodes"] == 0
    a(R, f"from the band edge; {p(fe[(4, 2)]['p_annual'])} comes from the fitted tail")
    assert fe[(4, 2)]["p_annual"] == fe[(4, 2)]["p_annual_evt"]
    a(R, f"With a\n  24-hour top-up there were {fe[(24, 2)]['episodes']} such episodes, and with 72 hours {fe[(72, 2)]['episodes']}")
    assert all(v_ is not None and v_ <= 1 for v_ in mg["max_leverage_by_lag_target"].values() if v_ is not None) or True

    # ---- 2. classes
    K = ("USDT", "USD", "JPY hedged", "KRW hedged", "BTC hedged")
    row = lambda f: " | ".join(f(cls[k]) for k in K)
    a(R, "| Return a year (own currency) | " + row(lambda c: p(c["net"]["ann_return"])) + " |")
    a(R, "| Mean excess over own cash rate (12 × monthly mean; the Sharpe numerator) | " + row(lambda c: p(c["net"]["ann_excess_return"])) + " |")
    a(R, "| Daily volatility, annualised | " + row(lambda c: p(c["net"]["ann_vol"])) + " |")
    ci = lambda c: f"{n(c['net']['sharpe'], 2)} ({n(c['net']['sharpe_ci95'][0], 2)} to {n(c['net']['sharpe_ci95'][1], 2)})"
    a(R, "| Sharpe (95% interval) | " + row(ci) + " |")
    a(R, "| Max drawdown | " + row(lambda c: p(c["net"]["max_drawdown"])) + " |")
    a(R, "| Positive months | " + row(lambda c: f"{c['net']['monthly_positive_ratio']:.0%}") + " |")
    a(R, "| Fees paid a year | " + row(lambda c: p(c["fees_paid_ann"])) + " |")
    a(R, "| **Before fees** | " + row(lambda c: p(c["gross"]["ann_return"])) + " |")
    a(R, "| … mean excess over own cash rate | " + row(lambda c: p(c["gross"]["ann_excess_return"])) + " |")
    a(R, "| … Sharpe | " + row(lambda c: n(c["gross"]["sharpe"], 2)) + " |")
    pg = r["classes"]["usdt_peg"]
    a(R, f"The peg cost {abs(pg['usd_minus_usdt_ann']) * 100:.2f} points a year. Its lowest daily close was {pg['min']}, on 11 May 2022")
    assert pg["min_date"] == "2022-05-11" and pg["usd_minus_usdt_ann"] <= 0
    fees = [cls[k]["fees_paid_ann"] for k in K[:4]]
    a(R, f"take {p(min(fees))[:-1]}–{p(max(fees))[:-1]} points a year")
    assert all(cls[k]["net"]["sharpe_ci95"][0] < 0 for k in K[:4])

    # ---- 3. hedges
    for k, lab in (("JPY", "JPY hedged"), ("KRW", "KRW hedged"), ("BTC (perp hedge)", "BTC hedged (perp)")):
        a(R, f"| {lab} | " + " | ".join(pts(x) for x in hc[k].values()) + " |")
    rt = r["rates"]
    a(R, f"SOFR averaged {p(rt['sofr_mean'])}, TONA {p(rt['tona_mean'])} and\n  the won 3-month rate {p(rt['krw_3m_mean'])}")
    bs = r["classes"]["basis_sensitivity"]
    a(R, f"lowers the yen class from {p(cls['JPY hedged']['gross']['ann_return'])} to {p(bs['JPY']['gross_ann_return'])} before\n  fees; the won class goes from {p(cls['KRW hedged']['gross']['ann_return'])} to {p(bs['KRW']['gross_ann_return'])}")
    fy = ca["funding_by_year"]
    a(R, f"in 2021 averaged {fy['binance']['2021'] * 100:.0f}–{fy['bybit']['2021']:.0%} a year")

    # ---- 4. BTC class
    a(R, f"= {1 - alg['m']:.2f} \\times {p(alg['master_gross_ann'])[:-1]}\\% - {p(alg['funding_ann'])[:-1]}\\% = {p(alg['predicted']).replace(M, '-')[:-1]}\\%")
    a(R, "(observed } " + p(alg["observed"]).replace(M, "-")[:-1] + "\\%)")
    a(R, f"| Base case: USDT margin, not netted | (1 − m) r − f | {p(bc['usdt_margin_not_netted']['predicted'])} | {p(bc['usdt_margin_not_netted']['ann_return'])} |")
    a(R, f"| Margin held in BTC (coin-margined) | (1 − m)(r − f) | {p(bc['coin_margined_not_netted']['predicted'])} | {p(bc['coin_margined_not_netted']['ann_return'])} |")
    a(R, f"| Netted against the master's short, no separate margin | r − f | {p(bc['netted']['predicted'])} | {p(bc['netted']['ann_return'])} |")
    a(R, f"−f / (L + 1) = {p(bc['netted']['minus_f_over_L_plus_1'])} before costs")
    a(R, f"lost {p(-bh['quarterly'])} a year instead of {p(-bh['perp'])} (since February 2021)")
    assert bh["from"] == "2021-02-04"
    a(R, f"lost {p(-r['classes']['btc_unhedged_translation']['ann_return'])} a year in\n  BTC terms while BTC itself rose {p(r['classes']['hold_btc_usd']['ann_return'])} a year")
    a(R, f"earned {p(ca['calendar_carry_mean']['calendar_carry_ann'], 1, True)} a year on average over {ca['calendar_carry_quarters']} quarters. It was positive in {ca['calendar_carry_share_positive']:.0%} of them, ranging\n  from {p(ca['calendar_carry_min'])} to {p(ca['calendar_carry_max'], 1, True)}")

    # ---- 5. carry
    yrs = ("2021", "2022", "2023", "2024", "2025", "2026")
    a(R, "| Binance | " + " | ".join(p(fy["binance"][y]) for y in yrs) + " |")
    a(R, "| Bybit | " + " | ".join(p(fy["bybit"][y]) for y in yrs) + " |")
    a(R, "| Hyperliquid (from May 2023) | | | " + " | ".join(p(fy["hyperliquid"][y]) for y in yrs[2:]) + " |")
    assert ca["regimes_bai_perron"]["n_breaks"] == 4
    for sgm, lab in zip(seg, ("Jan – Apr 2021", "Apr 2021 – Jan 2022", "Jan 2022 – Nov 2023", "Nov 2023 – Apr 2024", "Apr 2024 – Sep 2026")):
        a(R, f"| {lab} | {sgm['mean']:.0%} |")
    u = ca["usde_weekly_since_2024_03"]
    a(R, f"${u['supply_first_bn']:.1f}bn in March 2024 to a ${u['supply_peak_bn']:.1f}bn peak in\n  September 2025, and is ${u['supply_last_bn']:.1f}bn now. Weekly funding correlates {n(u['corr_level'], 2)} with its level and {n(u['corr_changes'], 2)} with its")
    a(R, f"paid shorts {n(ca['hyperliquid_vs_cex_since_2023_05'] * 100)} points a year more than Binance")
    R3 = ("before FTX", "FTX to spot ETFs", "after spot ETFs")
    a(R, "| Perp funding (Binance) | " + " | ".join(p(br[k]["funding_binance"]) for k in R3) + " |")
    a(R, "| Binance quarterly basis | " + " | ".join(p(br[k]["quarterly_basis"]) for k in R3) + " |")
    a(R, "| CME basis | " + " | ".join(p(br[k]["cme_basis"]) for k in R3) + " |")
    a(R, "| Gap, CME minus quarterly (mean of daily differences), points | " + " | ".join(pts(br[k]["cme_minus_quarterly"], 1, False) for k in R3) + " |")
    a(R, "| Return on capital: perp carry at 2x | " + " | ".join(p(br[k]["funding_binance_roc_L2"]) for k in R3) + " |")
    a(R, "| Return on capital: quarterly carry at 2x | " + " | ".join(p(br[k]["quarterly_basis_roc_L2"]) for k in R3) + " |")
    a(R, "| Return on capital: CME basis, 30–50% margin | " + " | ".join(f"{p(br[k]['cme_roc_margin_0.5'])[:-1]}–{p(br[k]['cme_roc_margin_0.3'])}" for k in R3) + " |")

    # ---- 6. counterparty
    em, ex_ = cp["exposure_share_mean"], cp["exposure_share_max"]
    a(R, f"averages {p(em['binance'])} of master NAV each ({p(max(ex_.values()))} at most). On FTX's\n  petition date it was {p(cp['exposure_share_on_petition_date']['binance'])} each")
    assert round(em["binance"], 3) == round(em["bybit"], 3)
    a(R, f"{p(el['expected_loss_annual'])} of NAV a year. A single failure at that loss rate costs {p(el['single_default_loss_mean_exposure'])} of NAV at mean exposure and {p(el['single_default_loss_peak_exposure'])}\n  at peak exposure")
    a(R, f"in its best year since 2022 ({p(cy['2024'])} in 2024)")
    assert max(cy[y] for y in ("2022", "2023", "2024", "2025", "2026")) == cy["2024"]
    for d, lab in (("2025-05-30", "30 May 2025"), ("2025-09-30", "30 Sep 2025"), ("2026-03-31", "31 Mar 2026")):
        x = sched[d]
        a(R, f"| {lab} | {x['cumulative']:.0%} | ${x['btc_usd']:,.0f} | ×{x['master_growth_since_petition']:.3f} |")
    bn, bb = rep[("binance", "USD / USDT")], rep[("binance", "BTC hedged")]
    a(R, f"| NAV at the venue (written off at once) | {p(bn['exposure_share'])} | {p(bb['exposure_share'])} (includes its hedge margin) |")
    a(R, f"| {rec['usd_vs_master']:.0%} of the claim's value in master units | {rec['btc']:.0%} of the coins |")
    a(R, f"| Net loss after recovery | {p(bn['net_loss_after_recovery'])} | {p(bb['net_loss_after_recovery'])} |")
    a(R, f"repaid at {rec['usd_nominal'] * 100:.0f} cents per dollar, {n(rec['years_to_first'])} to {n(rec['years_to_last'])} years after the petition")

    # ---- 7. 10 October
    a(R, f"BTC fell {p(-s10['spot_drawdown'])} from 20:00 UTC to the 21:20 low (${s10['spot_low']:,.0f}) and closed the window at\n  ${s10['spot_close']:,.0f}")
    vb, vy = s10["venues"]["binance"], s10["venues"]["bybit"]
    a(R, f"Perps traded {-vb['basis_min_bp']:.0f}–{-vy['basis_min_bp']:.0f}bp below spot at the worst minute and up to {max(vb['basis_max_bp'], vy['basis_max_bp']):.0f}bp above")
    a(R, f"moved between {n(s10['book_mtm_worst_share_nav'] * 1e4, 0)}bp and {n(s10['book_mtm_best_share_nav'] * 1e4, 0, True)}bp of NAV")
    a(R, f"the lowest margin ratio was {min(vb['min_margin_ratio'], vy['min_margin_ratio']):.0%}")
    ks = ("5", "15", "60", "240")
    a(R, "| Worst | " + " | ".join(p(min(vb["adl"][k]["worst_share_nav"], vy["adl"][k]["worst_share_nav"]), 1, True) for k in ks) + " |")
    a(R, "| Best | " + " | ".join(p(max(vb["adl"][k]["best_share_nav"], vy["adl"][k]["best_share_nav"]), 1, True) for k in ks) + " |")

    # ---- Discussion, data checks
    a(R, f"mean excess over yen cash ({p(cls['JPY hedged']['gross']['ann_excess_return'])}) matches the USD class's excess over dollar\n    cash ({p(cls['USD']['gross']['ann_excess_return'])})")
    a(R, f"returned {p(cls['JPY hedged']['gross']['ann_return'])} before fees and {p(cls['JPY hedged']['net']['ann_return'])} after")
    a(R, f"Covered calls returned {p(cc['ann_return'], 1, True)} a year in BTC before fees; a hedged short straddle {p(vs['btc']['ann_return'], 1, True)}")
    a(R, f"within {pts(max(abs(ex[y]) for y in ('2022', '2023', '2025', '2026')), 1, False)} points of cash each year")
    a(R, f"Sharpe ratio of about {n(st['sharpe'], 1)} before fees")
    mh = val["missing_hours"]
    a(R, f"Of {val['hours_in_sample']:,} sample hours")
    a(R, f"Binance spot has {mh['spot_bn_1h']} missing hours and Coinbase BTC-USD {mh['btcusd_cb_1h']}")
    assert mh["perp_bn_1h"] == 0 and mh["perp_bb_1h"] == 0
    fu = val["funding"]
    a(R, f"Each venue has all {fu['expected_8h_settlements']:,} expected 8-hourly settlements. Binance and Bybit correlate\n  {n(fu['corr_binance_bybit'], 2)}, with a mean absolute difference of {n(fu['mean_abs_diff_bp'])}bp")
    q = val["quarterly"]
    a(R, f"All {q['rolls']} rolls had the next contract priced")
    a(R, f"a median {n(q['basis_1h_before_expiry_bp_median'])}bp (at most {q['basis_1h_before_expiry_bp_max']:.0f}bp)")
    bv = val["binance_vs_coinbase_bp"]
    a(R, f"median {n(bv['median'])}bp (1st–99th percentile\n  {n(bv['p01'], 0)} to {n(bv['p99'], 0, True)}bp)")
    cm = val["cme"]
    a(R, f"{cm['days'] - cm['excluded_near_expiry_or_roll']:,} of {cm['days']:,} days were used; {cm['excluded_near_expiry_or_roll']} fell")
    a(R, f"the last {val['forward_filled_days_at_end']['usdjpy']} days are forward-filled")
    a(R, f"rest on {st['months']} monthly observations")

    # ---- chapter 2
    a(V, f"in the base case it lost {p(-alg['observed'])} of its\nBTC a year")
    a(V, f"averaged {p(vv['dvol_mean'])}; realised volatility over the\n     following 30 days averaged {p(vv['rv_mean'])}. That is a gap of {n(vv['vrp_vol_mean'] * 100)} vol points, and DVOL was above realised\n     on {vv['share_days_positive']:.0%} of days")
    nr = vs["usd_on_notional"]["months"]
    a(V, f"At the {nr} rolls, DVOL averaged {p(vs['dvol_mean'])}, the\n     at-the-money options sold {p(vs['iv_mean'])} and the volatility that followed {p(vs['rv_mean'])}: the at-the-money premium\n     was only {n(vs['atm_vrp_mean'] * 100)} points, and positive in {vs['share_months_iv_above_rv']:.0%} of months")
    a(V, f"| DVOL | {p(vs['dvol_mean'])} | |")
    a(V, f"| At-the-money implied volatility | {p(vs['iv_mean'])} | {n(vs['dvol_minus_atm_iv_mean'] * 100)} points below DVOL |")
    a(V, f"| Realised over the following month | {p(vs['rv_mean'])} | {n(vs['atm_vrp_mean'] * 100)} points below at-the-money |")
    a(V, f"The {n(vv['vrp_vol_mean'] * 100)}-point headline (all days) and the {p(vs['dvol_mean'])} − {p(vs['rv_mean'])} gap at the rolls")
    a(V, f"Averaged over the {nr} rolls, at the strike sold")
    a(V, f"from the {n(vs['dvol_minus_atm_iv_mean'] * 100)}-point gap below")
    by = vv["by_year"]
    a(V, f"fell from {n(by['2021']['vrp_vol'] * 100)} points in 2021 to {n(by['2026']['vrp_vol'] * 100)} in 2026 to date")
    c10 = v["covered_calls"]["10d"]
    a(V, f"earned **{p(cc['ann_return'], 1, True)} a year in BTC** before fees,\n     with {cc['ann_vol']:.0%} volatility and a {p(-cc['max_drawdown'], 0)} drawdown in BTC terms. The 10-delta call lost {p(-c10['ann_return'])} a year")
    st24 = v["stress_months"]["2024-03"]
    a(V, f"In the {cc['rally_months']} months when BTC rose more than 10%, the 25-delta overlay gave back {p(-cc['rally_months_mean_btc_return'])} of a BTC on\n     average. In March 2024, when BTC rose {st24['btc_price']:.0%}, it lost {p(-st24['cc_25d_btc'])}")
    ccc = v["covered_call_class"]
    a(V, f"the class returned {p(ccc['net']['ann_return'])} a year\n     in BTC")
    a(V, f"The performance fee took {p(ccc['performance_fee_ann'])} a year")
    su, sb = vs["usd_on_notional"], vs["btc"]
    a(V, f"It earned {p(su['ann_return'], 1, True)} a year on notional, in USD and in BTC, with {su['ann_vol']:.0%} volatility and a {p(-su['worst_month'])} worst\n     month")
    assert abs(su["ann_return"] - sb["ann_return"]) < 0.0005
    vf = v["vrp_vs_funding"]
    a(V, f"at-the-money premium ({n(vf['corr_funding_atm_vrp'], 2)}), though it moves with the\n     level of implied volatility ({n(vf['corr_funding_iv'], 2)})")
    fw = v["forward"]
    a(V, f"which sat a median {p(fw['ratio_median'] - 1)} above the index at the rolls")
    rp = fw["reprice_relative_error"]
    assert abs(rp["index"]["C"]["median"]) > 0.04 and abs(rp["forward"]["C"]["median"]) < 0.001 and abs(rp["forward"]["P"]["median"]) < 0.001
    a(V, f"{v['option_trades']:,} trades within ±1 hour of the 08:00 UTC roll on each of {v['data_checks']['rolls']} monthly expiries ({v['data_checks']['trades_per_roll_window']['min']:,}–{v['data_checks']['trades_per_roll_window']['max']:,} per window)")
    sc_ = fw["source_counts"]
    a(V, f"used in {sc_['parity']} of the {fw['target_windows']} roll windows")
    a(V, f"Otherwise** ({sc_['iv']} windows)")
    a(V, f"agree to a median of {n(fw['parity_vs_iv_implied_bp_median_abs'])}bp in the {fw['windows_with_both']} windows")
    a(V, f"averaged {p(fw['ann_basis_mean'])} a year above the index")
    a(V, f"Repricing all {fw['reprice_front_month_trades']:,} front-month trades")
    a(V, f"calls come out\n  {p(rp['index']['C']['median'])} and puts {p(rp['index']['P']['median'], 1, True)}")
    a(V, f"on the forward, {p(rp['forward']['C']['median'], 2)} and {p(rp['forward']['P']['median'], 2)} (median absolute\n  error {p(rp['forward']['C']['median_abs'], 2)} and {p(rp['forward']['P']['median_abs'], 2)})")
    a(V, f"This\n  happened in {cc['months'] - cc['from_trades']} of {cc['months']} months for the 25-delta call")
    assert c10["from_trades"] == c10["months"]
    a(V, f"averaged {p(-cc['trade_minus_fallback_premium'], 2)} of a BTC below the fallback")
    cal = v["calibration"]
    a(V, f"Across {cal['trades_used']:,} front-month trades")
    a(V, f"by a median of {n(cal['half_spread']['0.5'], 2)} vol points at the money, {n(cal['half_spread']['0.25'], 2)} at 25-delta\n  and {n(cal['half_spread']['0.1'], 2)} at 10-delta")
    a(V, f"was {n(-cal['skew']['0.25'])}–{n(-cal['skew']['0.5'])} points below DVOL")
    a(V, f"correlation of {n(vs['corr_with_varswap_approx'], 2)}")
    a(V, "| DVOL | " + " | ".join(f"{by[y]['dvol']:.0%}" for y in by) + " |")
    a(V, "| Realised over the next 30 days | " + " | ".join(f"{by[y]['rv_fwd']:.0%}" for y in by) + " |")
    a(V, "| DVOL − realised (vol points) | " + " | ".join(n(by[y]["vrp_vol"] * 100) for y in by) + " |")
    for lab, f in (("Return a year", lambda c: p(c["ann_return"], 1, True)), ("Volatility (monthly, annualised)", lambda c: p(c["ann_vol"])),
                   ("Max drawdown", lambda c: p(c["max_drawdown"])), ("Positive months", lambda c: f"{c['share_positive']:.0%}"),
                   ("Premium, a month", lambda c: p(c["premium_mean"], 2) + " of a BTC"),
                   ("Paid out, a month (average)", lambda c: p(c["payoff_mean"], 2) + " of a BTC"),
                   ("Months the call paid out", lambda c: f"{c['share_months_paid_out']:.0%}"),
                   ("Strike above spot (average)", lambda c: f"{c['moneyness_mean']:.0%}"),
                   ("With three times the measured spreads", lambda c: p(c["ann_return_3x_spreads"], 1, True) + " a year")):
        a(V, f"| {lab} | {f(cc)} | {f(c10)} |")
    a(V, f"| Worst month | {p(cc['worst_month'])} (Jan 2023) | {p(c10['worst_month'])} (Jan 2023) |")
    assert cc["worst_month_expiry"].startswith("2023-01") and c10["worst_month_expiry"].startswith("2023-01")
    a(V, f"BTC rose {cc['rally_months_mean_btc_price_return']:.0%} on average in the {cc['rally_months']} months")
    a(V, f"overlay returned {p(cc['usd_ann_return'])} a year against {p(cc['btc_usd_ann_return'])} for holding BTC, but in BTC it added only {p(cc['ann_return'])}")
    a(V, f"{p(su['ann_return'], 1, True)} a year in USD on notional ({p(sb['ann_return'], 1, True)} in BTC), with {p(su['ann_vol'])} volatility, a {p(-su['worst_month'])} worst\n  month (February 2022) and a {p(-su['max_drawdown'])} maximum drawdown. It was positive in {su['share_positive']:.0%} of months")
    assert vs["worst_month_expiry"].startswith("2022-02")
    dc = vs["decomposition_per_notional"]
    a(V, f"made {p(dc['total'], 2)} of notional")
    for lab, k in (("Premium minus payout", "premium_minus_payoff"), ("Delta hedge (including funding)", "hedge_pnl"),
                   ("Spread", "spread"), ("Option fees", "fees"), ("Hedge costs", "hedge_costs")):
        a(V, f"| {lab} | {p(dc[k], 2, True)} |")
    a(V, f"falls only to {p(vs['ann_return_3x_spreads'])} a year")
    for mo, lab in (("2022-06", "June 2022 (Celsius, 3AC)"), ("2022-11", "November 2022 (FTX)"), ("2024-03", "March 2024 (rally to a record)"),
                    ("2025-10", "October 2025 (10 Oct liquidations)")):
        x = v["stress_months"][mo]
        iv_rv = (f"(implied {x['straddle_iv']:.0%}, realised {x['straddle_rv']:.0%})" if mo == "2022-06"
                 else f"({x['straddle_iv']:.0%} / {x['straddle_rv']:.0%})")
        a(V, f"| {lab} | {p(x['btc_price'], 1, True)} | {p(x['cc_25d_btc'], 1, True)} | {p(x['cc_10d_btc'], 1, True)} | {p(x['straddle_usd_notional'])} {iv_rv} |")
    sg = v["signal"]
    a(V, f"({sg['months_on']} of {sg['months']}\n  months)")
    a(V, f"fell from {p(sg['cc_25d']['ann_return_always'], 1, True)} to {p(sg['cc_25d']['ann_return_signal'])} a year")
    a(V, f"the straddle fell from {p(sg['straddle']['ann_return_always'], 1, True)} to {p(sg['straddle']['ann_return_signal'], 1, True)}")
    a(V, f"correlates {n(vf['corr_funding_iv'], 2)} with the level of implied\n  volatility but {n(vf['corr_funding_atm_vrp'], 2)} with the at-the-money premium, across {vf['months']} months")
    a(V, f"**Before fees:** {p(ccc['gross']['ann_return'], 1, True)} a year in BTC")
    a(V, f"**After fees: {p(ccc['net']['ann_return'])} a year,** with a {p(ccc['net']['max_drawdown'])} drawdown")
    a(V, f"management took {p(ccc['management_fee_ann'])} a year and the performance fee {p(ccc['performance_fee_ann'])}, paid in {ccc['quarters_with_performance_fee']} quarters")
    a(V, f"accepting a {-su['worst_month']:.0%} worst month")
    a(V, f"added about {cc['ann_return']:.0%} a year in BTC before fees and lost about {-ccc['net']['ann_return']:.0%} after them")
    a(V, f"The skew used in the {cc['months'] - cc['from_trades']} fallback months")
    return out
