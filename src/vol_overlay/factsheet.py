"""One-page factsheet for a BTC class that sells 25-delta covered calls (A4 PDF and PNG)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ..factsheet import footer, header  # noqa: E402
from ..plots import INK, SLOT, _esc, _pct, _style, _wrap, num, pc  # noqa: E402


def build(cfg: dict, res: dict, gross: pd.Series, net: pd.Series, table: pd.DataFrame, path) -> None:
    n, g, a = res["covered_call_class"]["net"], res["covered_call_class"]["gross"], res["covered_calls"]["25d"]
    fig = plt.figure(figsize=(8.27, 11.69), dpi=150)
    fig.patch.set_facecolor(INK["surface"])
    L, T = 0.06, INK["secondary"]
    header(fig, "Hypothetical backtest: BTC covered-call class",
           _wrap("Holds BTC and sells one 25-delta call on Deribit each month against it; premiums and payouts settle in BTC. "
                 "Simulated on public option trades with assumed fees.", 118),
           f"Period {table['roll'].iloc[0]:%Y-%m-%d} to {table['expiry'].iloc[-1]:%Y-%m-%d} | NAV and returns in BTC, after assumed "
           f"fees | monthly roll at 08:00 UTC")
    tiles = [("Annualised return (BTC)", pc(n["ann_return"], 1, True)), ("Volatility (monthly, annualised)", pc(n["ann_vol"], 1)),
             ("Worst month", pc(n["worst_month"], 1, True)), ("Max drawdown", pc(n["max_drawdown"], 1)),
             ("Positive months", f"{n['share_positive']:.0%}"), ("Months the call paid out", f"{a['share_months_paid_out']:.0%}")]
    for i, (k, v) in enumerate(tiles):
        x, y = L + (i % 3) * 0.3, 0.875 - (i // 3) * 0.052
        fig.text(x, y, k, fontsize=7.8, color=INK["muted"], va="top")
        fig.text(x, y - 0.015, v, fontsize=15, color=INK["primary"], va="top", fontweight="bold")
    ax = fig.add_axes([0.08, 0.6, 0.86, 0.15])
    _style(ax)
    ax.plot(net.index, net / net.iloc[0] - 1, color=SLOT[1], linewidth=1.6, label="after fees")
    ax.plot(gross.index, gross / gross.iloc[0] - 1, color=INK["muted"], linewidth=0.9, linestyle="--", label="before fees")
    ax.axhline(0, color=INK["primary"], linewidth=0.8)
    _pct(ax)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=7.5, labelcolor=INK["secondary"], loc="lower left")
    ax.set_title("Cumulative return in BTC (0% = just holding BTC)", fontsize=9, color=INK["primary"], loc="left")

    r = net.pct_change().dropna()
    grid = pd.DataFrame({"y": r.index.year, "m": r.index.month, "r": r.to_numpy()}).pivot_table(index="y", columns="m", values="r")
    yr = (1 + r).groupby(r.index.year).prod() - 1
    fig.text(L, 0.565, "Monthly returns in BTC (after fees, by expiry month)", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    cols = list(range(1, 13)) + ["Year"]
    xs = [L + 0.1 + j * 0.0635 for j in range(len(cols))]
    y = 0.543
    for x, c in zip(xs, cols):
        fig.text(x, y, pd.Timestamp(2000, c, 1).strftime("%b") if c != "Year" else "Year", fontsize=6.8, color=INK["muted"],
                 va="top", ha="right")
    for yy in grid.index:
        y -= 0.0135
        fig.text(L, y, str(yy), fontsize=7, color=INK["muted"], va="top")
        for x, c in zip(xs, cols):
            v = yr.get(yy) if c == "Year" else grid.loc[yy].get(c)
            if pd.notna(v):
                fig.text(x, y, num(v * 100, 1, True), fontsize=6.8, va="top", ha="right",
                         color=INK["primary"] if c == "Year" else (T if round(v * 100, 1) >= 0 else "#b03a2e"),
                         fontweight="bold" if c == "Year" else "normal")
    y -= 0.022
    sc = cfg["share_classes"]
    terms = [("Class currency", "BTC"),
             ("Overlay", "Sell one call per BTC held, 25-delta on the expiry's forward, on the next monthly expiry; settles in BTC"),
             ("Premium", f"{pc(a['premium_mean'], 2)} of a BTC a month on average, strike {a['moneyness_mean']:.0%} above spot"),
             ("Paid out", f"{pc(a['payoff_mean'], 2)} of a BTC a month on average, in {a['share_months_paid_out']:.0%} of months"),
             ("Fees (assumed)", f"{sc['management_fee']:.1%} management; {sc['performance_fee']:.0%} performance above a "
                                "high-water mark, quarterly"),
             ("Before fees", f"{pc(g['ann_return'], 1, True)} a year in BTC")]
    fig.text(L, y, "Assumed terms", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    yt = y - 0.02
    for k, v in terms:
        fig.text(L, yt, k, fontsize=7.4, color=INK["muted"], va="top")
        w = _wrap(v, 46)
        fig.text(L + 0.14, yt, w, fontsize=7.4, color=T, va="top", linespacing=1.25)
        yt -= 0.0125 * (w.count("\n") + 1) + 0.004
    st = res["stress_months"]
    risks = [f"The call caps BTC's rallies: in the {a['rally_months']} months BTC rose more than 10% (by "
             f"{pc(a['rally_months_mean_btc_price_return'], 0)} on average), the overlay gave back "
             f"{pc(-a['rally_months_mean_btc_return'], 1)} of a BTC, before fees.",
             f"Worst month, before fees: expiry {a['worst_month_expiry']} ({pc(a['worst_month'], 1, True)}). March 2024 (BTC "
             f"{pc(st['2024-03']['btc_price'], 0, True)}): {pc(st['2024-03']['cc_25d_btc'], 1, True)}.",
             "Falling markets do not hurt the overlay itself (the call expires worthless), but the investor holds BTC throughout.",
             "Prices are Deribit trades at each roll; size, slippage and venue risk beyond the measured spreads are not modelled."]
    fig.text(0.53, y, "How it behaves", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    yr_ = y - 0.02
    for line in risks:
        w = _wrap(line, 62)
        fig.text(0.53, yr_, _esc(w), fontsize=7.4, color=T, va="top", linespacing=1.25)
        yr_ -= 0.0125 * (w.count("\n") + 1) + 0.006
    yc = min(yt, yr_) - 0.016
    fig.text(L, yc, "A BTC holder's alternatives, before fees (same months)", fontsize=9.5, color=INK["primary"], fontweight="bold", va="top")
    heads = [("Strategy", L, "left"), ("Return in BTC", 0.55, "right"), ("Volatility", 0.67, "right"),
             ("Worst month", 0.79, "right"), ("Max drawdown", 0.92, "right")]
    yc -= 0.018
    for h, x, ha in heads:
        fig.text(x, yc, h, fontsize=7, color=INK["muted"], va="top", ha=ha)
    for k, v in res["btc_investor"].items():
        yc -= 0.0142
        bold = "bold" if k == "covered call, 25-delta" else "normal"
        for (h, x, ha), t in zip(heads, [k, pc(v["ann_return"], 1, True), pc(v["ann_vol"], 1), pc(v["worst_month"], 1, True),
                                         pc(v["max_drawdown"], 1)]):
            fig.text(x, yc, t, fontsize=7.4, color=INK["primary"] if bold == "bold" else T, va="top", ha=ha, fontweight=bold)
    footer(fig)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=INK["surface"], metadata={"CreationDate": None})     # byte-reproducible PDF
    fig.savefig(path.with_suffix(".png"), facecolor=INK["surface"])
    plt.close(fig)
