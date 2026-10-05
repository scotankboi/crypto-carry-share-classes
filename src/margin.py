"""Margin survival for the short perpetual leg, and the leverage that is worth taking.

A short with margin ratio e = E / (n F) is liquidated when equity falls below maintenance m:
    e F - F x  <  m F (1 + x)    <=>    x  >  (e - m) / (1 + m)
for a price rise x that happens before margin can be topped up (lag T hours). The engine
(src/engine.py) does not hold e at the target 1/L: it tops margin up only when e leaves
1/L (1 +/- band), and then `lag` hours after the breach. Margin can therefore sit just inside the
lower band edge, e = (1 - band) / L, for up to a week, and the threshold that matters is the one from
that edge:
    x*(L) = ((1 - band) / L - m) / (1 + m)
The threshold from the target margin (band = 0) is reported next to it. Crypto trades around the
clock, so there is no closure cap: the risk is the speed of the move.

Two estimates of the annual frequency of a rise beyond x* within T hours, on BTC spot since 2018:
  1. empirical: breaches of overlapping hourly windows declustered into episodes (runs of
     consecutive breaching start hours); lambda = episodes / years, with an exact Poisson interval
  2. EVT: a generalised Pareto tail fitted above the q-quantile of the T-hour maximum rise, scaled by
     the windows per year and by the extremal index theta = episodes / exceedances at the threshold
P(at least one liquidation in a year) = 1 - exp(-lambda). The windows are nested: a rise within T hours
is also a rise within any longer window, so the true probability cannot fall as T grows. Separate tail
fits per lag (and declustering, which merges episodes in longer windows) can break that ordering, so
each estimate is replaced by its running maximum over the lags, and the larger of the two is used.
The result depends on the model (threshold, tail fit, sample); it is a guide, not a guarantee.
"""
import numpy as np
import pandas as pd
from scipy import stats as sps


def liquidation_rise(leverage: float, maintenance: float, band: float = 0.0) -> float:
    return ((1 - band) / leverage - maintenance) / (1 + maintenance)


def poisson_ci(k: int, years: float) -> tuple[float, float]:
    """Exact (Garwood) 95% interval for an annual rate from k events in `years`."""
    lo = sps.chi2.ppf(0.025, 2 * k) / 2 / years if k > 0 else 0.0
    hi = sps.chi2.ppf(0.975, 2 * (k + 1)) / 2 / years
    return float(lo), float(hi)


def max_rise(close: pd.Series, high: pd.Series, hours: int) -> pd.Series:
    """For each hour t: max over (t, t + hours] of high / close_t - 1."""
    fwd = high[::-1].rolling(hours, min_periods=hours).max()[::-1].shift(-1)
    return (fwd / close - 1).dropna()


def episodes(breach: pd.Series) -> int:
    b = breach.astype(bool).to_numpy()
    return int(b[0]) + int(((~b[:-1]) & b[1:]).sum()) if len(b) else 0


def gpd_tail(x: pd.Series, q: float) -> dict:
    u = float(x.quantile(q))
    exc = (x[x > u] - u).to_numpy()
    shape, _, scale = sps.genpareto.fit(exc, floc=0)
    return {"u": u, "q": q, "shape": float(shape), "scale": float(scale)}


def gpd_prob(t: dict, level: float, x: pd.Series) -> float:
    if level <= t["u"]:
        return float((x > level).mean())
    return float((1 - t["q"]) * sps.genpareto.sf(level - t["u"], t["shape"], loc=0, scale=t["scale"]))


def frontier(close: pd.Series, high: pd.Series, leverage_grid: list, lags: list, maintenance: float, q: float,
             alpha: float, band: float = 0.0) -> pd.DataFrame:
    years = (close.index.max() - close.index.min()).total_seconds() / (365.25 * 86400)
    rows = []
    for T in sorted(lags):
        rise = max_rise(close, high, T)
        tail = gpd_tail(rise, q)
        theta = episodes(rise > tail["u"]) / max(1, int((rise > tail["u"]).sum()))
        for L in leverage_grid:
            x = liquidation_rise(L, maintenance, band)
            ep = episodes(rise > x)
            lo, hi = poisson_ci(ep, years)
            worst = rise[rise > x]
            rows.append({"topup_lag_h": T, "leverage": L, "liq_rise": x, "liq_rise_at_target": liquidation_rise(L, maintenance),
                         "episodes": ep, "years": years,
                         "p_empirical_raw": 1 - np.exp(-ep / years),
                         "p_empirical_ci95_lo": 1 - np.exp(-lo), "p_empirical_ci95_hi": 1 - np.exp(-hi),
                         "p_evt_raw": 1 - np.exp(-gpd_prob(tail, x, rise) * 8760 * theta),
                         "extremal_index": theta, "first_breach": str(worst.index.min()) if len(worst) else None})
    out = pd.DataFrame(rows)
    for k in ("empirical", "evt"):
        out[f"p_annual_{k}"] = out.groupby("leverage")[f"p_{k}_raw"].cummax()      # non-decreasing in the lag
    out["p_annual"] = out[["p_annual_empirical", "p_annual_evt"]].max(axis=1)
    out["below_reference"] = out["p_annual"] <= alpha
    return out.reset_index(drop=True)


def max_leverage(fr: pd.DataFrame, lag: int) -> float | None:
    """The highest leverage on the grid whose probability is at or below the reference level (alpha)."""
    ok = fr[(fr["topup_lag_h"] == lag) & fr["below_reference"]]
    return float(ok["leverage"].max()) if len(ok) else None
