"""Figures for the options chapter, in the same style as the main figures."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ..plots import INK, SLOT, _pct, _save, _style, _titles, _years, num, pc  # noqa: E402


def vrp(t: pd.DataFrame, straddle: pd.DataFrame, res: dict, path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.5, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    ax = axes[0]
    _style(ax)
    ax.plot(t.index, t["dvol"], color=SLOT[1], linewidth=1.0, label="DVOL (30-day implied, variance-swap style)")
    ax.plot(t.index, t["rv_fwd"], color=INK["primary"], linewidth=0.9, label="realised over the next 30 days")
    ax.scatter(straddle["roll"].dt.tz_localize(None), straddle["iv"], s=10, color=SLOT[0], zorder=3,
               label="at-the-money implied, traded at each roll")
    _pct(ax)
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="upper right")
    ax.set_title("Implied and realised volatility, annualised", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    by = res["vrp"]["by_year"]
    ys = list(by)
    s = straddle.assign(y=straddle["roll"].dt.year.astype(str))
    atm = (s["iv"] - s["rv"]).groupby(s["y"]).mean()
    xs = np.arange(len(ys))
    ax.bar(xs - 0.2, [by[y]["vrp_vol"] for y in ys], width=0.4, color=SLOT[1], label="DVOL − realised")
    ax.bar(xs + 0.2, [atm.get(y, np.nan) for y in ys], width=0.4, color=SLOT[0], label="at the money − realised")
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    ax.set_xticks(xs, [y + ("*" if y == ys[-1] else "") for y in ys], fontsize=8)
    from matplotlib.ticker import FuncFormatter, MultipleLocator
    ax.yaxis.set_major_locator(MultipleLocator(0.05))                     # 0, 5, 10, 15 vol points
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: num(v * 100, 0)))
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"])
    ax.set_title("Premium by year, volatility points (*to Sep)", fontsize=9, color=INK["primary"], loc="left")
    v, st = res["vrp"], res["straddle"]
    by21, ylast = by[ys[0]]["vrp_vol"] * 100, ys[-1]
    bylast = by[ylast]["vrp_vol"] * 100
    _titles(fig, f"BTC options are priced {num(v['vrp_vol_mean'] * 100, 1)} vol points above what follows, but at the money only "
            f"{num(st['atm_vrp_mean'] * 100, 1)}",
            f"DVOL averaged {pc(v['dvol_mean'], 1)} against {pc(v['rv_mean'], 1)} realised and was above it on "
            f"{v['share_days_positive']:.0%} of days. DVOL is built like a variance swap and includes the wings: at-the-money "
            f"options traded {num(st['dvol_minus_atm_iv_mean'] * 100, 1)} points below it, and were above realised volatility in "
            f"{st['share_months_iv_above_rv']:.0%} of months. The premium fell from {num(by21, 1)} points in 2021 to "
            f"{num(bylast, 1)} in {ylast} (to September).",
            "Realised volatility from Coinbase BTC-USD at 08:00 UTC, daily. Sources: Deribit (DVOL, option trades), Coinbase.")
    _save(fig, path)


def covered_calls(tables: dict, res: dict, path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.4, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    ax = axes[0]
    _style(ax)
    for (k, c, lab) in (("cc_25d", SLOT[1], "25-delta calls"), ("cc_10d", SLOT[2], "10-delta calls")):
        o = tables[k]
        x = pd.DatetimeIndex(o["expiry"].dt.tz_localize(None)).insert(0, o["roll"].iloc[0].tz_localize(None))
        ax.step(x, np.r_[1.0, o["btc_held"]], where="post", color=c, linewidth=1.6, label=lab)
    s = tables["straddle"]
    x = pd.DatetimeIndex(s["expiry"].dt.tz_localize(None)).insert(0, s["roll"].iloc[0].tz_localize(None))
    ax.step(x, np.r_[1.0, (1 + s["ret_btc"]).cumprod()], where="post", color=SLOT[0], linewidth=1.2,
            label="delta-hedged short straddle (1x)")
    ax.axhline(1, color=INK["primary"], linewidth=0.8)
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="upper right")
    ax.set_title("BTC held per BTC invested, before fees", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    o = tables["cc_25d"]
    ax.scatter(o["btc_usd_return"], o["ret_btc"], s=14, color=SLOT[1], zorder=3)
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    ax.axvline(0, color=INK["baseline"], linewidth=1)
    _pct(ax, "y")
    _pct(ax, "x")
    ax.set_xlabel("BTC price change over the month (USD)", fontsize=8.5, color=INK["secondary"])
    ax.set_title("25-delta covered call: monthly return in BTC", fontsize=9, color=INK["primary"], loc="left")
    a, b = res["covered_calls"]["25d"], res["covered_calls"]["10d"]
    _titles(fig, f"Covered calls earned a BTC holder {pc(a['ann_return'], 1, True)} a year (25-delta) and "
            f"{pc(b['ann_return'], 1, True)} (10-delta), before fees",
            f"Monthly calls sold against BTC at Deribit's traded implied volatilities, priced on each expiry's forward, less "
            f"calibrated spreads and fees. The 25-delta call collected {pc(a['premium_mean'], 1)} of a BTC a month and paid out "
            f"{pc(a['payoff_mean'], 1)} on average: in an average month when BTC rose more than 10%, it lost "
            f"{pc(-a['rally_months_mean_btc_return'], 1)} of a BTC.",
            "Roll at 08:00 UTC on each monthly expiry, settled at Deribit's delivery price. Hypothetical backtest. Sources: "
            "Deribit, Coinbase.")
    _save(fig, path)


def short_vol(s: pd.DataFrame, res: dict, stress_months: list, path) -> None:
    sm = res["stress_months"]
    lost_all = all(v["straddle_usd_notional"] < 0 for v in sm.values())
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), dpi=200, gridspec_kw={"width_ratios": [1.5, 1]})
    fig.subplots_adjust(left=0.07, right=0.97, top=0.72, bottom=0.14, wspace=0.25)
    ax = axes[0]
    _style(ax)
    x = s["expiry"].dt.tz_localize(None)
    hot = s["expiry"].dt.strftime("%Y-%m").isin(stress_months)
    ax.bar(x, s["ret_notional"], width=20, color=np.where(hot, SLOT[1], SLOT[0]), label="simulated, daily delta hedge")
    ax.plot(x, s["varswap_approx"], color=INK["primary"], linewidth=0.9, marker="o", markersize=2,
            label="variance-swap approximation")
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    _pct(ax)
    _years(ax)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK["secondary"], loc="lower right")
    ax.set_title("Monthly P&L per BTC of notional (stress months in orange)", fontsize=9, color=INK["primary"], loc="left")
    ax = axes[1]
    _style(ax)
    d = res["straddle"]["decomposition_per_notional"]
    keys = ["premium_minus_payoff", "hedge_pnl", "spread", "fees", "hedge_costs", "total"]
    names = ["premium −\npayoff", "delta\nhedge", "spread", "option\nfees", "hedge\ncosts", "total"]
    ax.bar(range(len(keys)), [d[k] for k in keys], color=[SLOT[0]] * 5 + [INK["primary"]], width=0.6)
    ax.axhline(0, color=INK["baseline"], linewidth=1)
    ax.set_xticks(range(len(keys)), names, fontsize=8)
    _pct(ax, "y", 1)
    ax.set_title("Average month, share of notional", fontsize=9, color=INK["primary"], loc="left")
    st = res["straddle"]["usd_on_notional"]
    _titles(fig, f"A delta-hedged short straddle earned {pc(st['ann_return'], 1)} a year on notional, with {st['ann_vol']:.0%} "
            f"volatility",
            f"One-month at-the-money straddles sold at each roll and hedged daily with the perpetual. The simulated P&L tracks "
            f"the variance-swap approximation (correlation {res['straddle']['corr_with_varswap_approx']:.2f}). The worst month "
            f"lost {pc(-st['worst_month'], 1)} of notional" + ("; it lost money in each of the "
            f"{len(sm)} stress months listed in config.yaml (chosen by hand)." if lost_all else "."),
            "In USD, before fees. Entry implied volatility from Deribit trades, priced on the expiry's forward; hedge at 08:00 UTC "
            "paying Binance funding. Hypothetical backtest. Sources: Deribit, Binance.")
    _save(fig, path)


def btc_investor(stats: dict, path, window: list, lost_all: bool, n_stress: int) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=200)
    fig.subplots_adjust(left=0.27, right=0.95, top=0.72, bottom=0.14)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=INK["grid"], linewidth=0.75)
    ks = list(stats)[::-1]
    y = np.arange(len(ks))
    vals = [stats[k]["ann_return"] for k in ks]
    ax.barh(y, vals, color=[SLOT[0] if v > 0 else SLOT[1] for v in vals], height=0.55)
    for yi, k in zip(y, ks):
        v, w = stats[k]["ann_return"], stats[k]["max_drawdown"]
        ax.text(max(v, 0) + 0.002, yi, f"{pc(v, 1, True)} a year, worst drawdown {pc(w, 0)}" if k != "hold BTC" else "the benchmark: 0",
                va="center", fontsize=8, color=INK["primary"])
    ax.set_yticks(y, ks, fontsize=8.5)
    ax.axvline(0, color=INK["primary"], linewidth=0.8)
    _pct(ax, "x")
    ax.set_xlim(min(vals) * 1.3, max(vals) * 2.6)
    a, b = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    _titles(fig, "For a BTC holder, none of the yields is free",
            f"Annualised return in BTC, before fees, over the same months (rolls {a.day} {a:%b %Y} – {b.day} {b:%b %Y}). The basis carry pays back its "
            f"funding through the hedge; covered calls give away BTC's rallies; the delta-hedged straddle earns the most but loses "
            f"when realised volatility jumps above what was sold" + (f": it lost money in each of the {n_stress} stress months "
            f"listed in config.yaml (chosen by hand)." if lost_all else "."),
            "Monthly, roll to roll. The basis-carry line is the BTC-hedged class from the first chapter. Hypothetical backtest. "
            "Sources: Deribit, Binance, Coinbase.")
    _save(fig, path)


def make_all(cfg, res, t, tables, alts, j, gross, net, FIG) -> None:
    vrp(t, tables["straddle"], res, FIG / "v1_volatility_premium.png")
    covered_calls(tables, res, FIG / "v2_covered_calls.png")
    short_vol(tables["straddle"], res, cfg["vol_overlay"]["stress_months"], FIG / "v3_short_straddle.png")
    sm = res["stress_months"]
    btc_investor(res["btc_investor"], FIG / "v4_btc_investor.png", res["btc_investor_window"],
                 all(v["straddle_usd_notional"] < 0 for v in sm.values()), len(sm))
