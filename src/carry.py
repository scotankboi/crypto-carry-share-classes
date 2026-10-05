"""The carry itself: perp funding, the quarterly and CME basis, their gap, and how the regime changed.

    funding (annualised)      sum of settlements over a window * 365 / days
    quarterly basis           (F_q / S - 1) * 365 / days to expiry, the held Binance quarterly, days > 7
    CME basis                 (F_CME / S_USD - 1) * 365 / days to the front expiry, from Yahoo's daily
                              close of the continuous front month (BTC=F) and Coinbase BTC-USD at 15:00
                              Chicago, the CME settlement time; whether Yahoo's close is the official
                              settlement is not verified. The last Friday of the month is the expiry;
                              days < 7 to expiry and the first trading day after each expiry (when the
                              continuous series switches contract) are excluded
    calendar carry            per quarter: perp funding actually received while short the perp,
                              minus the quarterly basis locked at the start of that quarter, the carry
                              a BTC holder can earn without selling BTC (short perp, long quarterly)

Regimes: Bai and Perron (1998, 2003) multiple mean shifts in weekly funding, found by dynamic
programming over all segmentations with a minimum segment length; the number of breaks is chosen by
BIC. Break dates are estimates; the README pairs them with the events they sit near, causally untested.
"""
import numpy as np
import pandas as pd


def last_friday(year: int, month: int) -> pd.Timestamp:
    end = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    return end - pd.Timedelta(days=(end.weekday() - 4) % 7)


def cme_basis(cme: pd.DataFrame, btcusd_1h: pd.DataFrame) -> pd.DataFrame:
    """cme: daily rows (date, close); btcusd_1h: Coinbase hourly klines (open_time, close)."""
    d = cme[["date", "close"]].rename(columns={"close": "F"}).sort_values("date").reset_index(drop=True)
    settle = (d["date"] + pd.Timedelta(hours=15)).dt.tz_localize("America/Chicago").dt.tz_convert("UTC")
    spot = pd.Series(btcusd_1h["close"].to_numpy(), index=(btcusd_1h["open_time"] + pd.Timedelta(hours=1)))
    d["S"] = spot.reindex(settle.to_numpy()).to_numpy()
    exp = d["date"].map(lambda t: last_friday(t.year, t.month))
    exp = exp.where(exp >= d["date"], d["date"].map(lambda t: last_friday((t + pd.offsets.MonthBegin(1)).year,
                                                                           (t + pd.offsets.MonthBegin(1)).month)))
    d["expiry"] = exp
    d["days"] = (d["expiry"] - d["date"]).dt.days
    # the most recent expiry strictly before each date: this month's if it has passed, else last month's
    this = d["date"].map(lambda t: last_friday(t.year, t.month))
    prev_m = d["date"].map(lambda t: t.replace(day=1) - pd.Timedelta(days=1))
    last = prev_m.map(lambda t: last_friday(t.year, t.month))
    prev_exp = this.where(this < d["date"], last)
    # the first row after each expiry is the roll day (rows are trading days, so weekends are skipped)
    d["roll_day"] = ~prev_exp.duplicated() & (d.index > d.index.min())
    d["basis"] = d["F"] / d["S"] - 1
    d["ann_basis"] = d["basis"] * 365 / d["days"]
    d["excluded"] = (d["days"] < 7) | d["roll_day"] | d["S"].isna()
    return d


def cme_close_alignment(cme_tab: pd.DataFrame, btcusd_1h: pd.DataFrame, offsets=(-2, -1, 0, 1, 2)) -> dict:
    """Evidence on when Yahoo's daily close is struck: the standard deviation of day-to-day changes in
    the basis F / S - 1, with S taken at 15:00 Chicago plus each offset (hours), on consecutive used days.
    If the close is a 15:00 Chicago price, the basis is smoothest with S at that hour; otherwise the
    mismatch adds spot moves to the basis."""
    spot = pd.Series(btcusd_1h["close"].to_numpy(), index=(btcusd_1h["open_time"] + pd.Timedelta(hours=1)))
    ok = ~cme_tab["excluded"].to_numpy()
    both = ok & np.r_[False, ok[:-1]]
    out = {}
    for off in offsets:
        t = (cme_tab["date"] + pd.Timedelta(hours=15 + off)).dt.tz_localize("America/Chicago").dt.tz_convert("UTC")
        basis = pd.Series(cme_tab["F"].to_numpy() / spot.reindex(t.to_numpy()).to_numpy() - 1)
        out[str(off)] = float(basis.diff()[both].std())
    return {"basis_daily_change_sd_by_spot_hour_offset": out, "days": int(both.sum())}


def daily_at(hourly: pd.Series, hour: int) -> pd.Series:
    s = hourly[hourly.index.hour == hour]
    s.index = s.index.normalize().tz_localize(None)
    return s


def funding_daily(f_hourly: pd.Series) -> pd.Series:
    """Funding settled per UTC day (decimal per day)."""
    return f_hourly.groupby(f_hourly.index.floor("D").tz_localize(None)).sum()


def calendar_carry(qframe: pd.DataFrame, funding_hourly: pd.Series) -> pd.DataFrame:
    """Per held quarterly contract: basis locked at entry vs perp funding received over the same hours."""
    rows = []
    for sym, g in qframe.groupby("symbol", sort=False):
        g = g.iloc[1:] if g["days_to_expiry"].iloc[0] < 1 else g
        if len(g) < 24 * 20:
            continue
        start, end = g.index[0], g.index[-1]
        years = (end - start).total_seconds() / (365 * 86400)
        locked = g["F_binance_q"].iloc[0] / g["S"].iloc[0] - 1
        fund = funding_hourly.loc[start:end].sum()
        rows.append({"symbol": sym, "start": start, "end": end, "days": years * 365, "basis_locked": locked,
                     "basis_locked_ann": locked / years, "perp_funding": fund, "perp_funding_ann": fund / years,
                     "calendar_carry_ann": (fund - locked) / years})
    return pd.DataFrame(rows)


def bai_perron(y: pd.Series, max_breaks: int, min_seg: int) -> dict:
    """Mean-shift breaks by dynamic programming (Bai and Perron 2003); BIC picks the number of breaks."""
    x = y.to_numpy(float)
    n = len(x)
    c1, c2 = np.r_[0, np.cumsum(x)], np.r_[0, np.cumsum(x ** 2)]

    def ssr(i, j):                         # segment x[i:j]
        m = j - i
        s = c1[j] - c1[i]
        return (c2[j] - c2[i]) - s * s / m

    INF = np.inf
    # best[k][j]: min SSR of x[:j] with k breaks; arg[k][j]: position of the last break
    best = [[INF] * (n + 1) for _ in range(max_breaks + 1)]
    arg = [[None] * (n + 1) for _ in range(max_breaks + 1)]
    for j in range(min_seg, n + 1):
        best[0][j] = ssr(0, j)
    for k in range(1, max_breaks + 1):
        for j in range((k + 1) * min_seg, n + 1):
            for b in range(k * min_seg, j - min_seg + 1):
                v = best[k - 1][b] + ssr(b, j)
                if v < best[k][j]:
                    best[k][j], arg[k][j] = v, b
    out = []
    for k in range(max_breaks + 1):
        if best[k][n] == INF:
            continue
        bic = n * np.log(best[k][n] / n) + (2 * k + 1) * np.log(n)
        bps, j = [], n
        for kk in range(k, 0, -1):
            j = arg[kk][j]
            bps.append(j)
        out.append({"breaks": k, "ssr": best[k][n], "bic": bic, "positions": sorted(bps)})
    pick = min(out, key=lambda r: r["bic"])
    edges = [0, *pick["positions"], n]
    segs = [{"start": str(y.index[a].date()), "end": str(y.index[b - 1].date()), "mean": float(x[a:b].mean()), "weeks": b - a}
            for a, b in zip(edges[:-1], edges[1:])]
    return {"n_breaks": pick["breaks"], "break_dates": [str(y.index[p].date()) for p in pick["positions"]],
            "segments": segs, "bic_by_breaks": {r["breaks"]: float(r["bic"]) for r in out}}
