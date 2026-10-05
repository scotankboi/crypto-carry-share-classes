"""Hedged-book engine: exact P&L identity, target margin, rebalancing, funding, rolls, liquidation flags."""
import numpy as np
import pandas as pd
import pytest

from src import engine

from .conftest import leg_frame

CAP = 1e8
LEGS = {"a": engine.LegCosts(0.0003), "b": engine.LegCosts(0.0003)}
W = {"a": 0.5, "b": 0.5}


def run(df, legs=LEGS, w=W, L=2.0, band=0.25, due=None, lag=4, mm=0.025):
    due = pd.Series(False, index=df.index) if due is None else due
    return engine.run(df, legs, w, leverage=L, band=band, maintenance=dict.fromkeys(w, mm), capital=CAP, spot_cost=0.0005,
                      rebalance_due=due, lag=lag)


def walk(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    S = 30000 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    return S, S * (1 + rng.normal(0.0005, 0.0005, n)), S * (1 + rng.normal(0.0004, 0.0005, n))


def test_identity_every_hour():
    S, Fa, Fb = walk()
    df = leg_frame(S, {"a": {"F": Fa, "f": 1e-4}, "b": {"F": Fb, "f": 5e-5}})
    led = run(df)
    assert led["check"].abs().max() < 1e-5
    parts = led[["funding", "convergence", "costs"]].sum().sum()
    assert led["nav"].iloc[-1] - CAP == pytest.approx(parts, abs=1e-3)


def test_entry_targets_and_costs():
    df = leg_frame([30000.0] * 3, {"a": {"F": [30000.0] * 3}, "b": {"F": [30000.0] * 3}})
    led = run(df, L=2)
    first = led.iloc[0]
    assert first["ratio_a"] == pytest.approx(0.5) and first["ratio_b"] == pytest.approx(0.5)
    assert first["E_a"] == pytest.approx(first["Q"] * 0.5 * 30000 * 0.5)
    cost = first["Q"] * 30000 * 0.0005 + first["Q"] * 30000 * 0.0003
    assert -first["costs"] == pytest.approx(cost, rel=1e-6)
    assert abs(first["cash"]) < 1.0                     # the capital is fully deployed


def test_funding_paid_on_mark_notional():
    n = 30
    df = leg_frame([30000.0] * n, {"a": {"F": [30100.0] * n, "f": 1e-4}, "b": {"F": [30000.0] * n}})
    led = run(df)
    Q = led["Q"].iloc[0]
    assert led["funding"].sum() == pytest.approx(0.5 * Q * 1e-4 * 30100 * (n - 1), rel=1e-12)


def test_dated_future_carry_arrives_as_convergence_and_rolls():
    n = 48
    S = np.full(n, 30000.0)
    F = np.linspace(30300, 30000, n)                     # basis decays to zero at expiry (last hour)
    F_next = np.full(n, 30500.0)
    roll = np.zeros(n, bool)
    roll[-1] = True
    F_fwd = F.copy()
    F_fwd[-1] = F_next[-1]                               # after the roll the position is in the next contract
    df = leg_frame(S, {"q": {"F": F_fwd, "F_mtm": np.where(roll, S, F), "roll": roll}})
    led = run(df, legs={"q": engine.LegCosts(0.0003, 0.0002)}, w={"q": 1.0})
    Q = led["Q"].iloc[0]
    assert led["convergence"].sum() == pytest.approx(Q * 300, rel=1e-9)     # the locked basis
    last = led.iloc[-1]
    assert "roll_q" in last["flags"]
    assert -last["costs"] == pytest.approx(Q * (30000 * 0.0002 + 30500 * 0.0003), rel=1e-9)
    assert led["check"].abs().max() < 1e-6


def test_weekly_rebalance_restores_target():
    S = np.linspace(30000, 33000, 200)
    df = leg_frame(S, {"a": {"F": S}, "b": {"F": S}})
    due = pd.Series(False, index=df.index)
    due.iloc[100] = True
    led = run(df, due=due, band=10.0)                    # wide band: only the scheduled rebalance acts
    assert "rebalance" in led["flags"].iloc[100]
    assert led["ratio_a"].iloc[100] == pytest.approx(0.5) and led["ratio_a"].iloc[99] < 0.5


def test_emergency_rebalance_after_lag():
    S = np.r_[np.full(10, 30000.0), np.full(20, 36000.0)]          # +20%: the shorts lose margin
    df = leg_frame(S, {"a": {"F": S}, "b": {"F": S}})
    led = run(df, band=0.25, lag=4)
    breach = led.index[led["flags"].str.contains("breach")][0]
    emer = led.index[led["flags"].str.contains("emergency")][0]
    assert emer - breach == pd.Timedelta(hours=4)
    assert led.loc[emer, "ratio_a"] == pytest.approx(0.5)


def test_liquidation_flag_on_intrahour_spike():
    S = np.full(10, 30000.0)
    H = S.copy()
    H[5] = 30000 * 1.6                                   # +60% intrahour spike at 2x
    df = leg_frame(S, {"a": {"F": S, "H": H}, "b": {"F": S}})
    led = run(df)
    assert "liquidation_a" in led["flags"].iloc[5] and "liquidation_b" not in led["flags"].iloc[5]


def test_resizing_a_dated_future_loses_carry_when_basis_rises_with_price():
    n = 24 * 60
    t = np.linspace(0, 1, n)
    S = 30000 * (1 + 0.3 * np.sin(np.pi * t))                       # rally, then back
    basis = 0.02 * (1 - t) + 0.03 * np.sin(np.pi * t)                # widens in the rally, zero at expiry
    F = S * (1 + basis)
    legs = {"q": engine.LegCosts(0.0)}
    locked = None
    for band, expect_full in ((100.0, True), (0.1, False)):
        led = engine.run(leg_frame(S, {"q": {"F": F}}), legs, {"q": 1.0}, leverage=2, band=band,
                         maintenance={"q": 0.0}, capital=CAP, spot_cost=0.0,
                         rebalance_due=pd.Series(False, index=pd.RangeIndex(n)), lag=1)
        locked = led["Q"].iloc[0] * (F[0] - S[0])
        if expect_full:
            assert led["convergence"].sum() == pytest.approx(locked, rel=1e-9)     # held to expiry: all of it
        else:
            assert led["flags"].str.contains("emergency").sum() > 0
            assert led["convergence"].sum() < 0.9 * locked                          # resized in the rally: less
