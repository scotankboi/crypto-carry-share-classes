"""Binance public data archive (data.binance.vision): monthly zip files, SHA-256 checked.

Paths used here:
    spot/monthly/klines/BTCUSDT/<interval>/                     spot klines
    futures/um/monthly/klines/<symbol>/<interval>/              USDT-margined perpetual and quarterlies
    futures/um/monthly/fundingRate/BTCUSDT/                     funding settlements

Kline files from 2025 on carry microsecond timestamps in the spot archive; some futures files carry a
header row. Months before a contract was listed return 404 and are skipped.
"""
import hashlib
import io
import logging
import zipfile

import numpy as np
import pandas as pd
import requests

from ..net import HttpClient

log = logging.getLogger(__name__)
BASE = "https://data.binance.vision/data"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume"]


def _months(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [str(p) for p in pd.period_range(start.tz_convert(None) if start.tzinfo else start,
                                            end.tz_convert(None) if end.tzinfo else end, freq="M")]


def _fetch_zip(c: HttpClient, url: str) -> bytes | None:
    try:
        content = c.get(url).content
    except (requests.HTTPError, RuntimeError) as exc:
        if "404" in str(exc):
            return None
        raise
    checksum = c.get_text(url + ".CHECKSUM").split()[0]
    if hashlib.sha256(content).hexdigest() != checksum:
        raise ValueError(f"{url} failed its SHA-256 checksum")
    return content


def _read_csv(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = pd.read_csv(z.open(z.namelist()[0]), header=None)
    if not str(raw.iloc[0, 0]).lstrip("-").isdigit():       # header row
        raw = raw.iloc[1:].reset_index(drop=True)
    return raw


def _ts(x: pd.Series) -> pd.Series:
    t = pd.to_numeric(x)
    unit = "us" if t.max() > 10**14 else "ms"
    return pd.to_datetime(t, unit=unit, utc=True).dt.as_unit("ns")


def _kline_frame(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"open_time": _ts(raw[0]), "open": raw[1], "high": raw[2], "low": raw[3], "close": raw[4],
                         "volume": raw[5]})


def klines(c: HttpClient, market: str, symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """market: 'spot' or 'um'. A recent month whose monthly file is not published yet is read from daily files."""
    root = f"{BASE}/spot" if market == "spot" else f"{BASE}/futures/um"
    parts = []
    for m in _months(start, end):
        content = _fetch_zip(c, f"{root}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{m}.zip")
        if content is not None:
            parts.append(_kline_frame(_read_csv(content)))
            continue
        month = pd.Period(m, freq="M")
        if month.end_time < pd.Timestamp.now() - pd.Timedelta(days=45):
            continue                     # an old month without a monthly file: the contract was not trading
        last = min(month.end_time.normalize(), (end.tz_convert(None) if end.tzinfo else end).normalize())
        days = pd.date_range(month.start_time, last, freq="D")
        got = 0
        for d in days:
            dc = _fetch_zip(c, f"{root}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d:%Y-%m-%d}.zip")
            if dc is not None:
                parts.append(_kline_frame(_read_csv(dc)))
                got += 1
        log.info("%s %s %s: monthly file missing, %d of %d daily files", market, symbol, m, got, len(days))
    if not parts:
        return pd.DataFrame({k: pd.Series(dtype="datetime64[ns, UTC]" if k == "open_time" else float) for k in KLINE_COLS})
    df = pd.concat(parts, ignore_index=True)
    for k in KLINE_COLS[1:]:
        df[k] = pd.to_numeric(df[k], errors="coerce").astype(float)
    return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def funding(c: HttpClient, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Monthly archive files; a month not yet archived is read from the REST endpoint (1000 per call)."""
    parts = []
    for m in _months(start, end):
        content = _fetch_zip(c, f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{m}.zip")
        if content is None:
            month = pd.Period(m, freq="M")
            r = c.get_json("https://fapi.binance.com/fapi/v1/fundingRate",
                           {"symbol": symbol, "startTime": int(month.start_time.tz_localize("UTC").timestamp() * 1000),
                            "endTime": int(month.end_time.tz_localize("UTC").timestamp() * 1000), "limit": 1000})
            t = pd.to_datetime([x["fundingTime"] for x in r], unit="ms", utc=True).as_unit("ns")
            parts.append(pd.DataFrame({"time": t, "interval_hours": np.nan, "funding_rate": [float(x["fundingRate"]) for x in r]}))
            log.info("funding %s %s: monthly file missing, %d REST records", symbol, m, len(r))
            continue
        raw = _read_csv(content)
        parts.append(pd.DataFrame({"time": _ts(raw[0]), "interval_hours": pd.to_numeric(raw[1]),
                                   "funding_rate": pd.to_numeric(raw[2])}))
    df = pd.concat(parts, ignore_index=True)
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def quarterly_symbols(prefix: str, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[str, pd.Timestamp]]:
    """Quarterly contracts expiring on the last Friday of Mar/Jun/Sep/Dec at 08:00 UTC, from the first one
    alive at `start` to the first expiring after `end`."""
    out = []
    for q in pd.period_range(start.tz_convert(None).to_period("Q"), (end.tz_convert(None) + pd.Timedelta(days=200)).to_period("Q"), freq="Q"):
        last_day = q.end_time.normalize()
        expiry = last_day - pd.Timedelta(days=(last_day.weekday() - 4) % 7)
        out.append((f"{prefix}{expiry:%y%m%d}", (expiry + pd.Timedelta(hours=8)).tz_localize("UTC")))
    return [(s, e) for s, e in out if e > start]
