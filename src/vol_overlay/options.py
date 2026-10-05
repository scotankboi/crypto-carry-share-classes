"""Black-76 for BTC options quoted in BTC (Deribit's inverse options), zero rates.

Deribit quotes an option's implied volatility against the forward of its expiry (its "underlying
price"), not against the index. With the forward F as the underlying and zero rates,
    C_USD = F N(d1) - K N(d2),   d1 = [ln(F/K) + sigma^2 T / 2] / (sigma sqrt T),   d2 = d1 - sigma sqrt T
and an option that settles max(S_T - K, 0) / S_T BTC is worth c = C_USD / F BTC today. Put-call parity
in BTC is therefore
    c - p = (F - K) / F = 1 - K / F,
so a call and a put at the same strike reveal the forward:  F = K / (1 - (c - p)).
Pricing with the index S in place of F makes at-the-money calls several per cent too cheap and puts
too dear, because the monthly forward usually sits above the index. Strikes are chosen by the forward
delta N(d1), the market's convention for "25-delta". Every function takes the forward as its first
argument; with F = S they reduce to Black-Scholes on the index at zero rates.
"""
import numpy as np
from scipy.stats import norm


def d1(F, K, T, sigma):
    return (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))


def call_usd(F, K, T, sigma):
    a = d1(F, K, T, sigma)
    return F * norm.cdf(a) - K * norm.cdf(a - sigma * np.sqrt(T))


def put_usd(F, K, T, sigma):
    return call_usd(F, K, T, sigma) - F + K


def call_btc(F, K, T, sigma):
    return call_usd(F, K, T, sigma) / F


def put_btc(F, K, T, sigma):
    return put_usd(F, K, T, sigma) / F


def call_delta(F, K, T, sigma):
    return norm.cdf(d1(F, K, T, sigma))


def vega_usd(F, K, T, sigma):
    """USD price change per 1.00 of volatility (divide by 100 for one vol point)."""
    return F * norm.pdf(d1(F, K, T, sigma)) * np.sqrt(T)


def strike_for_delta(F, T, sigma, delta):
    """The strike whose forward call delta N(d1) equals `delta`."""
    return F * np.exp(-sigma * np.sqrt(T) * norm.ppf(delta) + 0.5 * sigma ** 2 * T)


def parity_forward(call_price_btc, put_price_btc, K):
    """The forward implied by BTC put-call parity, c - p = 1 - K / F."""
    return np.asarray(K, float) / (1 - (np.asarray(call_price_btc, float) - np.asarray(put_price_btc, float)))


def implied_forward(price_btc, K, T, sigma, is_call, lo, hi, iters: int = 80):
    """The forward at which Black-76 at the quoted IV reproduces a trade's BTC price (vectorised
    bisection on [lo, hi]). A call's BTC price rises with F; a put's falls."""
    price_btc, K, T, sigma = (np.asarray(x, float) for x in (price_btc, K, T, sigma))
    is_call = np.asarray(is_call, bool)
    lo, hi = np.asarray(lo, float).copy(), np.asarray(hi, float).copy()
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        model = np.where(is_call, call_btc(mid, K, T, sigma), put_btc(mid, K, T, sigma))
        too_high = np.where(is_call, model > price_btc, model < price_btc)
        hi = np.where(too_high, mid, hi)
        lo = np.where(too_high, lo, mid)
    return 0.5 * (lo + hi)
