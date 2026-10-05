"""Download every raw series into data/raw/*.parquet and record it in data/raw/manifest.json.

    python -m src.collect

The Binance archive files are immutable monthly snapshots, so the core series re-download identically.
"""
import json
import logging

import pandas as pd

from .clients import binance_vision as bv
from .clients import deribit, macro, venues
from .config import ROOT, load_config
from .net import HttpClient

log = logging.getLogger("collect")
RAW = ROOT / "data" / "raw"


def _have(name: str, refresh: bool) -> bool:
    if not refresh and (RAW / f"{name}.parquet").exists():
        log.info("%-28s already collected (use --refresh to fetch again)", name)
        return True
    return False


def _save(name: str, df: pd.DataFrame, time_col: str, source: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_parquet(RAW / f"{name}.parquet", index=False)
    path = RAW / "manifest.json"
    man = json.loads(path.read_text()) if path.exists() else {}
    man[name] = {"source": source, "rows": int(len(df)), "first": str(df[time_col].min()), "last": str(df[time_col].max()),
                 "fetched_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
    path.write_text(json.dumps(man, indent=2))
    log.info("%-28s %8d rows  %s -> %s", name, len(df), df[time_col].min(), df[time_col].max())


def collect(cfg: dict, refresh: bool = False) -> None:
    c = HttpClient(sleep_sec=0.12)
    s = cfg["sample"]
    start, end = pd.Timestamp(s["start_utc"], tz="UTC"), pd.Timestamp(s["end_utc"], tz="UTC")
    pre = start - pd.Timedelta(days=31)
    bn, by = cfg["venues"]["binance"], cfg["venues"]["bybit"]
    st, r = cfg["stress"], cfg["rates"]
    a, b = pd.Timestamp(st["oct10_start"], tz="UTC"), pd.Timestamp(st["oct10_end"], tz="UTC")

    def quarterlies():
        rows = []
        for sym, expiry in bv.quarterly_symbols(bn["quarterly_prefix"], pre, end):
            k = bv.klines(c, "um", sym, "1h", max(pre, expiry - pd.Timedelta(days=200)), min(end, expiry))
            if len(k):
                rows.append(k.assign(symbol=sym, expiry=expiry))
        return pd.concat(rows, ignore_index=True)

    def minutes(market, sym):
        k = bv.klines(c, market, sym, "1m", a, a)
        return k[(k["open_time"] >= a - pd.Timedelta(hours=6)) & (k["open_time"] < b + pd.Timedelta(hours=6))]

    vo = cfg["vol_overlay"]

    def roll_trades():
        """Deribit option trades within +/- the window of 08:00 UTC on each monthly expiry (last Friday)."""
        from .carry import last_friday
        parts = []
        for m in pd.period_range(vo["first_expiry"][:7], vo["last_expiry"][:7], freq="M"):
            t0 = (last_friday(m.year, m.month) + pd.Timedelta(hours=vo["roll_hour_utc"])).tz_localize("UTC")
            w = pd.Timedelta(minutes=vo["trade_window_minutes"])
            parts.append(deribit.option_trades(c, "BTC", t0 - w, t0 + w).assign(roll=t0))
        return pd.concat(parts, ignore_index=True)

    jobs = [
        ("spot_bn_1h", lambda: bv.klines(c, "spot", bn["spot"], "1h", pd.Timestamp(s["margin_history_start"], tz="UTC"), end),
         "open_time", "data.binance.vision spot klines"),
        ("perp_bn_1h", lambda: bv.klines(c, "um", bn["perp"], "1h", pre, end), "open_time", "data.binance.vision um klines"),
        ("funding_bn", lambda: bv.funding(c, bn["perp"], pre, end), "time", "data.binance.vision um fundingRate"),
        ("quarterly_bn_1h", quarterlies, "open_time", "data.binance.vision um klines (quarterlies)"),
        ("perp_bb_1h", lambda: venues.bybit_klines(c, by["perp"], "60", pre, end + pd.Timedelta(hours=1)), "open_time", "bybit v5 kline"),
        ("funding_bb", lambda: venues.bybit_funding(c, by["perp"], pre, end), "time", "bybit v5 funding history"),
        ("funding_hl", lambda: venues.hyperliquid_funding(c, cfg["venues"]["hyperliquid"]["perp"], pre, end), "time",
         "hyperliquid fundingHistory"),
        ("btcusd_cb_1h", lambda: venues.coinbase_candles(c, "BTC-USD", 3600, pre, end + pd.Timedelta(hours=1)), "open_time",
         "coinbase BTC-USD candles"),
        ("usdtusd_cb_1d", lambda: venues.coinbase_candles(c, "USDT-USD", 86400, pre, end + pd.Timedelta(days=1)), "open_time",
         "coinbase USDT-USD candles"),
        # one-minute bars around the 10 Oct 2025 liquidations
        ("spot_bn_1m_oct2025", lambda: minutes("spot", bn["spot"]), "open_time", "data.binance.vision 1m klines"),
        ("perp_bn_1m_oct2025", lambda: minutes("um", bn["perp"]), "open_time", "data.binance.vision 1m klines"),
        ("perp_bb_1m_oct2025", lambda: venues.bybit_klines(c, by["perp"], "1", a - pd.Timedelta(hours=6), b + pd.Timedelta(hours=6),
                                                           minutes=1), "open_time", "bybit v5 kline 1m"),
        ("sofr", lambda: macro.fred(c, r["fred_sofr"]), "date", f"FRED {r['fred_sofr']}"),
        ("usdjpy", lambda: macro.fred(c, r["fred_jpy_fx"]), "date", f"FRED {r['fred_jpy_fx']}"),
        ("usdkrw", lambda: macro.fred(c, r["fred_krw_fx"]), "date", f"FRED {r['fred_krw_fx']}"),
        ("krw_rate", lambda: macro.fred(c, r["fred_krw_rate"]), "date", f"FRED {r['fred_krw_rate']}"),
        ("tona", lambda: macro.boj(c, r["boj_db"], r["boj_tona"], str(pre.date())), "date", f"Bank of Japan {r['boj_db']}/{r['boj_tona']}"),
        ("cme_btc_1d", lambda: macro.yahoo_daily(cfg["market_data"]["cme_ticker"], str(pre.date())), "date",
         f"Yahoo {cfg['market_data']['cme_ticker']}"),
        ("usde_supply", lambda: macro.defillama_supply(c, cfg["market_data"]["usde_defillama_id"]), "date", "DefiLlama stablecoins"),
        ("deribit_dvol_1h", lambda: deribit.dvol(c, "BTC", pd.Timestamp(vo["first_expiry"], tz="UTC") - pd.Timedelta(days=3), end),
         "ts", "Deribit get_volatility_index_data (BTC, 1h)"),
        ("deribit_delivery", lambda: deribit.delivery_prices(c, "btc_usd"), "date", "Deribit get_delivery_prices (btc_usd)"),
        ("deribit_option_trades_rolls", roll_trades, "timestamp", "history.deribit.com option trades around monthly expiries"),
    ]
    for name, fetch, time_col, source in jobs:
        if not _have(name, refresh):
            _save(name, fetch(), time_col, source)


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="fetch every series again")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    collect(load_config(), refresh=args.refresh)


if __name__ == "__main__":
    main()
