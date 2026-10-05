import numpy as np
import pandas as pd
import pytest

from src import counterparty as cp, stress


FTX = {"petition_date": "2022-11-11", "btc_petition_price": 16871, "claim_class": "5A",
       "distributions": [{"date": "2025-05-30", "cumulative": 0.72}, {"date": "2025-09-30", "cumulative": 0.78},
                         {"date": "2026-03-31", "cumulative": 0.96}]}


def test_ftx_recovery_values_each_instalment_on_its_date():
    dates = pd.to_datetime(["2022-11-11", "2025-05-30", "2025-09-30", "2026-03-31"])
    btc = pd.Series([16871.0, 100000.0, 120000.0, 80000.0], index=dates)
    master = pd.Series([1.0, 1.2, 1.25, 1.3], index=dates)
    rec = cp.ftx_recovery(FTX, btc, master)
    assert [r["paid"] for r in rec["schedule"]] == pytest.approx([0.72, 0.06, 0.18])
    assert rec["usd_nominal"] == pytest.approx(0.96) and rec["unpaid"] == pytest.approx(0.04)
    # USD classes: each dollar repaid buys back master units at that date's price
    assert rec["usd_vs_master"] == pytest.approx(0.72 / 1.2 + 0.06 / 1.25 + 0.18 / 1.3)
    # BTC class: coins recovered per coin lost, each instalment converted at its own date's price
    assert rec["btc"] == pytest.approx(16871 * (0.72 / 100000 + 0.06 / 120000 + 0.18 / 80000))
    assert rec["years_to_first"] == pytest.approx((dates[1] - dates[0]).days / 365.25)


def test_ftx_recovery_with_flat_prices_is_the_nominal_share():
    idx = pd.date_range("2022-11-01", "2026-04-30")
    rec = cp.ftx_recovery(FTX, pd.Series(16871.0, index=idx), pd.Series(1.0, index=idx))
    assert rec["usd_vs_master"] == pytest.approx(0.96) and rec["btc"] == pytest.approx(0.96)


def test_btc_class_exposure_includes_hedge_margin():
    rep = cp.default_replay(pd.Series({"binance": 0.17, "bybit": 0.17}), {"usd_vs_master": 1.03, "btc": 0.2}, 1 / 3, "binance")
    r = rep.set_index(["venue", "class"])
    assert r.loc[("binance", "BTC hedged"), "exposure_share"] == pytest.approx(2 / 3 * 0.17 + 1 / 3)
    assert r.loc[("bybit", "BTC hedged"), "exposure_share"] == pytest.approx(2 / 3 * 0.17)
    assert r.loc[("binance", "USD / USDT"), "net_loss_after_recovery"] == 0.0


def test_expected_loss():
    share = pd.DataFrame({"a": [0.1, 0.2], "b": [0.15, 0.15]})
    el = cp.expected_loss(share, [0.02], [0.5]).iloc[0]
    assert el["expected_loss_annual"] == pytest.approx(0.02 * 0.5 * 0.30)
    assert el["single_default_loss_peak_exposure"] == pytest.approx(0.5 * 0.2)
    assert el["single_default_loss_mean_exposure"] == pytest.approx(0.5 * 0.15)


def test_stress_book_moves_only_with_the_basis_and_adl_is_relative():
    t = pd.date_range("2025-10-10 20:00", periods=120, freq="min", tz="UTC")
    px = np.r_[np.full(40, 100.0), np.linspace(100, 80, 20), np.linspace(80, 95, 60)]
    bars = lambda p: pd.DataFrame({"open_time": t, "open": p, "high": p, "low": p, "close": p})
    state = {"nav": 1000.0, "Q": 4.0, "n": {"v": 4.0}, "E": {"v": 200.0}, "S0": 100.0, "F0": {"v": 100.0}}
    out = stress.oct10(bars(px), {"v": bars(px)}, state, t[0], t[-1], [5], {"v": 0.025})
    assert out["book_mtm_worst_share_nav"] == pytest.approx(0.0)              # perp = spot: no basis, no P&L
    adl = out["venues"]["v"]["adl"]["5"]
    # the cascade runs from the first minute 5% below the open (minute 45) to the low (minute 59)
    assert adl["adl_minutes_tried"] == 15
    assert adl["worst_share_nav"] == pytest.approx(4.0 * (px[50] - px[45]) / 1000)     # closed mid-fall, re-shorted lower
    assert adl["best_share_nav"] == pytest.approx(4.0 * (px[64] - px[59]) / 1000)      # closed at the low, re-shorted higher
