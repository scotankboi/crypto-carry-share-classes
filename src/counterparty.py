"""Counterparty risk: what the book keeps at each venue, the expected loss, and why the loss depends on
the share class's currency.

Exposure. Spot BTC sits with a custodian (off-exchange settlement), so what is at risk at venue v is
its perp margin equity E_v, a share s_v = E_v / NAV of the master (about w_v / (L + 1) at target,
more after the short has gained).

Expected loss per year:  EL = sum_v PD_v * LGD * s_v, on scenario grids for PD and LGD. The loss from a
single failure is LGD * s_v, reported at the mean and at the peak exposure.

Recovery depends on the class currency. In the FTX bankruptcy, customer claims were fixed in USD at
petition-date prices (BTC at $16,871) and repaid in cash, in instalments. Non-US ("Dotcom") customers,
class 5A, received cumulative distributions of 72% of the allowed claim on 30 May 2025, 78% on
30 Sep 2025 and 96% on 31 Mar 2026 (sources in config.yaml). A claim of E USD lost on the petition date
P is repaid as instalments p_i E on dates D_i (p_i = increase in the cumulative share), and each class
measures each instalment in its own unit on the date it is paid:

    nominal USD          sum_i p_i                          (cents per dollar of claim)
    USD / USDT classes   sum_i p_i M_P / M_Di               M = the USD class index (before fees): each
                                                            instalment buys back fewer master units than
                                                            the claim was worth on the petition date
    BTC class            sum_i p_i S_P / S_Di               coins recovered per coin lost (S = BTC-USD)

Whatever is still unpaid at the last distribution is counted as not recovered.
"""
import numpy as np
import pandas as pd


def exposures(ledger: pd.DataFrame, legs: list[str], hour: int) -> pd.DataFrame:
    d = ledger[ledger.index.hour == hour]
    return pd.DataFrame({v: d[f"E_{v}"] / d["nav"] for v in legs})


def expected_loss(share: pd.DataFrame, pd_grid: list, lgd_grid: list) -> pd.DataFrame:
    mean_share = share.mean()
    rows = [{"pd_annual": p, "lgd": g, "expected_loss_annual": float(p * g * mean_share.sum()),
             "single_default_loss_mean_exposure": float(g * mean_share.max()),
             "single_default_loss_peak_exposure": float(g * share.max(axis=0).max())} for p in pd_grid for g in lgd_grid]
    return pd.DataFrame(rows)


def ftx_recovery(cfg_ftx: dict, btc_usd: pd.Series, master_usd: pd.Series) -> dict:
    """Recovery of a USD claim frozen on the petition date and paid in instalments, with each instalment
    valued in each class's unit on its payment date (module docstring)."""
    P = pd.Timestamp(cfg_ftx["petition_date"])
    S_P = float(cfg_ftx["btc_petition_price"])
    M_P = float(master_usd.asof(P))
    rows, prev = [], 0.0
    for d in cfg_ftx["distributions"]:
        D, cum = pd.Timestamp(d["date"]), float(d["cumulative"])
        if cum < prev:
            raise ValueError("FTX distributions must be cumulative and non-decreasing")
        paid, prev = cum - prev, cum
        M_D, S_D = float(master_usd.asof(D)), float(btc_usd.asof(D))
        rows.append({"date": str(D.date()), "cumulative": cum, "paid": paid, "years_after_petition": (D - P).days / 365.25,
                     "btc_usd": S_D, "master_growth_since_petition": M_D / M_P,
                     "usd_vs_master": paid * M_P / M_D, "btc": paid * S_P / S_D})
    return {"petition_date": str(P.date()), "claim_class": cfg_ftx["claim_class"], "btc_petition": S_P,
            "schedule": rows, "first_distribution": rows[0]["date"], "last_distribution": rows[-1]["date"],
            "years_to_first": rows[0]["years_after_petition"], "years_to_last": rows[-1]["years_after_petition"],
            "usd_nominal": prev, "unpaid": 1 - prev,
            "usd_vs_master": float(sum(r["usd_vs_master"] for r in rows)),
            "btc": float(sum(r["btc"] for r in rows))}


def default_replay(share_on_date: pd.Series, recovery: dict, btc_hedge_margin: float, hedge_venue: str) -> pd.DataFrame:
    """Loss to each class (share of its NAV) if one venue had failed on the petition date: written to zero
    at once, and net of the eventual recovery measured in the class's currency. The BTC class invests
    (1 - m) of its NAV in the master and keeps m as margin for its long hedge on `hedge_venue`, so its
    exposure to that venue is larger."""
    rows = []
    for v, s in share_on_date.items():
        btc_exposure = (1 - btc_hedge_margin) * s + (btc_hedge_margin if v == hedge_venue else 0.0)
        for cls, exp, mult in (("USD / USDT", s, recovery["usd_vs_master"]), ("BTC hedged", btc_exposure, recovery["btc"])):
            rows.append({"venue": v, "class": cls, "exposure_share": float(exp), "loss_on_default": float(exp),
                         "recovery_multiple": mult, "net_loss_after_recovery": float(exp * max(0.0, 1 - mult))})
    return pd.DataFrame(rows)
