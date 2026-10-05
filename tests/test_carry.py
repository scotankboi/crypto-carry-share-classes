"""The carry measures: CME expiry calendar and basis, calendar carry, multiple-break detection."""
import numpy as np
import pandas as pd
import pytest

from src import carry


def test_last_friday():
    assert carry.last_friday(2024, 3) == pd.Timestamp("2024-03-29")
    assert carry.last_friday(2026, 9) == pd.Timestamp("2026-09-25")


def test_cme_basis_annualises_to_the_front_expiry_and_excludes_rolls():
    dates = pd.to_datetime(["2026-09-01", "2026-09-21", "2026-09-28", "2026-09-29", "2026-10-30", "2026-11-02"])
    cme = pd.DataFrame({"date": dates, "close": [101.0, 100.5, 101.0, 101.0, 100.0, 101.0]})
    settle = (dates + pd.Timedelta(hours=15)).tz_localize("America/Chicago").tz_convert("UTC")
    btc = pd.DataFrame({"open_time": settle - pd.Timedelta(hours=1), "close": 100.0})
    d = carry.cme_basis(cme, btc).set_index("date")
    assert d.loc["2026-09-01", "days"] == 24 and d.loc["2026-09-01", "ann_basis"] == pytest.approx(0.01 * 365 / 24)
    assert d.loc["2026-09-21", "excluded"]                                  # 4 days to the 25 Sep expiry
    assert d.loc["2026-09-28", "days"] == (pd.Timestamp("2026-10-30") - pd.Timestamp("2026-09-28")).days
    # the first trading day after each expiry is the roll day: Monday 28 Sep after 25 Sep, Monday 2 Nov after 30 Oct
    assert d.loc["2026-09-28", "roll_day"] and d.loc["2026-09-28", "excluded"]
    assert not d.loc["2026-09-29", "roll_day"] and not d.loc["2026-09-29", "excluded"]
    assert d.loc["2026-11-02", "roll_day"] and d.loc["2026-10-30", "excluded"] and not d.loc["2026-10-30", "roll_day"]
    assert d["roll_day"].sum() == 2


def test_calendar_carry_is_funding_minus_locked_basis():
    idx = pd.date_range("2026-01-01 01:00", periods=24 * 60, freq="h", tz="UTC")
    q = pd.DataFrame({"symbol": "Q", "days_to_expiry": np.linspace(60, 0.04, len(idx)), "S": 100.0,
                      "F_binance_q": np.linspace(102.0, 100.0, len(idx))}, index=idx)
    f = pd.Series(0.0, index=idx)
    f.iloc[::8] = 0.0001
    out = carry.calendar_carry(q, f).iloc[0]
    assert out["basis_locked"] == pytest.approx(0.02)
    assert out["perp_funding"] == pytest.approx(0.0001 * len(idx[::8]))
    assert out["calendar_carry_ann"] == pytest.approx((out["perp_funding"] - 0.02) / (out["days"] / 365))


def test_bai_perron_finds_planted_breaks():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2021-01-04", periods=150, freq="W-MON")
    mean = np.r_[np.full(50, 0.4), np.full(60, 0.05), np.full(40, 0.2)]
    out = carry.bai_perron(pd.Series(mean + rng.normal(0, 0.03, 150), index=idx), 4, 13)
    assert out["n_breaks"] == 2
    found = [pd.Timestamp(d) for d in out["break_dates"]]
    assert abs((found[0] - idx[50]).days) <= 14 and abs((found[1] - idx[110]).days) <= 14
    assert [s["mean"] for s in out["segments"]] == pytest.approx([0.4, 0.05, 0.2], abs=0.015)
