"""Load config.yaml and reject anything the code does not use.

The schema below is the contract: every key is required, unknown keys raise, and types are checked.
A typo in an assumption fails loudly instead of being silently ignored.
"""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
NUM = (int, float)
DATE = "date"          # string parseable as a date
OPT = object()         # marker: value may be null

VENUE_BN = {"perp": str, "spot": str, "quarterly_prefix": str, "maintenance_margin": NUM, "perp_taker": NUM,
            "delivery_fee": NUM}
SCHEMA = {
    "sample": {"start_utc": DATE, "end_utc": DATE, "margin_history_start": DATE},
    "venues": {"binance": VENUE_BN, "bybit": {"perp": str, "maintenance_margin": NUM, "perp_taker": NUM},
               "hyperliquid": {"perp": str}},
    "costs": {"spot_taker": NUM, "spot_half_spread_bps": NUM, "perp_half_spread_bps": NUM,
              "regular_tier": {"spot_taker": NUM, "perp_taker": NUM}},
    "strategy": {"capital_usdt": NUM, "weights": ("mapping", NUM), "leverage": NUM, "rebalance_weekday": int,
                 "rebalance_band": NUM, "emergency_lag_hours": int},
    "master": {"candidates": ("list_of", str), "rule": str},
    "margin": {"leverage_grid": ("list_of", NUM), "topup_lag_hours": ("list_of", int), "reference_probability_annual": NUM,
               "evt_threshold_quantile": NUM},
    "share_classes": {"valuation_hour_utc": int, "management_fee": NUM, "performance_fee": NUM, "hedge_roll": str,
                      "cross_currency_basis_bps": ("mapping", NUM), "basis_sensitivity_bps": ("mapping", NUM),
                      "btc_hedge_margin": NUM, "btc_hedge_rebalance": str},
    "rates": {"fred_sofr": str, "fred_jpy_fx": str, "fred_krw_fx": str, "fred_krw_rate": str, "boj_db": str, "boj_tona": str},
    "market_data": {"usdt_usd": str, "cme_ticker": str, "cme_margin_rate": ("list_of", NUM), "usde_defillama_id": int},
    "counterparty": {"pd_annual": ("list_of", NUM), "lgd_usd": ("list_of", NUM), "spot_at_custodian": bool,
                     "ftx": {"petition_date": DATE, "btc_petition_price": NUM, "claim_class": str,
                             "distributions": ("list", {"date": DATE, "cumulative": NUM})}},
    "events": ("list", {"date": DATE, "label": str}),
    "breaks": {"max_breaks": int, "min_segment_weeks": int},
    "stress": {"oct10_start": DATE, "oct10_end": DATE, "readd_minutes": ("list_of", int)},
    "vol_overlay": {"first_expiry": DATE, "last_expiry": DATE, "roll_hour_utc": int, "trade_window_minutes": int,
                    "call_deltas": ("list_of", NUM), "max_delta_miss": NUM, "option_fee": NUM, "option_fee_cap": NUM,
                    "settlement_fee": NUM, "half_spread_multiplier": NUM, "half_spread_sensitivity": NUM,
                    "hedge_hour_utc": int, "rv_days": int, "stress_months": ("list_of", str)},
}


def _check(value, spec, where: str) -> None:
    if isinstance(spec, tuple) and spec and spec[0] is OPT:
        if value is None:
            return
        return _check(value, spec[1], where)
    if spec == DATE:
        if not isinstance(value, str):
            raise ValueError(f"{where}={value!r} must be a quoted date string")
        try:
            pd.Timestamp(value)
        except ValueError as exc:
            raise ValueError(f"{where}={value!r} is not a date") from exc
        return
    if isinstance(spec, tuple) and spec[0] == "mapping":
        if not isinstance(value, dict) or not value:
            raise ValueError(f"{where} must be a non-empty mapping")
        for k, v in value.items():
            _check(v, spec[1], f"{where}.{k}")
        return
    if isinstance(spec, tuple) and spec[0] == "list":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{where} must be a non-empty list")
        for i, v in enumerate(value):
            _check(v, spec[1], f"{where}[{i}]")
        return
    if isinstance(spec, tuple) and spec[0] == "list_of":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{where} must be a non-empty list")
        for i, v in enumerate(value):
            _check(v, spec[1], f"{where}[{i}]")
        return
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            raise ValueError(f"{where} must be a mapping")
        unknown, missing = set(value) - set(spec), set(spec) - set(value)
        if unknown or missing:
            raise ValueError(f"{where}: unknown={sorted(unknown)} missing={sorted(missing)}")
        for k, s in spec.items():
            _check(value[k], s, f"{where}.{k}")
        return
    if spec is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{where}={value!r} must be true or false")
        return
    # plain type or tuple of types; bool is never a number here
    if isinstance(value, bool) or not isinstance(value, spec):
        raise ValueError(f"{where}={value!r} has the wrong type")


def validate(cfg: dict) -> dict:
    _check(cfg, SCHEMA, "config")
    w = cfg["strategy"]["weights"]
    if set(w) - {"binance", "bybit"} or abs(sum(w.values()) - 1) > 1e-9 or min(w.values()) < 0:
        raise ValueError("strategy.weights must be non-negative weights on binance / bybit summing to 1")
    if not cfg["strategy"]["leverage"] >= 1:
        raise ValueError("strategy.leverage must be >= 1")
    for v in ("binance", "bybit"):
        if not 0 < cfg["venues"][v]["maintenance_margin"] < 1 / cfg["strategy"]["leverage"]:
            raise ValueError(f"venues.{v}.maintenance_margin must be below the initial margin 1/L")
    sc = cfg["share_classes"]
    if not (0 <= sc["management_fee"] < 0.1 and 0 <= sc["performance_fee"] < 1 and 0 < sc["btc_hedge_margin"] < 1):
        raise ValueError("share_classes fees and btc_hedge_margin must be fractions")
    if sc["hedge_roll"] != "monthly" or sc["btc_hedge_rebalance"] != "daily":
        raise ValueError("only monthly FX rolls and daily BTC hedge rebalancing are implemented")
    if set(cfg["master"]["candidates"]) - {"perp_carry", "quarterly_carry"}:
        raise ValueError("master.candidates must be perp_carry and/or quarterly_carry")
    if pd.Timestamp(cfg["sample"]["start_utc"]) >= pd.Timestamp(cfg["sample"]["end_utc"]):
        raise ValueError("sample.start_utc must precede end_utc")
    if not 0 < cfg["margin"]["reference_probability_annual"] < 1 or not 0.5 < cfg["margin"]["evt_threshold_quantile"] < 1:
        raise ValueError("margin.reference_probability_annual and evt_threshold_quantile must be in (0, 1) / (0.5, 1)")
    ftx = cfg["counterparty"]["ftx"]["distributions"]
    cum = [d["cumulative"] for d in ftx]
    dates = [pd.Timestamp(d["date"]) for d in ftx]
    if any(b < a for a, b in zip(cum, cum[1:])) or not 0 < cum[-1] <= 2 or dates != sorted(dates):
        raise ValueError("counterparty.ftx.distributions must be dated in order with non-decreasing cumulative shares")
    if cfg["strategy"]["emergency_lag_hours"] not in cfg["margin"]["topup_lag_hours"]:
        raise ValueError("margin.topup_lag_hours must include strategy.emergency_lag_hours")
    return cfg


def load_config(path: Path | str = ROOT / "config.yaml") -> dict:
    with open(path) as f:
        return validate(yaml.safe_load(f))
