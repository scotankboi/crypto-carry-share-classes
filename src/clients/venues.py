"""REST clients for venues without a bulk archive.

- Bybit v5: funding history (200 per call, page backwards with endTime) and linear klines (1000 per call,
  rows newest first: [start ms, open, high, low, close, volume, turnover]).
- Hyperliquid: fundingHistory (500 records per call from startTime; page with last time + 1).
- Coinbase Exchange: candles (300 per call, rows [time, low, high, open, close, volume]).
"""
import time

import pandas as pd

from ..net import HttpClient

BYBIT = "https://api.bybit.com/v5/market"
HL = "https://api.hyperliquid.xyz/info"
COINBASE = "https://api.exchange.coinbase.com"


def _ms(t: pd.Timestamp) -> int:
    return int(t.timestamp() * 1000)


def _bybit(c: HttpClient, path: str, params: dict, tries: int = 6) -> dict:
    """Bybit returns HTTP 200 with retCode 10016 ('svc error') under load: retry with backoff."""
    for k in range(tries):
        r = c.get_json(f"{BYBIT}/{path}", params)
        if r.get("retCode") == 0:
            return r
        if r.get("retCode") not in (10002, 10006, 10016):
            break
        time.sleep(2 ** k)
    raise RuntimeError(f"Bybit {path}: {str(r)[:200]}")


def bybit_funding(c: HttpClient, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows, cursor = [], _ms(end)
    while True:
        r = _bybit(c, "funding/history", {"category": "linear", "symbol": symbol, "endTime": cursor, "limit": 200})
        batch = r["result"]["list"]
        if not batch:
            break
        rows += batch
        oldest = int(batch[-1]["fundingRateTimestamp"])
        if oldest <= _ms(start) or oldest - 1 >= cursor:
            break
        cursor = oldest - 1
    df = pd.DataFrame({"time": pd.to_datetime(pd.to_numeric([x["fundingRateTimestamp"] for x in rows]), unit="ms", utc=True),
                       "funding_rate": pd.to_numeric([x["fundingRate"] for x in rows])})
    df["time"] = df["time"].dt.as_unit("ns")
    return df[(df["time"] >= start) & (df["time"] <= end)].drop_duplicates("time").sort_values("time").reset_index(drop=True)


def bybit_klines(c: HttpClient, symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp,
                 minutes: int = 60) -> pd.DataFrame:
    rows, cursor = [], start
    step = pd.Timedelta(minutes=minutes)
    while cursor < end:
        chunk_end = min(cursor + 1000 * step, end)
        r = _bybit(c, "kline", {"category": "linear", "symbol": symbol, "interval": interval, "limit": 1000,
                                "start": _ms(cursor), "end": _ms(chunk_end - step)})
        rows += r["result"]["list"]
        cursor = chunk_end
    df = pd.DataFrame([x[:6] for x in rows], columns=["open_time", "open", "high", "low", "close", "volume"])
    df["open_time"] = pd.to_datetime(pd.to_numeric(df["open_time"]), unit="ms", utc=True).dt.as_unit("ns")
    for k in ["open", "high", "low", "close", "volume"]:
        df[k] = pd.to_numeric(df[k]).astype(float)
    return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def hyperliquid_funding(c: HttpClient, coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows, cursor = [], _ms(start)
    while cursor < _ms(end):
        batch = c.post_json(HL, {"type": "fundingHistory", "coin": coin, "startTime": cursor})
        if not isinstance(batch, list):
            raise RuntimeError(f"Hyperliquid fundingHistory: {str(batch)[:200]}")
        if not batch:
            break
        rows += batch
        nxt = batch[-1]["time"] + 1
        if nxt <= cursor:
            raise RuntimeError("Hyperliquid fundingHistory: pagination stuck")
        cursor = nxt
    df = pd.DataFrame({"time": pd.to_datetime([x["time"] for x in rows], unit="ms", utc=True).floor("h"),
                       "funding_rate": pd.to_numeric([x["fundingRate"] for x in rows])})
    df["time"] = df["time"].dt.as_unit("ns")
    return df[df["time"] <= end].drop_duplicates("time").reset_index(drop=True)


def coinbase_candles(c: HttpClient, product: str, granularity: int, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows, cursor = [], start
    step = pd.Timedelta(seconds=granularity)
    while cursor < end:
        chunk_end = min(cursor + 300 * step, end)
        batch = c.get_json(f"{COINBASE}/products/{product}/candles", {"granularity": granularity, "start": cursor.isoformat(),
                                                                       "end": (chunk_end - step).isoformat()})
        if not isinstance(batch, list):
            raise RuntimeError(f"Coinbase {product}: {str(batch)[:200]}")
        rows += batch
        cursor = chunk_end
    df = pd.DataFrame(rows, columns=["time", "low", "high", "open", "close", "volume"])
    df["open_time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.as_unit("ns")
    df = df[["open_time", "open", "high", "low", "close", "volume"]].astype({k: float for k in ["open", "high", "low", "close", "volume"]})
    return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
