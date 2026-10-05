import copy

import numpy as np
import pandas as pd
import pytest
import yaml

from src import risk
from src.config import ROOT, validate


def test_stats_on_a_known_path():
    idx = pd.date_range("2024-01-01", periods=366, freq="D")
    nav = pd.Series(100 * 1.0001 ** np.arange(366), index=idx)
    st = risk.stats(nav)
    assert st["ann_return"] == pytest.approx(1.0001 ** 365.25 - 1, rel=1e-9)        # 365 daily steps = 365/365.25 years
    assert st["max_drawdown"] == 0.0 and st["weekly_positive_ratio"] == 1.0


def test_sharpe_interval_brackets_the_estimate():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2022-01-01", periods=800, freq="D")
    nav = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.002, 800)), index=idx)
    st = risk.stats(nav, pd.Series(0.03, index=idx))
    lo, hi = st["sharpe_ci95"]
    assert lo < st["sharpe"] < hi


def test_lo_eta_is_sqrt_q_without_autocorrelation_and_smaller_with_it():
    rng = np.random.default_rng(0)
    x = rng.normal(size=100_000)
    assert risk.lo_eta(x) == pytest.approx(np.sqrt(12), rel=0.01)
    ar = np.zeros_like(x)
    for i in range(1, len(x)):                      # AR(1), rho = 0.7
        ar[i] = 0.7 * ar[i - 1] + x[i]
    rho = [0.7 ** k for k in range(1, 12)]
    expect = 12 / np.sqrt(12 + 2 * sum((12 - k) * r for k, r in zip(range(1, 12), rho)))
    assert risk.lo_eta(ar) == pytest.approx(expect, rel=0.02)


def test_sharpe_uses_monthly_excess_returns_not_daily():
    """A smooth daily path whose drift switches between two regimes: daily returns are highly
    autocorrelated, so the daily iid Sharpe is huge while the monthly, autocorrelation-adjusted one is
    small; the reported Sharpe is the latter, and equals annual excess / annual-horizon volatility."""
    idx = pd.date_range("2021-01-01", "2026-12-31", freq="D")
    drift = np.where(idx.year % 2 == 0, 0.16, 0.0) / 365
    nav = pd.Series(np.cumprod(1 + drift + 1e-5 * np.sin(np.arange(len(idx)))), index=idx)
    st = risk.stats(nav, pd.Series(0.05, index=idx))
    assert st["sharpe_daily_iid"] > 5 * abs(st["sharpe"])
    assert st["sharpe"] == pytest.approx(st["ann_excess_return"] / st["excess_vol_annual_horizon"], rel=1e-9)
    x = risk.monthly_excess(nav, pd.Series(0.05, index=idx)).to_numpy()
    assert st["sharpe"] == pytest.approx(x.mean() / x.std(ddof=1) * risk.lo_eta(x), rel=1e-9)
    assert st["months"] == 72


def test_monthly_excess_compounds_the_short_rate():
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    nav = pd.Series(np.cumprod(np.r_[1.0, np.full(len(idx) - 1, 1 + 0.04 / 360)]), index=idx)
    x = risk.monthly_excess(nav, pd.Series(0.04, index=idx))
    assert np.allclose(x, 0.0, atol=1e-12)


def test_hac_standard_error_matches_iid_formula_without_autocorrelation():
    rng = np.random.default_rng(2)
    x = rng.normal(0.01, 0.02, 20_000)
    sr = x.mean() / x.std()
    assert risk.sharpe_se_hac(x, lags=0) == pytest.approx(np.sqrt((1 + 0.5 * sr ** 2) / len(x)), rel=0.03)


def test_calendar_returns_start_from_first_nav():
    idx = pd.date_range("2024-06-01", "2025-12-31", freq="D")
    nav = pd.Series(np.linspace(100, 130, len(idx)), index=idx)
    y = risk.calendar_returns(nav)
    assert y.iloc[0] == pytest.approx(nav.loc["2024-12-31"] / 100 - 1)
    assert (1 + y).prod() == pytest.approx(1.3)


@pytest.fixture
def raw():
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def test_repo_config_valid(raw):
    validate(copy.deepcopy(raw))


@pytest.mark.parametrize("mutate,msg", [
    (lambda c: c["costs"].update(spot_takr=0.001), "unknown"),
    (lambda c: c["strategy"].pop("leverage"), "missing"),
    (lambda c: c["strategy"].update(leverage=True), "wrong type"),
    (lambda c: c["counterparty"].update(spot_at_custodian=1), "true or false"),
    (lambda c: c["strategy"].update(weights={"binance": 0.7, "bybit": 0.7}), "summing to 1"),
    (lambda c: c["venues"]["binance"].update(maintenance_margin=0.6), "maintenance"),
    (lambda c: c["sample"].update(end_utc="2020-01-01"), "precede"),
    (lambda c: c["master"].update(candidates=["perp_carry", "magic"]), "candidates"),
    (lambda c: c["counterparty"]["ftx"]["distributions"][1].update(cumulative=0.5), "non-decreasing"),
    (lambda c: c["margin"].update(topup_lag_hours=[1, 24]), "emergency_lag_hours"),
])
def test_bad_config_rejected(raw, mutate, msg):
    c = copy.deepcopy(raw)
    mutate(c)
    with pytest.raises(ValueError, match=msg):
        validate(c)
