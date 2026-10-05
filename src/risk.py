"""Performance statistics in the form an allocator asks for them, in each class's own currency.

Daily NAVs are struck at the valuation hour, so every daily return is 24h apart (crypto trades every
day). Excess returns use the class currency's short rate (SOFR for USD and USDT, TONA for JPY, the KRW
3-month rate for KRW, zero for BTC).

Sharpe ratio and volatility. A carry's returns are strongly autocorrelated: the master's daily returns
have autocorrelations of about 0.5 at lags 1 to 5, and its monthly returns about 0.7 at lag 1, because
funding moves in regimes. Annualising a daily Sharpe ratio by sqrt(365) then overstates it several
times. Both statistics are therefore computed from monthly excess returns x_m and annualised with
Lo (2002), eq. (14), which allows for serial correlation:

    eta(q) = q / sqrt(q + 2 sum_{k=1}^{q-1} (q - k) rho_k),   q = 12,  rho_k = autocorrelations of x_m
    Sharpe = eta(q) * mean(x_m) / sd(x_m) = 12 mean(x_m) / (sd(x_m) q / eta(q))
The denominator, sd(x_m) q / eta(q), is the standard deviation of annual excess returns implied by the
monthly ones and their autocorrelation (`excess_vol_annual_horizon`). For a carry whose excess over
cash moves in regimes it is far larger than daily volatility annualised by sqrt(365) (`ann_vol`, the
conventional figure, reported for day-to-day risk), so Sharpe is not ann_return / ann_vol here.

The 95% interval is Lo's (2002) non-IID one: the standard error of the monthly Sharpe ratio comes from
the delta method on (mean, variance) with a Newey-West covariance of the moment conditions, and is
scaled by eta(q). eta is treated as known, so the interval is, if anything, too narrow. The daily
iid Sharpe ratio is kept in the output for comparison only.
"""
import numpy as np
import pandas as pd


def autocorr(x: np.ndarray, k: int) -> float:
    x = np.asarray(x, float) - np.mean(x)
    g0 = float(x @ x)
    return float(x[k:] @ x[:-k]) / g0 if g0 > 0 and 0 < k < len(x) else 0.0


def lo_eta(x: np.ndarray, q: int = 12) -> float:
    """Lo (2002) eq. (14) annualisation factor for q periods, from the sample autocorrelations of x."""
    var_ratio = q + 2 * sum((q - k) * autocorr(x, k) for k in range(1, q))
    return float(q / np.sqrt(max(var_ratio, 1e-12)))


def newey_west_lags(n: int) -> int:
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def sharpe_se_hac(x: np.ndarray, lags: int | None = None) -> float:
    """Standard error of mean / sd by the delta method, with a Newey-West (Bartlett) covariance of the
    moment conditions (x - mu, (x - mu)^2 - s2): Lo (2002), section 3, non-IID returns."""
    x = np.asarray(x, float)
    n = len(x)
    lags = newey_west_lags(n) if lags is None else lags
    mu, s2 = x.mean(), x.var()
    u = np.column_stack([x - mu, (x - mu) ** 2 - s2])
    S = u.T @ u / n
    for k in range(1, lags + 1):
        w = 1 - k / (lags + 1)
        G = u[k:].T @ u[:-k] / n
        S += w * (G + G.T)
    grad = np.array([1 / np.sqrt(s2), -mu / (2 * s2 ** 1.5)])
    return float(np.sqrt(grad @ S @ grad / n))


def monthly_excess(nav: pd.Series, rf_annual: pd.Series | None = None, day_count: float = 360.0) -> pd.Series:
    """Calendar-month returns of the NAV minus the compounded short rate over the same days. The first
    month runs from the first NAV."""
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    rf = (rf_annual.reindex(r.index).ffill().bfill() / day_count) if rf_annual is not None else pd.Series(0.0, index=r.index)
    m = r.index.to_period("M")
    return ((1 + r).groupby(m).prod() - 1) - ((1 + rf).groupby(m).prod() - 1)


def stats(nav: pd.Series, rf_annual: pd.Series | None = None, day_count: float = 360.0) -> dict:
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    per_year = len(r) / years
    rf = (rf_annual.reindex(r.index).ffill().bfill().to_numpy() / day_count) if rf_annual is not None else np.zeros(len(r))
    ex = r - rf
    total = nav.iloc[-1] / nav.iloc[0] - 1
    ann = (1 + total) ** (1 / years) - 1
    sd_d = r.std()
    x = monthly_excess(nav, rf_annual, day_count).to_numpy()
    sd_m = x.std(ddof=1)
    eta = lo_eta(x)
    sr_m = x.mean() / sd_m if sd_m > 0 else np.nan
    se_m = sharpe_se_hac(x) if sd_m > 0 else np.nan
    dd = nav / nav.cummax() - 1
    weekly = nav.resample("W-SUN").last().pct_change().dropna()
    return {"start": str(nav.index[0].date()), "end": str(nav.index[-1].date()), "years": years,
            "total_return": float(total), "ann_return": float(ann),
            "ann_vol": float(sd_d * np.sqrt(per_year)),
            "excess_vol_annual_horizon": float(sd_m * 12 / eta) if sd_m > 0 else 0.0,
            "ann_excess_return": float(x.mean() * 12),
            "sharpe": float(sr_m * eta),
            "sharpe_ci95": [float((sr_m - 1.96 * se_m) * eta), float((sr_m + 1.96 * se_m) * eta)],
            "sharpe_monthly_iid": float(sr_m * np.sqrt(12)),
            "sharpe_daily_iid": float(ex.mean() / sd_d * np.sqrt(per_year)) if sd_d > 0 else np.nan,
            "lo_eta_12": eta, "months": int(len(x)),
            "autocorr_monthly_lag1": autocorr(x, 1),
            "autocorr_daily_lags1to5": [autocorr(r.to_numpy(), k) for k in range(1, 6)],
            "max_drawdown": float(dd.min()), "max_drawdown_date": str(dd.idxmin().date()),
            "weekly_positive_ratio": float((weekly > 0).mean()),
            "monthly_positive_ratio": float((monthly_excess(nav) > 0).mean()),
            "worst_day": float(r.min()), "worst_day_date": str(r.idxmin().date()),
            "var95_daily": float(-r.quantile(0.05))}


def calendar_returns(nav: pd.Series, freq: str = "YE") -> pd.Series:
    """Returns per calendar period; the first period runs from the first NAV."""
    nav = nav.dropna()
    e = nav.resample(freq).last()
    out = e.pct_change()
    out.iloc[0] = e.iloc[0] / nav.iloc[0] - 1
    return out


def beta(nav: pd.Series, ref: pd.Series) -> dict:
    r = nav.pct_change()
    x = ref.reindex(nav.index).pct_change()
    j = pd.concat([r, x], axis=1).dropna()
    c = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
    return {"corr": c, "beta": float(c * j.iloc[:, 0].std() / j.iloc[:, 1].std())}
