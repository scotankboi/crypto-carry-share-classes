import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config()


def hours(n, start="2026-03-02 00:00"):
    return pd.date_range(start, periods=n, freq="h", tz="UTC")


def leg_frame(S, legs: dict, start="2026-03-02 01:00"):
    """legs: {name: dict(F=..., f=..., F_mtm=None, roll=None, H=None)} -> engine input."""
    S = np.asarray(S, float)
    idx = hours(len(S), start)
    df = pd.DataFrame({"S": S}, index=idx)
    for v, d in legs.items():
        F = np.asarray(d["F"], float)
        df[f"F_{v}"] = F
        df[f"F_mtm_{v}"] = np.asarray(d.get("F_mtm", F), float)
        df[f"f_{v}"] = d.get("f", 0.0)
        df[f"roll_{v}"] = d.get("roll", False)
        df[f"H_{v}"] = np.asarray(d.get("H", F), float)
    return df
