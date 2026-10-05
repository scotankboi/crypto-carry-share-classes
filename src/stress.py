"""The 10 October 2025 liquidations, minute by minute, for the master book.

From one-minute bars (Binance spot and perpetual, Bybit perpetual) and the book as it stood at the
last hour before the crash:
  * the hedged book's mark-to-market path: the short legs mirror spot, so only the perp-spot basis
    moves the NAV; the worst minute shows how far the hedge slipped;
  * margin: the lowest margin ratio on each venue at the minute's high (the short loses on spikes);
  * auto-deleveraging (ADL): when bankrupt longs cannot be closed against the order book, venues close
    profitable shorts against them. If the short on one venue is closed at minute t and re-established
    k minutes later, the book is long and unhedged in between; relative to staying hedged it gains
    n (F_t+k - F_t). The ADL minute is unknown, so every minute of the cascade (from the first minute
    5% below the opening price to the low) is tried, and the range of outcomes is reported.
"""
import pandas as pd


def _bars(k: pd.DataFrame) -> pd.DataFrame:
    return k.set_index("open_time")[["open", "high", "low", "close"]]


def oct10(spot_1m: pd.DataFrame, perps_1m: dict, state: dict, start: pd.Timestamp, end: pd.Timestamp,
          readd_minutes: list[int], maintenance: dict) -> dict:
    """state: {"nav", "Q", "n": {v: contracts}, "E": {v: equity}, "S0", "F0": {v: price}} at `start`."""
    s = _bars(spot_1m).loc[start:end]
    out = {"window": [str(start), str(end)], "spot_open": float(s["open"].iloc[0]), "spot_low": float(s["low"].min()),
           "spot_low_time": str(s["low"].idxmin()), "spot_close": float(s["close"].iloc[-1]),
           "spot_drawdown": float(s["low"].min() / s["open"].iloc[0] - 1), "venues": {}}
    nav0 = state["nav"]
    mtm = pd.Series(0.0, index=s.index)
    for v, k in perps_1m.items():
        f = _bars(k).loc[start:end].reindex(s.index).ffill()
        n, E0, F0 = state["n"][v], state["E"][v], state["F0"][v]
        basis = f["close"] / s["close"] - 1
        mtm += n * ((s["close"] - state["S0"]) - (f["close"] - F0))
        eq_hi = E0 - n * (f["high"] - F0)
        ratio = eq_hi / (n * f["high"])
        low_t = f["low"].idxmin()
        F_low = float(f["low"].min())
        cascade = f.loc[s.index[s["low"] <= s["open"].iloc[0] * 0.95].min():low_t]
        adl = {}
        for m in readd_minutes:
            later = f["close"].reindex(cascade.index + pd.Timedelta(minutes=m)).to_numpy()
            rel = n * (later - cascade["close"].to_numpy()) / nav0
            adl[str(m)] = {"adl_minutes_tried": int(len(cascade)), "worst_share_nav": float(rel.min()),
                           "best_share_nav": float(rel.max()), "median_share_nav": float(pd.Series(rel).median())}
        out["venues"][v] = {"perp_low": F_low, "perp_low_time": str(low_t), "basis_min_bp": float(basis.min() * 1e4),
                            "basis_max_bp": float(basis.max() * 1e4), "min_margin_ratio": float(ratio.min()),
                            "maintenance": maintenance[v], "notional_share_nav": float(n * F0 / nav0), "adl": adl}
    out["book_mtm_worst_share_nav"] = float(mtm.min() / nav0)
    out["book_mtm_best_share_nav"] = float(mtm.max() / nav0)
    out["book_mtm_end_share_nav"] = float(mtm.iloc[-1] / nav0)
    return out
