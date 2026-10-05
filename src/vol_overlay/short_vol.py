"""Market-neutral short volatility: sell a one-month at-the-money straddle, delta-hedge it daily.

At each monthly roll, sell one call and one put (1 BTC each) on the next monthly expiry at the strike
nearest the forward that traded on both sides in the roll window, at the median implied volatility of
those trades (fallback: DVOL plus the calibrated at-the-money skew), sold below that by the calibrated
half-spread. Options are priced with the expiry's forward F0 (covered_call.forward_ratio) as the
underlying, and the BTC premium is converted to USD at the roll's delivery price S0. Once a day at
08:00 UTC the position is hedged with the Binance perpetual to the straddle's Black-76 delta at the
entry volatility, with the forward on day d taken as S_d (F0 / S0)^(tau_d / T) (the basis decays to
zero at expiry); the hedge pays or receives perp funding. P&L per straddle, in USD:
    premium - spread - fees - |S_T - K| + sum_d h_d (S_d+1 - S_d) - sum_d h_d S_d f_d - hedge costs
It is reported per BTC of notional, in USD (P&L / S_0) and in BTC (P&L / S_T: Deribit settles in BTC).

Cross-check: a delta-hedged option earns about vega x (sigma_implied^2 - sigma_realised^2) / (2 sigma),
the payoff of a variance swap; this approximation is computed next to the simulated P&L.
"""
import numpy as np
import pandas as pd

from . import options as bs
from .covered_call import forward_ratio, roll_times, traded_strikes


def run(trades: pd.DataFrame, delivery: pd.Series, dvol_08: pd.Series, funding_daily: pd.Series, cfg: dict,
        perp_cost: float, calib: dict, spread_multiplier: float = 1.0) -> pd.DataFrame:
    vo = cfg["vol_overlay"]
    rolls = roll_times(vo["first_expiry"], vo["last_expiry"], vo["roll_hour_utc"])
    window = pd.Timedelta(minutes=vo["trade_window_minutes"])
    rows = []
    for t0, t1 in zip(rolls[:-1], rolls[1:]):
        d0, d1_ = t0.tz_localize(None).normalize(), t1.tz_localize(None).normalize()
        path = delivery.loc[d0:d1_]
        S0, ST = float(path.iloc[0]), float(path.iloc[-1])
        T = (t1 - t0).total_seconds() / (365.25 * 86400)
        ratio = forward_ratio(trades, t0, t1)
        F0 = S0 * ratio
        calls = traded_strikes(trades, t0, t1, window, "C").set_index("strike")
        puts = traded_strikes(trades, t0, t1, window, "P").set_index("strike")
        both = calls.index.intersection(puts.index)
        if len(both):
            K = float(min(both, key=lambda k: abs(k - F0)))
            sig, src = float(np.median([calls.at[K, "iv"], puts.at[K, "iv"]])), "trades"
        else:
            K, sig, src = F0, float(dvol_08.loc[d0]) / 100 + calib["skew"][0.5] / 100, "fallback"
        c_usd, p_usd = float(bs.call_btc(F0, K, T, sig)) * S0, float(bs.put_btc(F0, K, T, sig)) * S0
        vega = float(bs.vega_usd(F0, K, T, sig)) / F0 * S0
        spread = 2 * vega * calib["half_spread"][0.5] * spread_multiplier / 100
        fees = sum(min(vo["option_fee"] * S0, vo["option_fee_cap"] * p) for p in (c_usd, p_usd))
        hedge, cost, h_prev = 0.0, 0.0, 0.0
        days = path.index
        for i in range(len(days) - 1):
            S = float(path.iloc[i])
            tau = max((t1 - (days[i] + pd.Timedelta(hours=8)).tz_localize("UTC")).total_seconds() / (365.25 * 86400), 1e-9)
            h = 2 * float(bs.call_delta(S * ratio ** (tau / T), K, tau, sig)) - 1     # long perp units offsetting the short straddle
            cost += abs(h - h_prev) * S * perp_cost
            f = float(funding_daily.get(days[i + 1], 0.0))
            hedge += h * (float(path.iloc[i + 1]) - S) - h * S * f
            h_prev = h
        cost += abs(h_prev) * ST * perp_cost
        payoff = abs(ST - K)
        sfee = min(vo["settlement_fee"] * ST, vo["option_fee_cap"] * payoff) if payoff > 0 else 0.0
        pnl = c_usd + p_usd - spread - fees - payoff - sfee + hedge - cost
        r = np.log(path).diff().dropna()
        rv = float(np.sqrt(365 / len(r) * (r ** 2).sum())) if len(r) else np.nan
        rows.append({"roll": t0, "expiry": t1, "S0": S0, "F0": F0, "ST": ST, "strike": K, "iv": sig, "source": src,
                     "dvol": float(dvol_08.loc[d0]) / 100, "rv": rv, "premium_usd": c_usd + p_usd, "spread_usd": spread,
                     "fees_usd": fees + sfee, "payoff_usd": payoff, "hedge_pnl_usd": hedge, "hedge_cost_usd": cost,
                     "pnl_usd": pnl, "ret_notional": pnl / S0, "ret_btc": pnl / ST,
                     "varswap_approx": 2 * vega * (sig ** 2 - rv ** 2) / (2 * sig) / S0})
    return pd.DataFrame(rows)
