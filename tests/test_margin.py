import numpy as np
import pandas as pd
import pytest

from src import margin


@pytest.mark.parametrize("L", [1, 2, 3, 5])
def test_liquidation_rise_leaves_maintenance(L):
    x = margin.liquidation_rise(L, 0.025)
    assert (1 / L - x) / (1 + x) == pytest.approx(0.025)


def test_max_rise_is_forward_only_and_episodes_decluster():
    idx = pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC")
    close = pd.Series(100.0, index=idx)
    high = pd.Series([100, 100, 150, 100, 100, 100.0], index=idx)
    r = margin.max_rise(close, high, 2)
    assert r.iloc[0] == pytest.approx(0.5) and r.iloc[2] == pytest.approx(0.0)
    assert margin.episodes(pd.Series([True, True, False, True])) == 2


def test_frontier_rises_with_leverage():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2018-01-01", periods=24 * 365 * 3, freq="h", tz="UTC")
    close = pd.Series(10000 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx)
    high = close * (1 + np.abs(rng.normal(0, 0.003, len(idx))))
    fr = margin.frontier(close, high, [1, 2, 5, 10], [24], 0.025, 0.95, 0.01)
    assert fr["p_annual"].is_monotonic_increasing
    assert margin.max_leverage(fr, 24) in (1, 2, 5, 10, None)


def test_liquidation_rise_from_the_band_edge():
    """The engine lets margin drift to (1 - band) / L before topping up; from there a smaller rise liquidates."""
    x = margin.liquidation_rise(2, 0.025, band=0.25)
    e = 0.75 / 2
    assert (e - x) / (1 + x) == pytest.approx(0.025)
    assert x < margin.liquidation_rise(2, 0.025)


def test_frontier_is_non_decreasing_in_the_topup_lag():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2018-01-01", periods=24 * 365 * 3, freq="h", tz="UTC")
    close = pd.Series(10000 * np.exp(np.cumsum(rng.standard_t(3, len(idx)) * 0.006)), index=idx)
    high = close * (1 + np.abs(rng.normal(0, 0.003, len(idx))))
    fr = margin.frontier(close, high, [1, 2, 3, 5], [1, 4, 24, 72], 0.025, 0.95, 0.01, band=0.25)
    for _, g in fr.groupby("leverage"):
        g = g.sort_values("topup_lag_h")
        for col in ("p_annual", "p_annual_evt", "p_annual_empirical"):
            assert g[col].is_monotonic_increasing
    assert (fr["p_annual_evt"] >= fr["p_evt_raw"]).all()
    assert (fr["liq_rise"] < fr["liq_rise_at_target"]).all()


def test_poisson_interval_brackets_the_rate():
    lo, hi = margin.poisson_ci(4, 8.0)
    assert lo < 0.5 < hi
    assert margin.poisson_ci(0, 8.0)[0] == 0.0 and margin.poisson_ci(0, 8.0)[1] == pytest.approx(3.689 / 8, rel=1e-3)
