"""Options chapter: BTC-quoted option algebra, realised volatility, strike selection, settlement and hedging."""
import numpy as np
import pandas as pd
import pytest

from src.clients.deribit import parse_instrument
from src.vol_overlay import covered_call as cc, options as bs, short_vol as sv, vrp


@pytest.mark.parametrize("K", [40000.0, 60000.0, 80000.0])
def test_put_call_parity_in_btc_uses_the_forward(K):
    F, T, sig = 60300.0, 30 / 365.25, 0.55
    assert bs.call_btc(F, K, T, sig) - bs.put_btc(F, K, T, sig) == pytest.approx(1 - K / F, abs=1e-12)
    assert bs.parity_forward(bs.call_btc(F, K, T, sig), bs.put_btc(F, K, T, sig), K) == pytest.approx(F, rel=1e-12)


@pytest.mark.parametrize("cp", ["C", "P"])
def test_implied_forward_inverts_the_price(cp):
    F, K, T, sig = 61000.0, np.array([55000.0, 60000.0, 66000.0]), 28 / 365.25, 0.6
    price = bs.call_btc(F, K, T, sig) if cp == "C" else bs.put_btc(F, K, T, sig)
    got = bs.implied_forward(price, K, T, sig, np.full(3, cp == "C"), np.full(3, 40000.0), np.full(3, 90000.0))
    assert np.allclose(got, F, rtol=1e-9)


@pytest.mark.parametrize("target", [0.1, 0.25, 0.5])
def test_strike_for_delta_inverts_delta(target):
    K = bs.strike_for_delta(60000.0, 30 / 365.25, 0.6, target)
    assert bs.call_delta(60000.0, K, 30 / 365.25, 0.6) == pytest.approx(target, abs=1e-12)


def test_forward_realised_vol_annualises_on_365_days():
    idx = pd.date_range("2024-01-01", periods=61, freq="D")
    price = pd.Series(100 * np.exp(np.cumsum(np.r_[0, np.tile([0.01, -0.01], 30)])), index=idx)
    rv = vrp.forward_rv(price, 30)
    assert rv.iloc[0] == pytest.approx(0.01 * np.sqrt(365))
    assert rv.iloc[30] == pytest.approx(0.01 * np.sqrt(365)) and np.isnan(rv.iloc[31])


def test_parse_instrument():
    e, k, cp = parse_instrument("BTC-29MAR24-70000-C")
    assert e == pd.Timestamp("2024-03-29 08:00", tz="UTC") and k == 70000.0 and cp == "C"


def _cfg(first="2024-01-26", last="2024-02-23"):
    return {"vol_overlay": {"first_expiry": first, "last_expiry": last, "roll_hour_utc": 8, "trade_window_minutes": 60,
                            "max_delta_miss": 0.05, "option_fee": 0.0003, "option_fee_cap": 0.125, "settlement_fee": 0.00015}}


def _trades(t0, t1, S, strikes_ivs, cp="C", ratio=1.0):
    """Trades priced as Deribit prices them: Black-76 on the forward F = S x ratio at the quoted IV."""
    rows = []
    F = S * ratio
    for K, iv in strikes_ivs:
        name = f"BTC-{t1:%d%b%y}-{int(K)}-{cp}".upper()
        T = (t1 - t0).total_seconds() / (365.25 * 86400)
        price = bs.call_btc(F, K, T, iv / 100) if cp == "C" else bs.put_btc(F, K, T, iv / 100)
        rows.append({"timestamp": t0, "trade_id": f"{name}-1", "instrument_name": name, "price": price, "iv": iv,
                     "index_price": S, "mark_price": price, "amount": 1.0, "direction": "sell", "roll": t0})
    return pd.DataFrame(rows)


CALIB = {"half_spread": {0.1: 0.0, 0.25: 0.0, 0.5: 0.0}, "skew": {0.1: 0.0, 0.25: 0.0, 0.5: 0.0}}


def test_covered_call_picks_the_target_strike_and_settles_on_the_expiry_price():
    t0, t1 = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")
    S, T = 40000.0, 28 / 365.25
    K25 = float(round(bs.strike_for_delta(S, T, 0.5, 0.25), -3))
    trades = cc.parse(_trades(t0, t1, S, [(K25 - 4000, 50.0), (K25, 50.0), (K25 + 6000, 50.0)]))
    delivery = pd.Series([S, 50000.0], index=pd.to_datetime(["2024-01-26", "2024-02-23"]))
    dvol = pd.Series([50.0], index=pd.to_datetime(["2024-01-26"]))
    out = cc.run(trades, delivery, dvol, _cfg(), 0.25, CALIB).iloc[0]
    assert out["source"] == "trades" and out["strike"] == K25
    premium = bs.call_btc(S, K25, T, 0.5)
    payoff = (50000 - K25) / 50000
    assert out["ret_btc"] == pytest.approx(premium - min(0.0003, 0.125 * premium) - payoff - min(0.00015, 0.125 * payoff))


def test_covered_call_falls_back_without_a_suitable_trade():
    t0, t1 = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")
    trades = cc.parse(_trades(t0, t1, 40000.0, [(80000.0, 50.0)]))           # far out of the money: delta ~0
    delivery = pd.Series([40000.0, 39000.0], index=pd.to_datetime(["2024-01-26", "2024-02-23"]))
    out = cc.run(trades, delivery, pd.Series([50.0], index=pd.to_datetime(["2024-01-26"])), _cfg(), 0.25, CALIB).iloc[0]
    assert out["source"] == "fallback" and out["delta"] == pytest.approx(0.25, abs=1e-9) and out["payoff"] == 0.0


def test_calibration_recovers_a_known_spread():
    t0, t1 = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")
    S, T, ratio = 40000.0, 28 / 365.25, 1.005
    F = S * ratio
    K = float(bs.strike_for_delta(F, T, 0.5, 0.25))
    tr = _trades(t0, t1, S, [(K, 50.0)], ratio=ratio)
    vega_pt = bs.vega_usd(F, K, T, 0.5) / F / 100
    tr["price"] = tr["mark_price"] - 0.4 * vega_pt                         # sold 0.4 vol points below mark
    chain = pd.concat([_trades(t0, t1, S, [(k, 50.0) for k in (37000.0, 38500.0, 40000.0, 41500.0, 43000.0)], c, ratio)
                       for c in ("C", "P")], ignore_index=True).assign(direction="buy")   # sets the forward
    cal = cc.calibrate(cc.parse(pd.concat([tr, chain], ignore_index=True)), pd.Series([52.0], index=pd.to_datetime(["2024-01-26"])))
    assert cal["half_spread"][0.25] == pytest.approx(0.4, rel=1e-4) and cal["skew"][0.25] == pytest.approx(-2.0)


def test_straddle_keeps_the_premium_when_nothing_moves():
    t0, t1 = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")
    S, T = 40000.0, 28 / 365.25
    tr = pd.concat([_trades(t0, t1, S, [(S, 50.0)], "C"), _trades(t0, t1, S, [(S, 50.0)], "P")], ignore_index=True)
    days = pd.date_range("2024-01-26", "2024-02-23", freq="D")
    out = sv.run(cc.parse(tr), pd.Series(S, index=days), pd.Series(50.0, index=days), pd.Series(0.0, index=days),
                 _cfg(), 0.0, CALIB).iloc[0]
    premium = bs.call_usd(S, S, T, 0.5) + bs.put_usd(S, S, T, 0.5)
    fees = 2 * min(0.0003 * S, 0.125 * premium / 2)
    assert out["pnl_usd"] == pytest.approx(premium - fees, rel=1e-9) and out["rv"] == 0.0


def test_hedged_straddle_matches_the_variance_swap_approximation():
    """A steady 10% trend has almost no volatility around it: sold at 50% implied, the hedged straddle gains about
    vega x (sigma_i^2 - sigma_r^2) / (2 sigma_i), while the unhedged straddle would be roughly flat."""
    t0, t1 = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")
    S = 40000.0
    tr = pd.concat([_trades(t0, t1, S, [(S, 50.0)], "C"), _trades(t0, t1, S, [(S, 50.0)], "P")], ignore_index=True)
    days = pd.date_range("2024-01-26", "2024-02-23", freq="D")
    path = pd.Series(S * np.exp(np.linspace(0, 0.10, len(days))), index=days)
    out = sv.run(cc.parse(tr), path, pd.Series(50.0, index=days), pd.Series(0.0, index=days), _cfg(), 0.0, CALIB).iloc[0]
    assert out["hedge_pnl_usd"] > 0
    assert out["pnl_usd"] == pytest.approx(out["varswap_approx"] * S, rel=0.1)
    assert abs(out["premium_usd"] - out["payoff_usd"]) < 0.2 * out["pnl_usd"]


def test_spread_is_charged_on_the_sale():
    t0, t1 = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")
    S, T = 40000.0, 28 / 365.25
    K = float(round(bs.strike_for_delta(S, T, 0.5, 0.25), -3))
    trades = cc.parse(_trades(t0, t1, S, [(K, 50.0)]))
    delivery = pd.Series([S, 30000.0], index=pd.to_datetime(["2024-01-26", "2024-02-23"]))
    dvol = pd.Series([50.0], index=pd.to_datetime(["2024-01-26"]))
    calib = {"half_spread": {0.25: 0.5}, "skew": {0.25: 0.0}}
    a = cc.run(trades, delivery, dvol, _cfg(), 0.25, CALIB).iloc[0]
    b = cc.run(trades, delivery, dvol, _cfg(), 0.25, calib).iloc[0]
    assert a["ret_btc"] - b["ret_btc"] == pytest.approx(bs.vega_usd(S, K, T, 0.5) / S * 0.5 / 100, rel=1e-9)


T0, T1 = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")


def _chain(S, ratio, strikes=(37000.0, 38500.0, 40000.0, 41500.0, 43000.0), iv=50.0):
    return pd.concat([_trades(T0, T1, S, [(K, iv) for K in strikes], c, ratio) for c in ("C", "P")], ignore_index=True)


def test_window_forward_from_put_call_parity():
    t = cc.parse(_chain(40000.0, 1.006))
    wf = t.attrs["window_forwards"].iloc[0]
    assert wf["source"] == "parity" and wf["parity_pairs"] == 5
    assert wf["ratio"] == pytest.approx(1.006, rel=1e-9) and wf["iv_ratio"] == pytest.approx(1.006, rel=1e-6)
    assert np.allclose(t["forward"], 40000.0 * 1.006)


def test_window_forward_falls_back_to_iv_when_pairs_are_few():
    t = cc.parse(_chain(40000.0, 1.004, strikes=(39000.0, 41000.0)))
    wf = t.attrs["window_forwards"].iloc[0]
    assert wf["source"] == "iv" and wf["ratio"] == pytest.approx(1.004, rel=1e-6)


def test_forward_pricing_reprices_trades_and_index_pricing_does_not():
    t = cc.parse(_chain(40000.0, 1.006))
    calls = t[t["cp"] == "C"]
    fwd = bs.call_btc(calls["forward"], calls["strike"], calls["T"], calls["iv"] / 100)
    idx = bs.call_btc(calls["index_price"], calls["strike"], calls["T"], calls["iv"] / 100)
    assert np.allclose(fwd, calls["price"], rtol=1e-9)
    assert (idx < calls["price"]).all()                                     # the index makes calls too cheap


def test_covered_call_prices_and_selects_strikes_on_the_forward():
    S, ratio, T = 40000.0, 1.006, 28 / 365.25
    F = S * ratio
    K25 = float(round(bs.strike_for_delta(F, T, 0.5, 0.25), -3))
    tr = pd.concat([_chain(S, ratio), _trades(T0, T1, S, [(K25, 50.0)], "C", ratio)], ignore_index=True)
    delivery = pd.Series([S, 50000.0], index=pd.to_datetime(["2024-01-26", "2024-02-23"]))
    out = cc.run(cc.parse(tr), delivery, pd.Series([50.0], index=pd.to_datetime(["2024-01-26"])), _cfg(), 0.25, CALIB).iloc[0]
    assert out["F0"] == pytest.approx(F) and out["strike"] == K25
    assert out["premium"] == pytest.approx(bs.call_btc(F, K25, T, 0.5), rel=1e-9)
    assert out["delta"] == pytest.approx(bs.call_delta(F, K25, T, 0.5))
