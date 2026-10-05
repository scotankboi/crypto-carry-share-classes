"""The volatility risk premium: implied volatility (DVOL) against the volatility that followed.

    RV_t = sqrt( 365 / n * sum_{i=1..n} r_{t+i}^2 ),  r = daily log return of BTC at 08:00 UTC, n = 30
    VRP_t = DVOL_t - RV_t   (vol points; DVOL^2 - RV^2 in variance terms)

DVOL is Deribit's 30-day implied volatility index, built from option prices like the VIX, so
DVOL^2 is a 30-day variance-swap rate. A positive VRP means option sellers were paid more than the
volatility they then bore.
"""
import numpy as np
import pandas as pd


def daily_at(hourly_close: pd.Series, hour: int) -> pd.Series:
    s = hourly_close[hourly_close.index.hour == hour]
    s.index = s.index.tz_localize(None).normalize()
    return s


def forward_rv(price: pd.Series, days: int) -> pd.Series:
    """Annualised realised volatility over the next `days` daily returns (zero-mean, 365-day year)."""
    r = np.log(price).diff()
    fwd = (r ** 2)[::-1].rolling(days, min_periods=days).sum()[::-1].shift(-1)
    return np.sqrt(365 / days * fwd)


def vrp_table(dvol_daily: pd.Series, price: pd.Series, days: int) -> pd.DataFrame:
    rv = forward_rv(price, days)
    t = pd.DataFrame({"dvol": dvol_daily / 100, "rv_fwd": rv}).dropna()
    t["vrp_vol"] = t["dvol"] - t["rv_fwd"]
    t["vrp_var"] = t["dvol"] ** 2 - t["rv_fwd"] ** 2
    return t
