"""
fetch_daily_move.py
Bakes data for the Daily Move in Historical Distribution indicator.

For each of five assets, fetches the full daily price history, computes
every daily move, bins them into a histogram, and injects the binned
distribution plus summary stats into daily_move_distribution.html.
The page only renders — all math lives here.

Sources (all free, no registration):
  1. Yahoo ^GSPC    — S&P 500 daily closes since Dec 1927, % change
  2. LBMA gold PM   — gold fix USD/oz since 1968; trimmed to Aug 1971
                      (the end of the fixed $35 gold window), % change.
                      The fix publishes with a ~1-day lag, so the CURRENT
                      move comes from COMEX futures (Yahoo GC=F) whenever
                      futures have a fresher date than the fix.
  3. Yahoo ^TNX     — CBOE 10-year Treasury yield since 1962,
                      move measured in basis points (1 bp = 0.01%)
  4. Yahoo DX-Y.NYB — ICE US Dollar Index since 1971, % change
  5. Yahoo BTC-USD  — Bitcoin since Sep 2014, % change

Run:  python fetch_daily_move.py
Requires: requests  (pip install requests)
"""

import requests
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone

# ── CONFIG ─────────────────────────────────────────────────────────────────────
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "indicators", "macro", "daily_move_distribution.html")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

N_BINS      = 90    # histogram bins across mean ± 4.5 sd (bin width = sd/10)
BIN_SPAN_SD = 4.5
MAX_GAP_DAYS = 7    # don't compute a "daily" move across a longer gap

# Sanity floors: refuse to bake if a source comes back suspiciously short
# (protects against silent API degradation shrinking the distribution).
MIN_MOVES = {"spx": 20000, "gold": 11000, "ust10y": 13000, "dxy": 11000, "btc": 3500}


# ── FETCHERS ───────────────────────────────────────────────────────────────────
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def fetch_yahoo(symbol):
    """Full daily history -> [(date_str, close)]. Uses epoch arithmetic for
    dates because Windows fromtimestamp() rejects pre-1970 timestamps."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1d",
              "period1": "-2208988800",                  # 1900-01-01
              "period2": str(int(time.time()) + 86400)}
    r = requests.get(url, params=params, headers=HEADERS, timeout=120)
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    stamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    out, seen = [], set()
    for ts, c in zip(stamps, closes):
        if c is None or c <= 0:
            continue
        d = (EPOCH + timedelta(seconds=ts)).strftime("%Y-%m-%d")
        if d in seen:
            continue
        seen.add(d)
        out.append((d, float(c)))
    out.sort()
    return out


def fetch_lbma_gold():
    """LBMA gold PM fix, daily USD/oz -> [(date_str, price)]."""
    url = "https://prices.lbma.org.uk/json/gold_pm.json"
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    out = []
    for rec in r.json():                       # records are date-ascending
        v = rec.get("v")
        if v and v[0]:
            out.append((rec["d"][:10], float(v[0])))
    return out


# ── MOVE MATH ──────────────────────────────────────────────────────────────────
def day_gap(d1, d2):
    return (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days


def compute_moves(series, kind, max_abs):
    """kind 'pct': percent change; kind 'bp': basis-point change of a yield.
    Returns [(date, move)] skipping long gaps and bad-tick outliers."""
    moves = []
    for (d0, v0), (d1, v1) in zip(series, series[1:]):
        if day_gap(d0, d1) > MAX_GAP_DAYS:
            continue
        m = (v1 / v0 - 1) * 100 if kind == "pct" else (v1 - v0) * 100
        if abs(m) > max_abs:
            continue
        moves.append((d1, m))
    return moves


def build_asset(spec, series, cur_override=None):
    moves = compute_moves(series, spec["kind"], spec["max_abs"])
    n = len(moves)
    if n < MIN_MOVES[spec["id"]]:
        raise SystemExit(f"ERROR: {spec['name']} produced only {n} moves "
                         f"(< {MIN_MOVES[spec['id']]}) — refusing to bake degraded data.")

    vals = [m for _, m in moves]
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)

    cur_d, cur_v = moves[-1]
    if cur_override and cur_override[0] > cur_d:
        cur_d, cur_v = cur_override          # fresher quote from the live source
    rec_min = min(moves, key=lambda t: t[1])
    rec_max = max(moves, key=lambda t: t[1])

    # histogram: N_BINS bins across mean ± BIN_SPAN_SD * sd
    bin_lo = mean - BIN_SPAN_SD * sd
    bin_w = 2 * BIN_SPAN_SD * sd / N_BINS
    counts, below, above = [0] * N_BINS, 0, 0
    for v in vals:
        i = int((v - bin_lo) / bin_w)
        if v < bin_lo:
            below += 1
        elif i >= N_BINS:
            above += 1
        else:
            counts[i] += 1

    # stats for the current move
    z = (cur_v - mean) / sd
    pctile = 100 * (sum(1 for v in vals if v < cur_v)
                    + 0.5 * sum(1 for v in vals if v == cur_v)) / n
    n_bigger = sum(1 for v in vals if abs(v) >= abs(cur_v))
    one_in = round(n / n_bigger, 1) if n_bigger else None

    rd = 1 if spec["kind"] == "bp" else 2
    return {
        "id": spec["id"], "name": spec["name"],
        "unit": "bp" if spec["kind"] == "bp" else "%",
        "subLabel": spec["sub"],
        "start": moves[0][0], "n": n,
        "mean": round(mean, 5), "sd": round(sd, 5),
        "binLo": round(bin_lo, 6), "binW": round(bin_w, 6),
        "counts": counts, "below": below, "above": above,
        "recMin": {"v": round(rec_min[1], rd), "d": rec_min[0]},
        "recMax": {"v": round(rec_max[1], rd), "d": rec_max[0]},
        "cur": {"v": round(cur_v, rd), "d": cur_d},
        "z": round(z, 2), "pctile": round(pctile, 1), "oneIn": one_in,
    }


# ── MAIN ───────────────────────────────────────────────────────────────────────
SPECS = [
    {"id": "spx",    "name": "S&P 500",  "kind": "pct", "max_abs": 30,
     "sub": "% change vs prior close", "fetch": lambda: fetch_yahoo("^GSPC")},
    {"id": "gold",   "name": "Gold",     "kind": "pct", "max_abs": 30,
     "sub": "% change vs prior close",
     "fetch": lambda: [(d, v) for d, v in fetch_lbma_gold() if d >= "1971-08-16"],
     "live":  lambda: fetch_yahoo("GC=F")},
    {"id": "ust10y", "name": "US 10YR Yield", "kind": "bp", "max_abs": 150,
     "sub": "basis-point change vs prior close", "fetch": lambda: fetch_yahoo_tnx()},
    {"id": "dxy",    "name": "DXY (US Dollar Index)", "kind": "pct", "max_abs": 30,
     "sub": "% change vs prior close", "fetch": lambda: fetch_yahoo("DX-Y.NYB")},
    {"id": "btc",    "name": "Bitcoin",  "kind": "pct", "max_abs": 60,
     "sub": "% change vs prior close", "fetch": lambda: fetch_yahoo("BTC-USD")},
]


def fetch_yahoo_tnx():
    """^TNX with unit normalization: the index is historically quoted at
    10x the yield (44.6 = 4.46%); Yahoo sometimes serves it pre-divided.
    Normalize so values are the yield in percent."""
    series = fetch_yahoo("^TNX")
    last = series[-1][1]
    if last > 20:                       # quoted at 10x
        series = [(d, v / 10) for d, v in series]
    return series


assets = []
for spec in SPECS:
    print(f"Fetching {spec['name']}...")
    series = spec["fetch"]()
    cur_override = None
    if "live" in spec:
        live_moves = compute_moves(spec["live"](), spec["kind"], spec["max_abs"])
        if live_moves:
            cur_override = live_moves[-1]
    a = build_asset(spec, series, cur_override)
    assets.append(a)
    print(f"  {a['name']:22s}: {a['n']:6d} moves since {a['start']}, "
          f"last {a['cur']['d']} = {a['cur']['v']:+.2f}{a['unit']} "
          f"(z {a['z']:+.2f}, {a['pctile']:.1f} pctile, 1-in-{a['oneIn']})")

# ── INJECT INTO HTML ───────────────────────────────────────────────────────────
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

today = datetime.now().strftime("%Y-%m-%d")
baked_block = (
    f"    const DMHD_ASSETS   = {json.dumps(assets)};\n"
    f"    const DMHD_BAKED_ON = \"{today}\"; // injected by fetch_daily_move.py"
)

pattern = r"(// @@BAKED_DATA_START@@)[\s\S]*?(// @@BAKED_DATA_END@@)"
new_html, count = re.subn(pattern, r"\g<1>\n" + baked_block + "\n    \\2", html)

if count == 0:
    print("ERROR: Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers.")
    raise SystemExit(1)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(new_html)

print(f"Injected {len(assets)} assets into {HTML_PATH}")
print("Done.")
