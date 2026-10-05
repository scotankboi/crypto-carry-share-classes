"""Deribit public API: the DVOL index, daily delivery (settlement) prices and historical option trades.

- get_volatility_index_data: DVOL candles [ts, open, high, low, close]; long ranges come back in pieces
  with a `continuation` timestamp (the next end_timestamp to request, going backwards)
- get_delivery_prices: the btc_usd index fixing at 08:00 UTC each day (a 30-minute average), which
  settles expiring futures and options; paged by offset
- get_last_trades_by_currency_and_time on history.deribit.com: every option trade with its price (in
  BTC), implied volatility (%), index price and mark price; at most 1,000 per call, paged forward
"""
import pandas as pd

from ..net import HttpClient

API = "https://www.deribit.com/api/v2/public"
HISTORY = "https://history.deribit.com/api/v2/public"


def _ms(t: pd.Timestamp) -> int:
    return int(t.timestamp() * 1000)


def dvol(c: HttpClient, currency: str, start: pd.Timestamp, end: pd.Timestamp, resolution: str = "3600") -> pd.DataFrame:
    rows, stop = [], _ms(end)
    while True:
        r = c.get_json(f"{API}/get_volatility_index_data", {"currency": currency, "start_timestamp": _ms(start),
                                                            "end_timestamp": stop, "resolution": resolution})["result"]
        rows += r["data"]
        cont = r.get("continuation")
        if not cont or cont <= _ms(start) or cont >= stop:
            break
        stop = cont
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"]).drop_duplicates("ts")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.as_unit("ns")
    return df.sort_values("ts").reset_index(drop=True)


def delivery_prices(c: HttpClient, index_name: str = "btc_usd") -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        r = c.get_json(f"{API}/get_delivery_prices", {"index_name": index_name, "offset": offset, "count": 1000})["result"]
        rows += r["data"]
        offset += len(r["data"])
        if not r["data"] or offset >= r["records_total"]:
            break
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.as_unit("ns")
    return df.rename(columns={"delivery_price": "price"}).sort_values("date").reset_index(drop=True)


def option_trades(c: HttpClient, currency: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows, cursor = [], _ms(start)
    while True:
        r = c.get_json(f"{HISTORY}/get_last_trades_by_currency_and_time",
                       {"currency": currency, "kind": "option", "start_timestamp": cursor, "end_timestamp": _ms(end),
                        "count": 1000, "sorting": "asc"})["result"]
        batch = r["trades"]
        rows += batch
        if not r.get("has_more") or not batch:
            break
        nxt = batch[-1]["timestamp"]
        if nxt <= cursor:                # a millisecond with more than 1,000 trades: step past it
            nxt = cursor + 1
        cursor = nxt
    if not rows:
        return pd.DataFrame(columns=["timestamp", "trade_id", "instrument_name", "price", "iv", "index_price", "mark_price",
                                     "amount", "direction"])
    df = pd.DataFrame(rows)[["timestamp", "trade_id", "instrument_name", "price", "iv", "index_price", "mark_price", "amount",
                             "direction"]].drop_duplicates("trade_id")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.as_unit("ns")
    return df.sort_values("timestamp").reset_index(drop=True)


def parse_instrument(name: str) -> tuple[pd.Timestamp, float, str]:
    """BTC-29MAR24-70000-C -> (expiry 2024-03-29 08:00 UTC, strike 70000, 'C')."""
    _, d, k, cp = name.split("-")
    return pd.Timestamp(pd.to_datetime(d, format="%d%b%y")).tz_localize("UTC") + pd.Timedelta(hours=8), float(k), cp
