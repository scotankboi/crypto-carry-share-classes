"""One-page factsheet per share class (A4 PDF and PNG), every number computed in the run.

Layout: a "hypothetical backtest" band, KPI tiles in the class currency, cumulative NAV, a year x month
return grid, the assumed terms (currency, hedge, fees, valuation), the strategy and its risks, a table of
all classes and the disclaimer. Every number comes from results.json; nothing here describes a real fund.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .plots import CLASS_COLOR, INK, UNIT, _esc, _pct, _style, _wrap, num, pc  # noqa: E402

BAND = "#7a1f1f"
DISCLAIMER = ("Hypothetical backtest on public data with assumed fees and costs. It is not a fund, a track record, an offer or "
              "a solicitation, and it does not describe any firm's products or terms. Past and simulated returns do not predict "
              "future returns. Legal, tax and regulatory feasibility is not assessed.")


def header(fig, title: str, subtitle: str, period: str) -> None:
    """The band and titles shared by every factsheet."""
    fig.patches.append(matplotlib.patches.Rectangle((0, 0.972), 1, 0.028, transform=fig.transFigure, color=BAND, zorder=0))
    fig.text(0.5, 0.986, "HYPOTHETICAL BACKTEST – NOT A FUND, NOT AN OFFER", ha="center", va="center", fontsize=11,
             fontweight="bold", color="white")
    fig.text(0.06, 0.957, title, fontsize=16, fontweight="bold", color=INK["primary"], va="top")
    fig.text(0.06, 0.930, subtitle, fontsize=8.3, color=INK["secondary"], va="top")
    fig.text(0.06, 0.903, period, fontsize=7.8, color=INK["muted"], va="top")


def footer(fig) -> None:
    fig.patches.append(matplotlib.patches.Rectangle((0.05, 0.010), 0.9, 0.046, transform=fig.transFigure, facecolor="#f3f1ea",
                                                    edgecolor=INK["baseline"], linewidth=0.6, zorder=0))
    fig.text(0.065, 0.033, _wrap(DISCLAIMER, 118), fontsize=8, color=INK["primary"], va="center", linespacing=1.3)

HEDGE = {"USDT": "None: the master is a USDT book (USDT-margined perpetuals and USDT collateral).",
         "USD": "None: USDT converted at the previous day's Coinbase USDT-USD close, so the class carries the USDT peg.",
         "JPY hedged": "USD sold forward for JPY each month (1-month forward, covered interest parity on SOFR and TONA).",
         "KRW hedged": "USD sold forward for KRW each month (1-month forward, SOFR and the KRW 3-month rate).",
         "BTC hedged": "Long USDT-margined BTC perpetual equal to the class NAV, rebalanced daily, not netted against the "
                       "master; one third of NAV kept as its margin, in USDT."}
RF = {"USDT": "SOFR", "USD": "SOFR", "JPY hedged": "TONA", "KRW hedged": "KRW 3-month rate", "BTC hedged": "zero (BTC)"}


def _grid(net: pd.Series) -> pd.DataFrame:
    m = net.resample("ME").last()
    r = m.pct_change()
    r.iloc[0] = m.iloc[0] / net.iloc[0] - 1
    g = pd.DataFrame({"y": r.index.year, "m": r.index.month, "r": r.to_numpy()}).pivot(index="y", columns="m", values="r")
    y = net.resample("YE").last()
    yr = y.pct_change()
    yr.iloc[0] = y.iloc[0] / net.iloc[0] - 1
    g["Year"] = yr.to_numpy()
    return g


def risk_text(res: dict, cls: str) -> list[str]:
    """The 'Strategy and risks' lines, each built from results.json."""
    m, mg, cp = res["master"], res["margin"], res["counterparty"]
    lt = res["leverage_tradeoff"]["rows"]
    fe = {(r["topup_lag_h"], r["leverage"]): r["p_annual"] for r in mg["frontier_band_edge"]}
    ft = {(r["topup_lag_h"], r["leverage"]): r["p_annual"] for r in mg["frontier_target"]}
    lag, L = mg["engine_lag_h"], int(mg["config_leverage"])
    rep = {r["class"]: r for r in cp["default_replay"] if r["venue"] == "binance"}
    loss = rep["BTC hedged" if cls == "BTC hedged" else "USD / USDT"]["net_loss_after_recovery"]
    ex = res["rates"]["master_minus_sofr_calendar_years"]
    below = [y for y in ex if ex[y] < 0]
    lines = [f"Master, before fees: {pc(m['stats']['ann_return'], 1)} a year since Jan 2021; worst day "
             f"{pc(m['stats']['worst_day'], 2)} ({m['stats']['worst_day_date']}); worst drawdown {pc(m['stats']['max_drawdown'], 1)}.",
             f"Leverage {L:g}x on the short leg, a trade-off chosen in-sample: modelled annual liquidation probability "
             f"{pc(ft[(lag, L)], 1)} (target margin) to {pc(fe[(lag, L)], 1)} (band edge) with a {lag}h top-up, above a "
             f"{pc(mg['reference_probability_annual'], 0)} reference level; the band-edge figure rests on the fitted tail. At 1x "
             f"the master earned {pc(lt['1']['master_ann_return'], 1)} a year before fees, against {pc(lt[str(L)]['master_ann_return'], 1)}.",
             f"Venue risk: about {sum(cp['exposure_share_mean'].values()):.0%} of master NAV sits as margin at two exchanges. Had "
             f"one failed on FTX's petition date with FTX's class 5A recovery, this class would have lost {pc(loss, 1)} of NAV.",
             f"The carry moves in regimes: the master earned less than USD cash (SOFR) in {' and '.join(below)}"
             f"{' (to Sep)' if below and below[-1] == list(ex)[-1] else ''}."]
    if cls == "BTC hedged":
        yrs = res["classes"]["btc_class_calendar_years_gross"]
        neg = all(v < 0 for v in yrs.values())
        lines[-1] = ("In BTC terms the hedge pays the same funding the master earns" +
                     (": the class lost BTC in every calendar year of the sample, before fees." if neg else "."))
    if cls == "JPY hedged":
        h = res["classes"]["hedge_cost_by_year"]["JPY"]
        ys = [y for y in h if int(y) >= 2023]
        lines[-1] = (f"The forward hedge costs the USD–JPY rate gap: {', '.join(num(-h[y] * 100, 1) for y in ys)} points in "
                     f"{', '.join(ys)} (to Sep). The excess return over yen cash is about the same as the USD class's over dollar cash.")
    return lines


def build(cfg: dict, res: dict, cls: str, net: pd.Series, gross: pd.Series, path: Path) -> None:
    st = res["classes"]["stats"][cls]
    n = st["net"]
    unit = UNIT[cls]
    H = cfg["share_classes"]["valuation_hour_utc"]
    fig = plt.figure(figsize=(8.27, 11.69), dpi=150)
    fig.patch.set_facecolor(INK["surface"])
    L, T = 0.06, INK["secondary"]
    header(fig, f"Hypothetical backtest: BTC carry, {cls} class",
           _wrap("Market-neutral bitcoin carry: long spot BTC held at a custodian, short USDT-margined perpetuals on Binance "
                 "and Bybit at 2x. Simulated on public data with assumed fees.", 118),
           f"Period {n['start']} to {n['end']} | NAV and returns in {unit}, after assumed fees | daily valuation at {H}:00 UTC")
    beta = res["master"]["beta_btc"]["beta"]
    lo, hi = n["sharpe_ci95"]
    tiles = [("Annualised return", pc(n["ann_return"], 1, True)), ("Volatility (daily, annualised)", pc(n["ann_vol"], 1)),
             (f"Sharpe vs {RF[cls].split(' (')[0]} (95% interval)", f"{num(n['sharpe'], 2)} ({num(lo, 1)} to {num(hi, 1)})"),
             ("Max drawdown", pc(n["max_drawdown"], 1)), ("Positive months", f"{n['monthly_positive_ratio']:.0%}"),
             ("Beta to BTC (master, daily)", num(beta, 2))]
    for i, (k, v) in enumerate(tiles):
        x, y = L + (i % 3) * 0.3, 0.875 - (i // 3) * 0.052
        fig.text(x, y, k, fontsize=7.8, color=INK["muted"], va="top")
        fig.text(x, y - 0.015, v, fontsize=15 if len(v) < 10 else 12.5, color=INK["primary"], va="top", fontweight="bold")

    ax = fig.add_axes([0.08, 0.6, 0.86, 0.15])
    _style(ax)
    ax.plot(net.index, net / net.iloc[0] - 1, color=CLASS_COLOR[cls], linewidth=1.6, label="after fees")
    ax.plot(gross.index, gross / gross.iloc[0] - 1, color=INK["muted"], linewidth=0.9, linestyle="--", label="before fees")
    ax.axhline(0, color=INK["baseline"], linewidth=0.8)
    _pct(ax)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=7.5, labelcolor=INK["secondary"], loc="upper left" if net.iloc[-1] > net.iloc[0] else "lower left")
    ax.set_title(f"Cumulative return in {unit}", fontsize=9, color=INK["primary"], loc="left")

    g = _grid(net)
    fig.text(L, 0.565, f"Monthly returns in {unit} (after fees)", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    cols = list(range(1, 13)) + ["Year"]
    xs = [L + 0.1 + j * 0.0635 for j in range(len(cols))]
    y = 0.543
    for x, c in zip(xs, cols):
        fig.text(x, y, pd.Timestamp(2000, c, 1).strftime("%b") if c != "Year" else "Year", fontsize=6.8, color=INK["muted"],
                 va="top", ha="right")
    for yr, row in g.iterrows():
        y -= 0.0135
        fig.text(L, y, str(yr), fontsize=7, color=INK["muted"], va="top")
        for x, c in zip(xs, cols):
            v = row.get(c)
            if pd.notna(v):
                fig.text(x, y, num(v * 100, 1, True), fontsize=6.8, va="top", ha="right",
                         color=INK["primary"] if c == "Year" else (T if round(v * 100, 1) >= 0 else "#b03a2e"),
                         fontweight="bold" if c == "Year" else "normal")
    y -= 0.022

    sc = cfg["share_classes"]
    terms = [("Class currency", unit), ("Currency treatment", HEDGE[cls]),
             ("Fees (assumed)", f"{sc['management_fee']:.1%} management a year; {sc['performance_fee']:.0%} performance above a "
                                f"high-water mark, crystallised quarterly"),
             ("Fees paid", f"{pc(st['fees_paid_ann'], 2)} of assets a year"),
             ("Before fees", f"{pc(st['gross']['ann_return'], 1, True)} a year" +
              ("" if cls == "USD" else f" ({pc(st['gross_minus_usd_ann'], 1, True)} vs the USD class)")),
             ("Risk-free rate", RF[cls])]
    fig.text(L, y, "Assumed terms", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    yt = y - 0.02
    for k, v in terms:
        fig.text(L, yt, k, fontsize=7.4, color=INK["muted"], va="top")
        w = _wrap(v, 46)
        fig.text(L + 0.14, yt, w, fontsize=7.4, color=T, va="top", linespacing=1.25)
        yt -= 0.0125 * (w.count("\n") + 1) + 0.004

    risk_lines = risk_text(res, cls)
    fig.text(0.53, y, "Strategy and risks", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    yr_ = y - 0.02
    for line in risk_lines:
        w = _wrap(line, 62)
        fig.text(0.53, yr_, _esc(w), fontsize=7.4, color=T, va="top", linespacing=1.25)
        yr_ -= 0.0125 * (w.count("\n") + 1) + 0.006
    # all classes side by side
    yc = min(yt, yr_) - 0.016
    fig.text(L, yc, "All share classes, after fees", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    heads = [("Class", L, "left"), ("Return", 0.36, "right"), ("Volatility", 0.47, "right"), ("Sharpe", 0.56, "right"),
             ("Max drawdown", 0.69, "right"), ("Fees paid", 0.8, "right"), ("Before fees", 0.92, "right")]
    yc -= 0.018
    for h, x, ha in heads:
        fig.text(x, yc, h, fontsize=7, color=INK["muted"], va="top", ha=ha)
    for k, v in res["classes"]["stats"].items():
        yc -= 0.0142
        bold = "bold" if k == cls else "normal"
        vals = [f"{k} (in {UNIT[k]})", pc(v["net"]["ann_return"], 1, True), pc(v["net"]["ann_vol"], 1), num(v["net"]["sharpe"], 2),
                pc(v["net"]["max_drawdown"], 1), pc(v["fees_paid_ann"], 2), pc(v["gross"]["ann_return"], 1, True)]
        for (h, x, ha), t in zip(heads, vals):
            fig.text(x, yc, t, fontsize=7.4, color=INK["primary"] if k == cls else T, va="top", ha=ha, fontweight=bold)
    fig.text(L, yc - 0.02, _wrap("Sharpe ratios: monthly excess returns over each class's own short rate (zero for BTC), "
                                 "annualised allowing for their autocorrelation (Lo 2002), so they are not return divided by the "
                                 "daily volatility shown. Volatility: daily returns annualised.", 128), fontsize=7.2,
             color=INK["secondary"], va="top")
    footer(fig)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=INK["surface"], metadata={"CreationDate": None})     # byte-reproducible PDF
    fig.savefig(path.with_suffix(".png"), facecolor=INK["surface"])
    plt.close(fig)
