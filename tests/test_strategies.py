"""Inputs to the engine: contract calendar, the held quarterly, funding timing."""
import numpy as np
import pandas as pd
import pytest

from src import strategies as stg
from src.clients import binance_vision as bv


def test_quarterly_symbols_last_friday():
    syms = bv.quarterly_symbols("BTCUSDT_", pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2021-12-31", tz="UTC"))
    assert syms[0] == ("BTCUSDT_210326", pd.Timestamp("2021-03-26 08:00", tz="UTC"))
    assert ("BTCUSDT_211231", pd.Timestamp("2021-12-31 08:00", tz="UTC")) in syms
    assert all(e.weekday() == 4 for _, e in syms)


def test_held_quarterly_rolls_at_expiry():
    e1, e2 = pd.Timestamp("2026-03-27 08:00", tz="UTC"), pd.Timestamp("2026-06-26 08:00", tz="UTC")
    t = pd.date_range("2026-03-27 05:00", periods=6, freq="h", tz="UTC")
    rows = [{"open_time": x - pd.Timedelta(hours=1), "close": 100.0 + i, "high": 101.0 + i, "symbol": s, "expiry": e}
            for i, x in enumerate(t) for s, e in (("Q1", e1), ("Q2", e2))]
    h = stg.held_quarterly(pd.DataFrame(rows), t)
    assert list(h["symbol"]) == ["Q1", "Q1", "Q1", "Q2", "Q2", "Q2"]      # at 08:00 the expiring one is no longer held
    assert h["roll"].tolist() == [False, False, False, True, False, False]


def test_funding_credited_to_the_settlement_hour():
    idx = pd.date_range("2026-03-02 01:00", periods=24, freq="h", tz="UTC")
    ev = pd.DataFrame({"time": pd.to_datetime(["2026-03-02 08:00:00.003", "2026-03-02 16:00:00"], utc=True, format="ISO8601"),
                       "funding_rate": [1e-4, 2e-4]})
    f = stg._funding(ev, idx)
    assert f.loc[pd.Timestamp("2026-03-02 08:00", tz="UTC")] == 1e-4 and f.loc[pd.Timestamp("2026-03-02 16:00", tz="UTC")] == 2e-4
    assert f.sum() == pytest.approx(3e-4)


def test_weekly_due_is_monday_midnight():
    idx = pd.date_range("2026-03-01", periods=24 * 14, freq="h", tz="UTC")
    d = stg.weekly_due(idx, 0)
    assert d.sum() == 2 and all(t.weekday() == 0 and t.hour == 0 for t in idx[d.to_numpy()])
    assert np.all(np.diff(idx[d.to_numpy()]) == np.timedelta64(7, "D"))
