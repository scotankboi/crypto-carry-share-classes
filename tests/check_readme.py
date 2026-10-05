"""Check every number in README.md and vol_overlay/README.md against the pipeline's outputs.

    python tests/check_readme.py

Two checks. (1) tests/readme_claims.py regenerates each number in the READMEs from the outputs, with
the words around it, and each must appear verbatim. (2) As a net for numbers added later without a
claim, every number in the prose is also matched against all outputs (below).

Each number in the prose and tables (outside code blocks, formulas and links) must match, at the
precision it is written, a value in data/processed/results.json, validation.json,
vol_overlay/results.json or config.yaml, either as written or as a percentage (x 100). Numbers that
come from elsewhere (cited sources, counts of tests, list numbering, calendar dates) are listed in
ALLOWED with the reason. A match on the absolute value is accepted, so the check catches stale and
mistyped numbers rather than proving each one is the right statistic; the README's wording carries
that. Exits 1 if any number is unmatched.
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"

# number as written -> why it need not be in the outputs
ALLOWED = {
    "16,871": "FTX's BTC claim price (config.yaml, cited)", "72": "FTX class 5A cumulative distribution (cited)",
    "78": "FTX class 5A cumulative distribution (cited)", "96": "FTX class 5A cumulative distribution (cited)",
    "120": "FTX convenience-class distribution (cited); funding axis cut in a figure", "50,000": "FTX convenience-class limit (cited)",
    "0.01": "funding interest term per 8 hours (Binance, Hyperliquid docs)", "11": "0.01% x 3 x 365 = 10.95%, cited docs",
    "81": "unit tests counted by pytest", "41": "mutants in tests/mutation_check.py", "28": "mutants in chapter 1",
    "13": "mutants in chapter 2; minimum segment weeks", "100m": "reference book size (config)", "6": "list numbering / months",
    "1999": "Carino reference year", "2002": "Lo reference year", "2003": "Bai-Perron reference year", "1998": "reference year",
    "76": "Black-76", "91": "KRW CD 91-day rate (name)", "95": "95% intervals", "04": "retrieval date", "40": "front-month filter, 20–40 days to expiry (covered_call.calibrate)", "22": "year range 2021–22", "05": "retrieval date",
    "100": "100% probabilities in a table; $100m book", "256": "SHA-256", "365": "ACT/365 day count", "58": "Lo (2002) journal volume", "18": "Bai-Perron journal volume", "3": "journal issue / count",
}
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"


def flatten(x, out: list) -> list:
    if isinstance(x, dict):
        for k, v in x.items():
            flatten(v, out)
            try:
                out.append(float(k))
            except ValueError:
                pass
    elif isinstance(x, (list, tuple)):
        for v in x:
            flatten(v, out)
    elif isinstance(x, bool):
        pass
    elif isinstance(x, (int, float)):
        out.append(float(x))
    elif isinstance(x, str):
        for m in re.findall(r"\d+(?:\.\d+)?", x):
            out.append(float(m))
    return out


def values() -> dict[str, list[float]]:
    """Candidate values by unit: a number followed by % must match an output x 100, by bp an output x
    1e4 (or one already in bp), anything else an output as stored or x 100 (percentage points)."""
    vals = []
    for p in (OUT / "results.json", OUT / "validation.json", OUT / "vol_overlay" / "results.json"):
        flatten(json.loads(p.read_text()), vals)
    flatten(yaml.safe_load((ROOT / "config.yaml").read_text()), vals)
    vals = [abs(v) for v in vals if v == v and abs(v) != float("inf")]       # NaN would break the sorted search
    return {"%": sorted({v * 100 for v in vals}), "bp": sorted({v * 1e4 for v in vals} | set(vals)),
            "": sorted(set(vals) | {v * 100 for v in vals})}


def prose(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)                # code blocks
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.S)              # display formulas
    text = re.sub(r"`[^`]*`", " ", text)                              # inline code and paths
    text = re.sub(r"https?://\S+", " ", text)                         # links
    text = re.sub(r"\]\([^)]*\)", "]", text)                          # markdown link targets and images
    text = re.sub(rf"\b\d{{1,2}} {MONTHS}( \d{{4}})?", " ", text)     # 26 July 2021
    text = re.sub(rf"\b{MONTHS} \d{{4}}", " ", text)                   # May 2025
    text = re.sub(r"\b(?:19|20)\d\d\b(?![.,]\d)(?!%)", " ", text)     # years
    text = re.sub(r"\b\d{1,2}:\d\d\b", " ", text)                     # clock times
    text = re.sub(r"^\s*\d+\.\s", " ", text, flags=re.M)              # list numbering
    text = re.sub(r"^#+ \d+\.", " ", text, flags=re.M)                # numbered headings
    text = re.sub(r"\b[A-Za-z]+\d+[A-Za-z0-9]*\b", " ", text)         # tokens like 5A, 3AC, BTCUSDT_210326
    return text


def check(path: Path, vals: dict) -> list[str]:
    bad = []
    for m in re.finditer(r"[−-]?\$?(\d[\d,]*(?:\.\d+)?)(m|bn)?\s?(%|bp)?", prose(path.read_text())):
        tok = m.group(1).rstrip(",.")
        if not tok or tok in ALLOWED or (tok + (m.group(2) or "")) in ALLOWED:
            continue
        num = float(tok.replace(",", ""))
        d = len(tok.split(".")[1]) if "." in tok else 0
        tol = 0.5 * 10 ** -d + 1e-9
        v = vals[m.group(3) or ""]
        if not any(abs(x - num) <= tol for x in v[_lo(v, num - tol):_lo(v, num + tol) + 1]):
            bad.append(f"{path.relative_to(ROOT)}: {m.group(0).strip()}")
    return bad


def _lo(vals, x):
    import bisect
    return bisect.bisect_left(vals, x)


def unclaimed(text: str, found: list[str]) -> list[str]:
    """Numbers left in the prose once every claimed text is blanked out (and the ALLOWED ones)."""
    for t in found:
        i = text.find(t)
        while i >= 0:
            text = text[:i] + " " * len(t) + text[i + len(t):]
            i = text.find(t)
    toks = [m.group(1).rstrip(",.") for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)", prose(text))]
    cfg = flatten(yaml.safe_load((ROOT / "config.yaml").read_text()), [])
    cfg = {round(abs(x) * k, 6) for x in cfg for k in (1, 100)}
    ok = lambda t: (t in ALLOWED or round(float(t.replace(",", "")), 6) in cfg     # an assumption from config.yaml
                    or (t.isdigit() and int(t) <= 12))                             # small counts, lags, list items
    return [t for t in toks if t and not ok(t)]


def check_claims() -> list[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from readme_claims import claims
    r = json.loads((OUT / "results.json").read_text())
    v = json.loads((OUT / "vol_overlay" / "results.json").read_text())
    val = json.loads((OUT / "validation.json").read_text())
    text = {f: (ROOT / f).read_text() for f in ("README.md", "vol_overlay/README.md")}
    cl = claims(r, v, val)
    out = [f"{f}: expected {t!r}" for f, t in cl if t not in text[f]]
    for f in text:
        left = unclaimed(text[f], [t for g, t in cl if g == f])
        out += [f"{f}: number {t!r} is not covered by a claim" for t in left]
    return out


def main() -> int:
    missing = check_claims()
    for b in missing:
        print("CLAIM NOT FOUND", b)
    vals = values()
    bad = check(ROOT / "README.md", vals) + check(ROOT / "vol_overlay" / "README.md", vals)
    for b in bad:
        print("UNMATCHED", b)
    print(f"{len(missing)} claims not found, {len(bad)} numbers with no matching output")
    return 1 if bad or missing else 0


if __name__ == "__main__":
    sys.exit(main())
