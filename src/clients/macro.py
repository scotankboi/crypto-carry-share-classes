"""Rates, FX, CME futures and stablecoin supply.

- FRED CSV download (no key): SOFR, DEXJPUS, DEXKOUS, KRW 3-month interbank (monthly)
- Bank of Japan time-series API (no key): uncollateralised overnight call rate (TONA), daily
- Yahoo Finance: CME bitcoin futures, continuous front month (BTC=F), daily settlement
- DefiLlama stablecoins API: circulating supply of USDe
"""
import io

import pandas as pd
import yfinance as yf

from ..net import HttpClient


def fred(c: HttpClient, series: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(c.get_text("https://fred.stlouisfed.org/graph/fredgraph.csv", {"id": series})))
    df = pd.DataFrame({"date": pd.to_datetime(raw.iloc[:, 0]).dt.as_unit("ns"),
                       "value": pd.to_numeric(raw.iloc[:, 1], errors="coerce")})
    return df.dropna().reset_index(drop=True)


def boj(c: HttpClient, db: str, code: str, start: str) -> pd.DataFrame:
    r = c.get_json("https://www.stat-search.boj.or.jp/api/v1/getDataCode",
                   {"format": "json", "lang": "en", "db": db, "code": code, "startDate": start.replace("-", "")[:6]})
    if r.get("STATUS") != 200:
        raise RuntimeError(f"BoJ API: {str(r)[:200]}")
    v = r["RESULTSET"][0]["VALUES"]
    df = pd.DataFrame({"date": pd.to_datetime([str(d) for d in v["SURVEY_DATES"]], format="%Y%m%d").as_unit("ns"),
                       "value": pd.to_numeric(v["VALUES"], errors="coerce")})
    return df.dropna().reset_index(drop=True)


def yahoo_daily(ticker: str, start: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(interval="1d", start=start, auto_adjust=False, actions=False)
    if df.empty:
        raise RuntimeError(f"Yahoo returned no data for {ticker}")
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    # Yahoo dates futures by the Chicago trading day; keep the calendar date
    df.index = pd.DatetimeIndex(df.index.tz_localize(None) if df.index.tz is not None else df.index).normalize().as_unit("ns")
    return df.rename_axis("date").reset_index()


def defillama_supply(c: HttpClient, asset_id: int) -> pd.DataFrame:
    r = c.get_json(f"https://stablecoins.llama.fi/stablecoin/{asset_id}")
    rows = [(pd.to_datetime(int(x["date"]), unit="s"), x.get("circulating", {}).get("peggedUSD")) for x in r["tokens"]]
    df = pd.DataFrame(rows, columns=["date", "supply_usd"]).dropna()
    df["date"] = df["date"].dt.as_unit("ns")
    return df.sort_values("date").reset_index(drop=True)
