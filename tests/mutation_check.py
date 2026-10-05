"""Deliberately break the code and confirm the test suite notices.

    python tests/mutation_check.py

Each mutant changes one line that a correct analysis depends on; the suite must fail for it.
Files are restored after every run. The script exits with status 1 if any mutant survives or cannot be
applied (its line no longer exists), so it can gate a CI run.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTANTS = [
    ("src/engine.py", 'fund = n[v] * arr[f"f_{v}"][i] * Fm[v]', 'fund = -n[v] * arr[f"f_{v}"][i] * Fm[v]', "funding sign flipped"),
    ("src/engine.py", 'comp["convergence"] += n[v] * ((prev["F"][v] - prev["S"]) - (Fm[v] - S))',
     'comp["convergence"] += n[v] * ((Fm[v] - S) - (prev["F"][v] - prev["S"]))', "convergence sign flipped"),
    ("src/engine.py", "E[v] = n[v] * F[v] * target", "E[v] = n[v] * F[v] * leverage", "margin set to L instead of 1/L"),
    ("src/engine.py", "c = n[v] * (Fm[v] * legs[v].roll + F[v] * legs[v].trade)", "c = 0.0", "roll costs ignored"),
    ("src/engine.py", "pending = i + lag", "pending = i", "emergency lag ignored"),
    ("src/engine.py", 'E[v] -= n[v] * (Fm[v] - prev["F"][v])', 'E[v] -= n[v] * (F[v] - prev["F"][v])',
     "expiring future marked at the new contract's price"),
    ("src/strategies.py", 'held = np.searchsorted(exp.to_numpy(), idx.to_numpy(), side="right")',
     'held = np.searchsorted(exp.to_numpy(), idx.to_numpy(), side="left")', "expiring contract still held at expiry"),
    ("src/strategies.py", 't = ev["time"].dt.floor("h")', 't = ev["time"].dt.ceil("h")', "funding credited an hour late"),
    ("src/share_classes.py", "mtm = N * (K - fwd) / (1 + ic[i] * days / ccy_days)",
     "mtm = N * (fwd - K) / (1 + ic[i] * days / ccy_days)", "forward value sign flipped"),
    ("src/share_classes.py", "K = X[i] * (1 + (ic[i] + basis) * days / ccy_days) / (1 + iu[i] * days / 360)",
     "K = X[i] * (1 + (ic[i] - basis) * days / ccy_days) / (1 + iu[i] * days / 360)", "cross-currency basis sign"),
    ("src/share_classes.py", "            A = W - C\n            h = (A if margin_in_btc else W) / S[i]",
     "            A = W\n            h = (A if margin_in_btc else W) / S[i]", "BTC hedge margin also invested"),
    ("src/share_classes.py", "                C *= S[i] / S[i - 1]", "                pass", "coin margin not marked to BTC"),
    ("src/share_classes.py", "    s.index = s.index + pd.Timedelta(days=1)", "    s.index = s.index + pd.Timedelta(days=0)",
     "USDT-USD close used before it is known"),
    ("src/share_classes.py", "            hwm = B\n", "", "high-water mark not reset after a fee"),
    ("src/share_classes.py", "    crystallise = np.r_[q[1:] != q[:-1], True]", "    crystallise = np.ones(len(idx), bool)",
     "performance fee crystallised daily"),
    ("src/carry.py", 'd["excluded"] = (d["days"] < 7) |', 'd["excluded"] = (d["days"] < 0) |', "CME expiry week kept"),
    ("src/carry.py", 'd["excluded"] = (d["days"] < 7) | d["roll_day"] |', 'd["excluded"] = (d["days"] < 7) |', "CME roll day kept"),
    ("src/carry.py", "bic = n * np.log(best[k][n] / n) + (2 * k + 1) * np.log(n)", "bic = n * np.log(best[k][n] / n)",
     "no penalty for extra breaks"),
    ("src/counterparty.py", "btc_exposure = (1 - btc_hedge_margin) * s + (btc_hedge_margin if v == hedge_venue else 0.0)",
     "btc_exposure = s", "BTC class hedge margin left out of venue exposure"),
    ("src/counterparty.py", '"usd_vs_master": paid * M_P / M_D', '"usd_vs_master": paid', "FTX instalments not revalued"),
    ("src/counterparty.py", '"btc": paid * S_P / S_D', '"btc": paid * S_P / float(btc_usd.iloc[-1])', "FTX coins valued at one date"),
    ("src/risk.py", '"sharpe": float(sr_m * eta),', '"sharpe": float(sr_m * np.sqrt(12)),', "Sharpe ignores autocorrelation"),
    ("src/risk.py", "var_ratio = q + 2 * sum((q - k) * autocorr(x, k) for k in range(1, q))", "var_ratio = q",
     "Lo eta without autocorrelations"),
    ("src/margin.py", "return ((1 - band) / leverage - maintenance) / (1 + maintenance)",
     "return (1 / leverage - maintenance) / (1 + maintenance)", "band edge ignored"),
    ("src/margin.py", 'out[f"p_annual_{k}"] = out.groupby("leverage")[f"p_{k}_raw"].cummax()',
     'out[f"p_annual_{k}"] = out[f"p_{k}_raw"]', "liquidation risk not monotone in the lag"),
    ("src/stress.py", 'rel = n * (later - cascade["close"].to_numpy()) / nav0',
     'rel = n * (cascade["close"].to_numpy() - later) / nav0', "ADL outcome sign flipped"),
    ("src/margin.py", "return ((1 - band) / leverage - maintenance) / (1 + maintenance)",
     "return ((1 - band) / leverage - maintenance) / (1 - maintenance)", "liquidation threshold algebra"),
    ("src/config.py", "abs(sum(w.values()) - 1) > 1e-9", "abs(sum(w.values()) - 1) > 10", "venue weights not checked"),
    ("src/vol_overlay/options.py", "return call_usd(F, K, T, sigma) - F + K", "return call_usd(F, K, T, sigma) + F - K",
     "put-call parity sign"),
    ("src/vol_overlay/options.py", "return F * np.exp(-sigma * np.sqrt(T) * norm.ppf(delta) + 0.5 * sigma ** 2 * T)",
     "return F * np.exp(sigma * np.sqrt(T) * norm.ppf(delta) + 0.5 * sigma ** 2 * T)", "strike-from-delta sign"),
    ("src/vol_overlay/options.py", "return call_usd(F, K, T, sigma) / F", "return call_usd(F, K, T, sigma) / F * 1.004",
     "BTC price converted at the index instead of the forward"),
    ("src/vol_overlay/covered_call.py", "        price = float(bs.call_btc(F0, K, T, sig))", "        price = float(bs.call_btc(S0, K, T, sig))",
     "call priced off the index"),
    ("src/vol_overlay/covered_call.py", 'out["ratio"] = np.where(use_parity, out["parity_ratio"], out["iv_ratio"])',
     'out["ratio"] = np.where(use_parity, 1 / out["parity_ratio"], out["iv_ratio"])', "parity forward inverted"),
    ("src/vol_overlay/vrp.py", "return np.sqrt(365 / days * fwd)", "return np.sqrt(252 / days * fwd)",
     "realised volatility on a 252-day year"),
    ("src/vol_overlay/vrp.py", "fwd = (r ** 2)[::-1].rolling(days, min_periods=days).sum()[::-1].shift(-1)",
     "fwd = (r ** 2)[::-1].rolling(days, min_periods=days).sum()[::-1]", "realised window includes today's return"),
    ("src/vol_overlay/covered_call.py", "payoff = max(ST - K, 0.0) / ST", "payoff = max(ST - K, 0.0) / S0",
     "call payout converted at the entry price"),
    ("src/vol_overlay/covered_call.py", 'best = ks.sort_values(["miss", "btc_volume"], ascending=[True, False]).iloc[0]',
     'best = ks.sort_values(["miss", "btc_volume"], ascending=[False, False]).iloc[0]', "strike furthest from the target delta"),
    ("src/vol_overlay/covered_call.py", 't["below_mark"] = (t["mark_price"] - t["price"]) / vega_pt',
     't["below_mark"] = (t["price"] - t["mark_price"]) / vega_pt', "spread measured with the wrong sign"),
    ("src/vol_overlay/covered_call.py", "ret_btc=price - haircut - fee - payoff - sfee", "ret_btc=price + haircut - fee - payoff - sfee",
     "spread added to the premium"),
    ("src/vol_overlay/short_vol.py", "hedge += h * (float(path.iloc[i + 1]) - S) - h * S * f",
     "hedge -= h * (float(path.iloc[i + 1]) - S) - h * S * f", "delta hedge sign flipped"),
    ("src/vol_overlay/short_vol.py", "payoff = abs(ST - K)", "payoff = abs(S0 - K)", "straddle settled at the entry price"),
]


def exit_status(results: list[str]) -> int:
    """0 only if every mutant was applied and caught."""
    return 0 if results and all(r == "caught" for r in results) else 1


def main() -> int:
    results = []
    for rel, old, new, name in MUTANTS:
        path = ROOT / rel
        src = path.read_text()
        if old not in src:
            print(f"SKIPPED   {name} (line not found)")
            results.append("skipped")
            continue
        path.write_text(src.replace(old, new, 1))
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"], cwd=ROOT,
                               capture_output=True, text=True)
        finally:
            path.write_text(src)
        results.append("caught" if r.returncode != 0 else "survived")
        print(("caught    " if r.returncode != 0 else "SURVIVED  ") + name)
    print(f"{results.count('caught')}/{len(MUTANTS)} mutants caught")
    return exit_status(results)


if __name__ == "__main__":
    sys.exit(main())
