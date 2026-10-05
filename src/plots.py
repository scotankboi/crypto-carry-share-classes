"""Figures for the README. Static PNGs, light surface, one axis per panel, titles computed from results."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

INK = {"primary": "#0b0b0b", "secondary": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
       "baseline": "#c3c2b7", "surface": "#fcfcfb"}
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
CLASS_COLOR = {"USDT": SLOT[0], "USD": "#86b6ef", "JPY hedged": SLOT[1], "KRW hedged": SLOT[2], "BTC hedged": SLOT[3]}
UNIT = {"USDT": "USDT", "USD": "USD", "JPY hedged": "JPY", "KRW hedged": "KRW", "BTC hedged": "BTC"}


def _style(ax) -> None:
    ax.set_facecolor(INK["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK["baseline"])
    ax.grid(axis="y", color=INK["grid"], linewidth=0.75)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK["muted"], labelcolor=INK["secondary"], labelsize=8.5, length=0)


MINUS = "\u2212"


def pc(v: float, d: int = 1, sign: bool = False) -> str:
    """A percentage with a typographic minus: pc(-0.057) -> '−5.7%'."""
    return num(v * 100, d, sign) + "%"


def num(v: float, d: int = 1, sign: bool = False) -> str:
    if round(v, d) == 0:
        v = 0.0                                   # no "−0.0"
    return (f"{v:+.{d}f}" if sign and v != 0 else f"{v:.{d}f}").replace("-", MINUS)


def _pct(ax, axis="y", decimals=0) -> None:
    a = ax.yaxis if axis == "y" else ax.xaxis
    a.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5, 10]))
    a.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.{decimals}f}%".replace("-", MINUS)))


def _wrap(text: str, width: int) -> str:
    import textwrap
    return "\n".join(textwrap.wrap(text, width))


def _esc(text: str) -> str:
    return text.replace("$", r"\$")


def _titles(fig, title: str, subtitle: str, source: str) -> None:
    fig.patch.set_facecolor(INK["surface"])
    chars = int(fig.get_figwidth() * 13)
    fig.text(0.05, 0.965, title, fontsize=13, fontweight="bold", color=INK["primary"], va="top")
    fig.text(0.05, 0.905, _esc(_wrap(subtitle, chars)), fontsize=9.2, color=INK["secondary"], va="top", linespacing=1.35)
    fig.text(0.05, 0.02, _esc(_wrap(source, int(chars * 1.15))), fontsize=7.8, color=INK["muted"], va="bottom")


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=INK["surface"])
    plt.close(fig)


def _years(ax) -> None:
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def share_classes(net: dict, cls: dict, path: Path, cfg: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), dpi=200, gridspec_kw={"width_ratios": [1.5, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.12, wspace=0.28)
    ax = axes[0]
    _style(ax)
    for k, s in net.items():
        ax.plot(s.index, s / s.iloc[0] - 1, color=CLASS_COLOR[k], linewidth=1.6, label=f"{k} (in {UNIT[k]})")
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    _pct(ax)
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="center right", bbox_to_anchor=(1.0, 0.42))
    ax.set_title("Cumulative return after fees, each in its own currency (USDT and USD overlap)", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=INK["grid"], linewidth=0.75)
    ks = list(net)[::-1]
    y = np.arange(len(ks))
    g = [cls[k]["gross"]["ann_return"] for k in ks]
    n = [cls[k]["net"]["ann_return"] for k in ks]
    ax.barh(y, g, color=[CLASS_COLOR[k] for k in ks], height=0.6, alpha=0.35, label="before fees")
    ax.barh(y, n, color=[CLASS_COLOR[k] for k in ks], height=0.32, label="after fees")
    for yi, v in zip(y, n):
        ax.text(v + (0.003 if v >= 0 else -0.003), yi, pc(v, 1, True), va="center", ha="left" if v >= 0 else "right",
                fontsize=8, color=INK["primary"])
    ax.set_yticks(y, ks, fontsize=8.5)
    ax.axvline(0, color=INK["baseline"], linewidth=1)
    _pct(ax, "x")
    ax.set_xlim(min(n) * 1.45, max(g) * 1.35)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="lower right")
    ax.set_title("Annualised return", fontsize=9, color=INK["primary"], loc="left")
    u, b = cls["USDT"]["net"]["ann_return"], cls["BTC hedged"]["net"]["ann_return"]
    sc_ = cfg["share_classes"]
    _titles(fig, f"One carry, five investors: {pc(u, 1, True)} a year in USDT, {pc(b, 1, True)} a year in BTC",
            f"Hypothetical backtest. The same delta-neutral bitcoin carry (long spot, short perpetuals on Binance and Bybit, "
            f"{cfg['strategy']['leverage']:g}x) delivered to investors who measure wealth in different currencies. Hedging into yen "
            f"costs the USD–JPY interest-rate gap; hedging into BTC costs the same funding the strategy earns.",
            f"Jan 2021 – Sep 2026, daily NAV at {sc_['valuation_hour_utc']}:00 UTC. Assumed fees: {sc_['management_fee']:.1%} "
            f"management, {sc_['performance_fee']:.0%} performance above a high-water mark. Sources: Binance, Bybit, Coinbase, "
            f"FRED, Bank of Japan.")
    _save(fig, path)


def carry_regimes(weekly: pd.Series, bp: dict, daily_tab: pd.DataFrame, events: list, path: Path, excess: dict) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.8), dpi=200)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.12)
    _style(ax)
    ax.plot(weekly.index, weekly, color=SLOT[0], linewidth=1.0, alpha=0.55, label="perp funding, weekly (Binance/Bybit average)")
    m = daily_tab[["quarterly_basis", "cme_basis"]].rolling(30, min_periods=10).mean()
    ax.plot(m.index, m["quarterly_basis"], color=SLOT[1], linewidth=1.2, label="Binance quarterly basis, 30-day mean")
    ax.plot(m.index, m["cme_basis"], color=SLOT[2], linewidth=1.2, label="CME basis, 30-day mean")
    for sgm in bp["segments"]:
        a, b = pd.Timestamp(sgm["start"]), pd.Timestamp(sgm["end"]) + pd.Timedelta(days=7)
        ax.plot([a, b], [sgm["mean"]] * 2, color=INK["primary"], linewidth=2)
        ax.text(a + (b - a) / 2, sgm["mean"] + 0.04, pc(sgm["mean"], 0), ha="center", fontsize=8, color=INK["primary"])
    for e in events:
        d = pd.Timestamp(e["date"])
        ax.axvline(d, color=INK["baseline"], linewidth=0.8, linestyle="--")
        ax.text(d, 1.0, f" {e['label']}", fontsize=7.2, color=INK["secondary"], va="top", rotation=90,
                transform=ax.get_xaxis_transform())
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    low = float(min(weekly.min(), m.min().min()))
    ax.set_ylim(min(-0.1, low * 1.1), min(1.2, float(weekly.max()) * 1.05))
    _pct(ax)
    _years(ax)
    leg = ax.legend(frameon=True, fontsize=8, labelcolor=INK["secondary"], loc="lower right", bbox_to_anchor=(1.0, 0.33))
    leg.get_frame().set(facecolor=INK["surface"], edgecolor="none", alpha=1.0)
    seg = " → ".join(pc(s["mean"], 0) for s in bp["segments"])
    below = [y for y in excess if excess[y] < 0]
    since = below[0] if below and all(excess[y] < 0 for y in excess if y >= below[0]) else None
    head = (f"The bitcoin carry moves in regimes; since {since} the master has earned less than US cash" if since
            else "The bitcoin carry moves in regimes")
    ex_txt = ", ".join(f"{y}{'*' if y == list(excess)[-1] else ''} {num(excess[y] * 100, 1, True)}" for y in excess)
    _titles(fig, head,
            f"Annualised. Black steps: mean funding in each regime, break dates estimated (Bai–Perron, number of breaks by BIC): "
            f"{seg}. Master return minus SOFR, points: {ex_txt} (*to 30 Sep).",
            "Funding settlements every 8h; basis annualised to each contract's expiry, excluding the last 7 days and the CME roll "
            f"day. Axis cut at 120%: weekly funding peaked at {pc(float(weekly.max()), 0)} in early 2021. Sources: Binance, Bybit, "
            "CME via Yahoo Finance (daily close), Coinbase, FRED.")
    _save(fig, path)


def cme_vs_offshore(by_regime: pd.DataFrame, daily_tab: pd.DataFrame, path: Path, al: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.5, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    ax = axes[0]
    _style(ax)
    q = daily_tab.resample("QE").mean(numeric_only=True)
    w = 25
    x = q.index
    ax.bar(x - pd.Timedelta(days=w), q["quarterly_basis"], width=w, color=SLOT[1], label="Binance quarterly")
    ax.bar(x, q["cme_basis"], width=w, color=SLOT[2], label="CME")
    ax.plot(x, (q["funding_binance"] + q["funding_bybit"]) / 2, color=SLOT[0], marker="o", markersize=3, linewidth=1.2,
            label="perp funding")
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    _pct(ax)
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"])
    ax.set_title("Quarterly averages, annualised", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    r = by_regime.set_index("regime")
    xs = np.arange(len(r))
    ax.bar(xs - 0.2, r["quarterly_basis"], width=0.4, color=SLOT[1], label="Binance quarterly")
    ax.bar(xs + 0.2, r["cme_basis"], width=0.4, color=SLOT[2], label="CME")
    for xi, (a, b, gap) in zip(xs, zip(r["quarterly_basis"], r["cme_basis"], r["cme_minus_quarterly"])):
        ax.text(xi, max(a, b) + 0.003, f"gap {num(gap * 100, 1, True)} pts", ha="center", fontsize=8, color=INK["primary"])
    ax.set_xticks(xs, [i.split(". ")[1] for i in r.index], fontsize=8)
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    _pct(ax)
    ax.set_ylim(0, float(r[["quarterly_basis", "cme_basis"]].max().max()) * 1.18)
    ax.set_title("Mean annualised basis by regime", fontsize=9, color=INK["primary"], loc="left")
    gap0 = r["cme_minus_quarterly"].iloc[0]
    _titles(fig, f"Offshore basis ran {-gap0 * 100:.0f} points a year above CME before FTX; the gap has since closed",
            "Gap: mean of daily differences, CME minus Binance quarterly, on days both are observed. If the gap were the price "
            "of offshore counterparty risk it should have widened after FTX. It closed instead, which is consistent with "
            "offshore leverage demand that arbitrage capital later reached (not tested).",
            f"CME: Yahoo's daily close of the continuous front month (BTC=F) against Coinbase BTC-USD at 15:00 Chicago, where the "
            f"basis is smoothest (daily-change s.d. {pc(al['0'], 2)}, against {pc(min(al['-1'], al['1']), 1)}–{pc(max(al['-1'], al['1']), 1)} "
            f"an hour either side); the week before expiry and the first day after each expiry excluded. Sources: Yahoo Finance, "
            f"Coinbase, Binance, Bybit.")
    _save(fig, path)


def master(nav: pd.Series, sofr: pd.Series, years: dict, sofr_years: dict, attribution: dict, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.4, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    ax = axes[0]
    _style(ax)
    cash = (1 + sofr.reindex(nav.index).ffill().bfill() / 360).cumprod()
    ax.plot(nav.index, nav / nav.iloc[0] - 1, color=SLOT[0], linewidth=1.8, label="master (USDT, before fees)")
    ax.plot(cash.index, cash / cash.iloc[0] - 1, color=INK["muted"], linewidth=1.2, linestyle="--", label="USD cash (SOFR)")
    _pct(ax)
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="upper left")
    ax.set_title("Cumulative return", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    ys = list(years)
    xs = np.arange(len(ys))
    ax.bar(xs - 0.2, [years[y] for y in ys], width=0.4, color=SLOT[0], label="master")
    ax.bar(xs + 0.2, [sofr_years.get(y, np.nan) for y in ys], width=0.4, color=INK["baseline"], label="SOFR")
    for xi, y in zip(xs, ys):
        ax.text(xi - 0.2, years[y] + 0.004, pc(years[y], 1), ha="center", fontsize=7.5, color=INK["primary"])
    ax.set_xticks(xs, [f"{y}" + ("*" if y == ys[-1] else "") for y in ys], fontsize=8)
    _pct(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"])
    ax.set_title("Calendar-year return (*to 30 Sep)", fontsize=9, color=INK["primary"], loc="left")
    ex = {y: years[y] - sofr_years[y] for y in years if y in sofr_years}
    _titles(fig, f"The master: a smooth carry whose excess over cash came mostly in {max(ex, key=ex.get)}",
            f"Long spot BTC at a custodian, short USDT-margined perpetuals on Binance and Bybit (50/50) at 2x, margin and venue "
            f"weights reset weekly. Annualised log-return contributions: funding {pc(attribution['funding'], 1)}, basis "
            f"{pc(attribution['convergence'], 2, True)}, costs {pc(attribution['costs'], 2, True)}, summing to "
            f"{pc(attribution['sum'], 1)} ({pc(attribution['compounded_return_ann'], 1)} a year compounded).",
            "Before management and performance fees. Hypothetical backtest. Sources: Binance, Bybit, FRED.")
    _save(fig, path)


def margin_frontier(fr: pd.DataFrame, fr_target: pd.DataFrame, mg: dict, lev_ret: dict, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.3, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.70, bottom=0.19, wspace=0.25)
    alpha, lag = mg["reference_probability_annual"], mg["engine_lag_h"]
    ax = axes[0]
    _style(ax)
    for i, (T, g) in enumerate(fr.groupby("topup_lag_h")):
        own = T == lag
        ax.plot(g["leverage"], g["p_annual"].clip(lower=1e-4), color=SLOT[i], marker="o", linewidth=2.2 if own else 1.2,
                label=f"top-up within {T}h" + (" (the engine's lag)" if own else ""))
    gt = fr_target[fr_target["topup_lag_h"] == lag]
    ax.plot(gt["leverage"], gt["p_annual"].clip(lower=1e-4), color=INK["muted"], linestyle="--", linewidth=1.0,
            label=f"{lag}h, from target margin 1/L")
    ax.axhline(alpha, color=INK["primary"], linewidth=0.8)
    ax.text(fr["leverage"].max(), alpha, f"{pc(alpha, 0)} a year (reference) ", ha="right", va="bottom", fontsize=8, color=INK["secondary"])
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2%}" if v < 0.01 else f"{v:.0%}"))
    ax.set_xlabel("Perp leverage", fontsize=8.5, color=INK["secondary"])
    ax.legend(frameon=False, fontsize=7.5, labelcolor=INK["secondary"], loc="lower right")
    ax.set_title("Annual probability of at least one liquidation, from the band edge", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    ls = sorted(lev_ret, key=float)
    ax.bar([str(x) + "x" for x in ls], [lev_ret[x]["ann_return"] for x in ls], color=SLOT[0], width=0.5)
    for i, x in enumerate(ls):
        n = lev_ret[x]["liquidation_flags"]
        ax.text(i, lev_ret[x]["ann_return"] + 0.002, pc(lev_ret[x]["ann_return"], 1) + (f"\n{n} flag" + ("s" if n > 1 else "") if n else ""),
                ha="center", va="bottom", fontsize=8, color=INK["primary"])
    _pct(ax)
    ax.set_ylim(0, max(v["ann_return"] for v in lev_ret.values()) * 1.3)
    ax.set_title("Master return by leverage, 2021–2026 (liquidation flags)", fontsize=9, color=INK["primary"], loc="left")
    g = fr[fr["topup_lag_h"] == lag].set_index("leverage")
    p2 = float(g.loc[2, "p_annual"])
    p2t = float(gt.set_index("leverage").loc[2, "p_annual"])
    r1, r2 = lev_ret[1]["ann_return"], lev_ret[2]["ann_return"]
    _titles(fig, f"Leverage is a trade-off: 2x earned {num((r2 - r1) * 100, 1)} points a year more than 1x, for a modelled "
            f"liquidation risk of {pc(p2t, 1)}–{pc(p2, 1)} a year",
            f"The base case (2x, chosen in-sample) is above the {pc(alpha, 0)} reference line on this model; the band-edge "
            f"figure comes from the fitted tail, and no observed episode since 2018 would have liquidated it within {lag}h. "
            f"Margin can drift to the band edge, {1 - mg['band']:.2f}/L, and is topped up {lag} hours after a breach.",
            f"A short with margin ratio e is liquidated by a rise of (e − m)/(1 + m); m = {pc(mg['maintenance'], 1)} (assumption). "
            f"Probability: the larger of declustered empirical episodes and a generalised Pareto tail on hourly Binance BTCUSDT "
            f"since 2018, non-decreasing in the lag. Flags: backtest hours with a leg below maintenance at the last-price high.")
    _save(fig, path)


def hedge_costs(hc: dict, rate_gap: pd.DataFrame, path: Path) -> None:
    jpy = hc["JPY"]
    yrs = [y for y in jpy if int(y) >= 2023]
    jtxt = ", ".join(num(-jpy[y] * 100, 1) for y in yrs)
    krw_gain = [y for y in hc["KRW"] if hc["KRW"][y] > 0]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    ax = axes[0]
    _style(ax)
    for col, c, lab in (("JPY", SLOT[1], "SOFR − TONA"), ("KRW", SLOT[2], "SOFR − KRW 3-month")):
        ax.plot(rate_gap.index, rate_gap[col], color=c, linewidth=1.6, label=lab)
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    _pct(ax, "y", 0)
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"])
    ax.set_title("Interest-rate gap: the cost of a currency hedge", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    ys = list(hc["JPY"])
    xs = np.arange(len(ys))
    for j, (k, c) in enumerate((("JPY", SLOT[1]), ("KRW", SLOT[2]), ("BTC (perp hedge)", SLOT[3]))):
        ax.bar(xs + (j - 1) * 0.27, [hc[k][y] for y in ys], width=0.27, color=c, label=k.replace(" (perp hedge)", ""))
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    ax.set_xticks(xs, [y + ("*" if y == ys[-1] else "") for y in ys], fontsize=8)
    _pct(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"])
    ax.set_title("Class return minus USD class (*to 30 Sep), by year (before fees)", fontsize=9, color=INK["primary"], loc="left")
    _titles(fig, "What each investor pays to be paid in their own currency",
            f"Yen and won classes sell dollars forward every month; by covered interest parity that costs the rate gap. For yen "
            f"it cost {jtxt} points in {', '.join(yrs[:-1])} and {yrs[-1]} to date; for won it was a gain in "
            f"{' and '.join(krw_gain)}. The BTC class buys BTC through a perpetual and pays its funding.",
            "Forwards priced from SOFR, TONA (Bank of Japan) and the KRW 3-month rate (monthly) with no cross-currency basis; "
            "a −30bp basis is a sensitivity. Sources: FRED, Bank of Japan, Binance.")
    _save(fig, path)


def btc_class(btc_perp: pd.Series, btc_q: pd.Series, unhedged: pd.Series, cal: pd.DataFrame, algebra: dict, path: Path,
              construction: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.4, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    ax = axes[0]
    _style(ax)
    ax.plot(btc_perp.index, btc_perp, color=SLOT[3], linewidth=1.8, label="BTC hedged with the perp")
    ax.plot(btc_q.index, btc_q * float(btc_perp.asof(btc_q.index[0])), color=SLOT[1], linewidth=1.4, label="BTC hedged with the quarterly")
    ax.plot(unhedged.index, unhedged, color=INK["muted"], linewidth=1.0, label="not hedged (USD carry measured in BTC)")
    ax.axhline(1, color=INK["primary"], linewidth=0.8)
    ax.text(btc_perp.index[-1], 1.0, "just holding 1 BTC ", fontsize=8, color=INK["secondary"], va="bottom", ha="right")
    ax.set_ylim(0, max(1.6, float(unhedged.max()) * 1.05))
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="upper right")
    ax.set_title("BTC held per BTC invested, before fees", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    starts = pd.to_datetime(cal["start"]).dt.tz_localize(None)
    ax.bar(starts, cal["calendar_carry_ann"], width=70, align="edge",
           color=[SLOT[2] if v > 0 else SLOT[1] for v in cal["calendar_carry_ann"]])
    mean_cc = cal["calendar_carry_ann"].mean()
    ax.axhline(mean_cc, color=INK["primary"], linewidth=0.8)
    _years(ax)
    _pct(ax)
    ax.set_title(f"Short perp, long quarterly: each quarter's carry, annualised\n(black line: mean, {pc(mean_cc, 1, True)})", fontsize=9, color=INK["primary"], loc="left")
    c = construction
    _titles(fig, f"In BTC terms the basis carry is not a yield: the BTC class lost {pc(-algebra['observed'], 1)} a year",
            f"Base case: a long perpetual on all of NAV pays the funding the master earns, while only {1 - algebra['m']:.0%} of NAV "
            f"is invested; predicted (1 − m) × master − funding = {pc(algebra['predicted'], 1, True)}, observed "
            f"{pc(algebra['observed'], 1, True)}. With the hedge margin held in BTC: {pc(c['coin_margined_not_netted']['ann_return'], 1, True)}; "
            f"with the hedge netted against the master's short: {pc(c['netted']['ann_return'], 1, True)}. Short perp against long "
            f"quarterly averaged {pc(cal['calendar_carry_ann'].mean(), 1, True)} a year.",
            "Base case: daily rebalancing, one third of NAV as hedge margin held in USDT, not netted against the master. Binance "
            "BTCUSDT perpetual or quarterly. Before fees. Sources: Binance, Coinbase.")
    _save(fig, path)


def counterparty(share: pd.DataFrame, replay: pd.DataFrame, rec: dict, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.3, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.16, wspace=0.28)
    ax = axes[0]
    _style(ax)
    tot = share.sum(axis=1)
    ax.fill_between(tot.index, tot.rolling(30).min(), tot.rolling(30).max(), color=SLOT[0], alpha=0.15, linewidth=0,
                    label="both venues, 30-day range")
    ax.plot(tot.index, tot.rolling(30).mean(), color=SLOT[0], linewidth=1.4, label="both venues, 30-day mean")
    ax.plot(share.index, share["binance"].rolling(30).mean(), color=SLOT[1], linewidth=1.2, label="Binance, 30-day mean")
    _pct(ax)
    _years(ax)
    ax.set_ylim(0, None)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"])
    ax.set_title("Master NAV held as margin at the venues", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    r = replay[replay["venue"] == "binance"].set_index("class")
    xs = np.arange(len(r))
    ax.bar(xs - 0.18, r["loss_on_default"], width=0.36, color=INK["baseline"], label="written off at default")
    ax.bar(xs + 0.18, r["net_loss_after_recovery"], width=0.36, color=SLOT[1], label="after FTX class 5A payments to date")
    for xi, v in zip(xs, r["net_loss_after_recovery"]):
        ax.text(xi + 0.18, v + 0.005, pc(v, 1), ha="center", fontsize=8, color=INK["primary"])
    ax.set_xticks(xs, r.index, fontsize=8.5)
    _pct(ax)
    ax.set_ylim(0, float(r["loss_on_default"].max()) * 1.45)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="upper left")
    ax.set_title("If Binance had failed on 11 Nov 2022 (share of class NAV)", fontsize=9, color=INK["primary"], loc="left")
    sched = ", ".join(f"{pd.Timestamp(x['date']):%b %Y} {x['cumulative']:.0%}" for x in rec["schedule"])
    _titles(fig, "A venue failure costs a USD investor part of the claim and a BTC investor most of it",
            f"FTX repaid non-US customers (class 5A) in dollars at petition-date prices (BTC ${rec['btc_petition']:,.0f}), "
            f"cumulatively {sched} of the claim. Valued on each payment date, that is {pc(rec['usd_vs_master'], 0)} of what the "
            f"claim would have grown to in the master, and {pc(rec['btc'], 0)} of the coins. The BTC class also keeps its hedge "
            f"margin at the venue.",
            "Spot BTC assumed at a custodian with off-exchange settlement; only margin is at risk. The unpaid balance is counted "
            "as lost. Distribution terms: FTX Recovery Trust press releases. Sources: Binance, Bybit, Coinbase.")
    _save(fig, path)


def oct10(spot: pd.DataFrame, perps: dict, nav0: float, n: dict, S0: float, F0: dict, path: Path, s: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), dpi=200)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    a, b = pd.Timestamp(s["window"][0]), pd.Timestamp(s["window"][1])
    sp = spot.set_index("open_time").loc[a:b]
    ax = axes[0]
    _style(ax)
    ax.plot(sp.index, sp["close"], color=INK["primary"], linewidth=1.2, label="spot (Binance)")
    mtm = pd.Series(0.0, index=sp.index)
    for (v, k), c in zip(perps.items(), (SLOT[1], SLOT[0])):
        f = k.set_index("open_time").loc[a:b].reindex(sp.index).ffill()
        ax.plot(f.index, f["close"], color=c, linewidth=0.9, label=f"perp ({v.capitalize()})")
        mtm += n[v] * ((sp["close"] - S0) - (f["close"] - F0[v]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v / 1000:,.0f}k"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"])
    ax.set_title("BTC, one-minute closes (UTC)", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    ax.plot(mtm.index, mtm / nav0 * 1e4, color=SLOT[0], linewidth=1.2)
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_title("Hedged book, change in NAV (basis points)", fontsize=9, color=INK["primary"], loc="left")
    w = min(min(d["adl"][k]["worst_share_nav"] for k in d["adl"]) for d in s["venues"].values())
    _titles(fig, f"10 Oct 2025: BTC fell {abs(s['spot_drawdown']):.0%} by {pd.Timestamp(s['spot_low_time']):%H:%M} UTC; "
            f"the hedged book moved between {num(s['book_mtm_worst_share_nav'] * 1e4, 0)} and {num(s['book_mtm_best_share_nav'] * 1e4, 0, True)}bp",
            f"Perps traded up to {abs(min(d['basis_min_bp'] for d in s['venues'].values())):.0f}bp below spot. The short legs gained, "
            f"so margin was never short. Had a venue auto-deleveraged the book's short at any minute of the cascade, and had the "
            f"short been re-established 5–240 minutes later, the worst outcome was {pc(w, 1, True)} of NAV.",
            "Book as at 20:00 UTC on 10 Oct 2025. Hypothetical backtest. Sources: Binance, Bybit one-minute bars.")
    _save(fig, path)


def make_all(cfg, res, raw, pf, qf, cme, weekly, bp, daily_tab, fr, led, nav, gross, net, unhedged_btc, bx, hedged,
             btc_perp, share, FIG) -> None:
    from . import carry, risk, share_classes as sc
    sofr = raw["sofr"].set_index("date")["value"] / 100
    share_classes(net, res["classes"]["stats"], FIG / "00_share_classes.png", cfg)
    carry_regimes(weekly, bp, daily_tab, cfg["events"], FIG / "01_carry_regimes.png", res["rates"]["master_minus_sofr_calendar_years"])
    cme_vs_offshore(pd.DataFrame(res["carry"]["by_regime"]), daily_tab, FIG / "02_cme_vs_offshore.png",
                    res["carry"]["cme"]["close_alignment"]["basis_daily_change_sd_by_spot_hour_offset"])
    cash = (1 + sofr.reindex(nav.index).ffill().bfill() / 360).cumprod()
    sofr_years = {str(k.year): float(v) for k, v in risk.calendar_returns(cash).items()}
    master(nav, sofr, res["master"]["calendar_years"], sofr_years, res["master"]["attribution_log_ann"], FIG / "03_master.png")
    margin_frontier(fr, pd.DataFrame(res["margin"]["frontier_target"]), res["margin"], res["master"]["leverage_ann_return"],
                    FIG / "04_margin_frontier.png")
    tona = raw["tona"].set_index("date")["value"] / 100
    krw = raw["krw_rate"].set_index("date")["value"] / 100
    idx = nav.index
    gap = pd.DataFrame({"JPY": sofr.reindex(idx, method="ffill") - tona.reindex(idx, method="ffill"),
                        "KRW": sofr.reindex(idx, method="ffill") - krw.reindex(idx, method="ffill")})
    hedge_costs(res["classes"]["hedge_cost_by_year"], gap, FIG / "05_hedge_costs.png")
    qstart = pd.Timestamp(res["classes"]["btc_hedge_instrument"]["from"])
    usd_q = gross["USD"].loc[qstart:] / gross["USD"].loc[qstart:].iloc[0]
    tc = cfg["venues"]["binance"]["perp_taker"] + cfg["costs"]["perp_half_spread_bps"] / 1e4
    H = cfg["share_classes"]["valuation_hour_utc"]
    btc_q = sc.btc_class(usd_q, bx, sc.hedge_pnl_per_btc(qf, "binance_q", H), cfg["share_classes"]["btc_hedge_margin"], tc)["index"]
    cal = carry.calendar_carry(qf, pf["f_binance"])
    btc_class(gross["BTC hedged"], btc_q, unhedged_btc, cal, res["classes"]["btc_class_algebra"], FIG / "06_btc_class.png",
              res["classes"]["btc_construction"])
    counterparty(share, pd.DataFrame(res["counterparty"]["default_replay"]), res["counterparty"]["ftx_recovery"],
                 FIG / "07_counterparty.png")
    s = res["stress_oct10"]
    t0 = pd.Timestamp(s["window"][0])
    row = led.loc[t0]
    w = cfg["strategy"]["weights"]
    px = lambda k: float(k.loc[k["open_time"] < t0, "close"].iloc[-1])
    perps = {"binance": raw["perp_bn_1m_oct2025"], "bybit": raw["perp_bb_1m_oct2025"]}
    oct10(raw["spot_bn_1m_oct2025"], perps, float(row["nav"]), {v: w[v] * float(row["Q"]) for v in w},
          px(raw["spot_bn_1m_oct2025"]), {v: px(k) for v, k in perps.items()}, FIG / "08_oct10.png", s)
