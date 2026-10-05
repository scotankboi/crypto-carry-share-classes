"""Share classes: peg conversion, covered-interest-parity hedges, the BTC hedge, fees and the high-water mark."""
import numpy as np
import pandas as pd
import pytest

from src import share_classes as sc

DAYS = pd.date_range("2024-01-01", "2024-12-31", freq="D")


def flat(v=1.0, idx=DAYS):
    return pd.Series(v, index=idx)


def test_usd_index_equals_usdt_at_par_and_tracks_the_peg():
    master = pd.Series(np.linspace(100, 110, len(DAYS)), index=DAYS)
    assert np.allclose(sc.usd_index(master, flat()), master / master.iloc[0])
    p = flat().copy()
    p.iloc[-1] = 0.99
    assert sc.usd_index(master, p).iloc[-1] == pytest.approx(1.1 * 0.99)


def test_hedge_removes_fx_when_rates_are_zero():
    rng = np.random.default_rng(0)
    fx = pd.Series(150 * np.exp(np.cumsum(rng.normal(0, 0.01, len(DAYS)))), index=DAYS)
    h = sc.hedged_class(flat(), fx, flat(0.0), flat(0.0), 0.0)
    assert np.allclose(h["index"], 1.0, atol=1e-12)                 # flat master: FX moves fully hedged


def test_equal_rates_and_flat_fx_reproduce_the_usd_class():
    usd = pd.Series(np.linspace(1, 1.08, len(DAYS)), index=DAYS)
    h = sc.hedged_class(usd, flat(150.0), flat(0.04), flat(0.04), 0.0, ccy_days=360)
    assert np.allclose(h["index"], usd, atol=1e-12)


def test_hedge_cost_is_the_rate_gap():
    h = sc.hedged_class(flat(), flat(150.0), flat(0.05), flat(0.0), 0.0)
    assert h["index"].iloc[-1] - 1 == pytest.approx(-0.05 * 365 / 360, abs=0.003)
    hb = sc.hedged_class(flat(), flat(150.0), flat(0.05), flat(0.0), -0.003)
    assert hb["index"].iloc[-1] < h["index"].iloc[-1]                # a negative basis costs more


def test_btc_class_pays_the_hedge_carry():
    usd = pd.Series(1.08 ** (np.arange(len(DAYS)) / 365), index=DAYS)
    f = 0.10 / 365
    out = sc.btc_class(usd, flat(50000.0), flat(-50000.0 * f), 1 / 3, 0.0)
    ann = out["index"].iloc[-1] ** (365 / (len(DAYS) - 1)) - 1
    assert ann == pytest.approx((2 / 3) * 0.08 - 0.10, abs=0.004)
    up = pd.Series(np.linspace(50000, 80000, len(DAYS)), index=DAYS)
    pnl = up.diff().fillna(0.0)                                      # a perfect long hedge with no carry
    kept = sc.btc_class(flat(), up, pnl, 1 / 3, 0.0)
    assert kept["index"].iloc[-1] == pytest.approx(1.0, rel=1e-9)    # BTC value kept exactly


def test_hedge_pnl_per_btc_aggregates_mtm_and_funding():
    idx = pd.date_range("2024-01-01 17:00", periods=24, freq="h", tz="UTC")
    fr = pd.DataFrame({"F_x": np.arange(24.0) + 100, "F_mtm_x": np.arange(24.0) + 100, "f_x": 0.0}, index=idx)
    fr.loc[idx[7], "f_x"] = 0.001
    p = sc.hedge_pnl_per_btc(fr, "x", 16)
    assert p.sum() == pytest.approx(23 - 0.001 * 107)


def test_fees_management_only():
    out = sc.apply_fees(flat(), 0.015, 0.0)
    assert out["nav"].iloc[-1] == pytest.approx(100 * (1 - 0.015 / 365) ** (len(DAYS) - 1), rel=1e-12)


def test_performance_fee_and_high_water_mark():
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    g = pd.Series(1.0, index=idx)
    g.loc["2024-02-01":] = 1.10          # +10% in Q1
    g.loc["2024-05-01":] = 1.00          # -9% in Q2
    g.loc["2024-08-01":] = 1.05          # partial recovery in Q3: below the high-water mark
    g.loc["2024-11-01":] = 1.20          # new high in Q4
    out = sc.apply_fees(g, 0.0, 0.2)
    paid = out.loc[out["perf_paid"] > 0, "perf_paid"]
    assert list(paid.index) == [pd.Timestamp("2024-03-31"), pd.Timestamp("2024-12-31")]
    assert paid.iloc[0] == pytest.approx(0.2 * 10.0)
    hwm1 = 110 - 2.0
    assert paid.iloc[1] == pytest.approx(0.2 * (108 / 1.10 * 1.20 - hwm1))
    assert out.loc["2024-09-30", "perf_paid"] == 0.0


def test_btc_class_variants_follow_their_algebra():
    """Master log return r = ln 1.08, funding f = 10% a year: USDT margin not netted earns (1 - m) r - f;
    coin-margined (1 - m)(r - f); netted, with no separate margin, r - f (continuously compounded)."""
    usd = pd.Series(1.08 ** (np.arange(len(DAYS)) / 365), index=DAYS)
    hp = flat(-50000.0 * 0.10 / 365)
    r, m = np.log(1.08), 1 / 3
    ann = lambda out: out["index"].iloc[-1] ** (365 / (len(DAYS) - 1)) - 1
    assert ann(sc.btc_class(usd, flat(50000.0), hp, m, 0.0)) == pytest.approx(np.expm1((1 - m) * r - 0.10), abs=5e-4)
    assert ann(sc.btc_class(usd, flat(50000.0), hp, m, 0.0, margin_in_btc=True)) == pytest.approx(np.expm1((1 - m) * (r - 0.10)), abs=5e-4)
    assert ann(sc.btc_class(usd, flat(50000.0), hp, 0.0, 0.0)) == pytest.approx(np.expm1(r - 0.10), abs=5e-4)


def test_coin_margined_btc_class_keeps_btc_when_price_moves():
    up = pd.Series(np.linspace(50000, 80000, len(DAYS)), index=DAYS)
    out = sc.btc_class(flat(), up, up.diff().fillna(0.0), 1 / 3, 0.0, margin_in_btc=True)
    assert out["index"].iloc[-1] == pytest.approx(1.0, rel=1e-9)


def test_usdt_close_is_used_from_the_next_day():
    """A daily candle opened at 00:00 UTC on day d closes at 24:00, after that day's NAV hour."""
    c = pd.DataFrame({"open_time": pd.to_datetime(["2022-05-10", "2022-05-11"]).tz_localize("UTC"), "close": [0.999, 0.996]})
    p = sc.usdt_usd_known_by_nav(c)
    assert p.loc["2022-05-12"] == 0.996 and p.loc["2022-05-11"] == 0.999 and pd.Timestamp("2022-05-10") not in p.index
