"""
fetch_ddt.py
Bakes component data for the Dollar Debasement Tracking indicator.

Fetches five sources and injects aligned monthly raw arrays into
dollar_debasement_tracking.html. The page computes the pillar scores and
the composite itself, so the formula lives in one place.

Sources (all free, no registration):
  1. IMF COFER (new api.imf.org SDMX API) — USD share of world FX reserves,
     quarterly from 1999. Dec-2025 revised basis: share of TOTAL reserves,
     the old allocated/unallocated split was eliminated.
  2. Treasury TIC mfhhis01.txt — foreign official holdings of US Treasuries,
     monthly from Feb 2000, $B. (The mfh.txt/mfh.csv snapshots are frozen;
     this history file is the one Treasury keeps current.)
  3. FRED — broad dollar index: TWEXBMTH (1973-2019, discontinued) ratio-
     spliced into DTWEXBGS (2006-present) at Jan 2006.
  4. IMF International Liquidity (IL) — world official gold holdings in fine
     troy ounces and world FX reserves ex-gold in USD, monthly from 1995.
  5. LBMA — gold PM fix USD/oz, daily from 1968, month-end taken.

Dataset is small (~440 months x 5 series), so this does a full rebuild on
every run — IMF and TIC both revise history.

Run:  python fetch_ddt.py
Requires: requests  (pip install requests)
"""

import requests
import json
import os
import re
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────────
FRED_API_KEY = "824b29c5afa52f3fc7c6e7dc4925aebb"
HTML_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "indicators", "macro", "dollar_debasement_tracking.html")

FIRST_MONTH = "1990-01"   # warm-up for the 10-yr dollar lookback; display starts 2001
SPLICE_YM   = "2006-01"   # dollar index: TWEXBMTH before, DTWEXBGS from here

IMF_BASE = "https://api.imf.org/external/sdmx/2.1/data"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

# Sanity floors: refuse to bake if a source comes back suspiciously short
# (protects against silent API degradation shrinking the chart).
MIN_OBS = {"cofer": 100, "tic": 250, "dxy": 430, "gold_oz": 350, "fx_usd": 350, "gold_px": 430}


# ── DATE MATH ──────────────────────────────────────────────────────────────────
def shift_ym(ym, months_back):
    y, m  = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (m - 1) - months_back
    return f"{total // 12}-{(total % 12) + 1:02d}"


def month_range(start_ym, end_ym):
    out, ym = [], start_ym
    while ym <= end_ym:
        out.append(ym)
        ym = shift_ym(ym, -1)
    return out


# ── FETCHERS ───────────────────────────────────────────────────────────────────
def fetch_fred(series_id, obs_start, frequency=None, aggregation_method=None):
    url    = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id":         series_id,
        "api_key":           FRED_API_KEY,
        "file_type":         "json",
        "observation_start": obs_start,
        "sort_order":        "asc",
        "limit":             100000,
    }
    if frequency:
        params["frequency"] = frequency
    if aggregation_method:
        params["aggregation_method"] = aggregation_method

    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error_message" in data:
        raise RuntimeError(f"FRED error for {series_id}: {data['error_message']}")

    result = {}
    for obs in data.get("observations", []):
        if obs["value"] == ".":
            continue
        result[obs["date"][:7]] = float(obs["value"])
    return result


def fetch_imf(flow, key, start="1990"):
    """Fetch one series from the new IMF SDMX API; returns {period: value}.
    Periods come back as '1999-Q1' (quarterly) or '2026-M04' (monthly)."""
    url = f"{IMF_BASE}/{flow}/{key}?startPeriod={start}"
    r   = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    obs = re.findall(
        r'TIME_PERIOD="([0-9]{4}-[QM][0-9]{1,2})"[^>]*OBS_VALUE="([0-9.Ee+-]+)"',
        r.text)
    if not obs:
        raise RuntimeError(f"IMF returned no observations for {flow}/{key}")
    return {p: float(v) for p, v in obs}


MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def fetch_tic_official():
    """Parse foreign official holdings ($B) from the TIC major-foreign-holders
    history file. Year blocks are newest-first; each block has a month header
    line directly above a 'Country <year> <year> ...' line, then a
    'For. Official' row. First occurrence wins (newest vintage)."""
    url = "https://ticdata.treasury.gov/Publish/mfhhis01.txt"
    r   = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    lines = r.text.split("\n")

    result, cols = {}, None
    for idx, line in enumerate(lines):
        cells = [c.strip() for c in line.split("\t")]
        if cells and cells[0] == "Country":
            years  = [c for c in cells[1:] if re.fullmatch(r"(19|20)\d{2}", c)]
            months = []
            for back in (1, 2):
                prev = [c.strip() for c in lines[idx - back].split("\t")]
                months = [c for c in prev if c in MONTH_NUM]
                if months:
                    break
            cols = (list(zip(months, years)) if len(months) == len(years) and months
                    else None)
        elif cells and cells[0] == "For. Official" and cols:
            vals = [c for c in cells[1:] if c]
            for (mon, yr), v in zip(cols, vals):
                try:
                    val = float(v)
                except ValueError:
                    continue
                ym = f"{yr}-{MONTH_NUM[mon]:02d}"
                result.setdefault(ym, val)   # newest vintage appears first
            cols = None
    return result


def fetch_lbma_gold():
    """LBMA gold PM fix, daily USD/oz -> month-end value per month."""
    url = "https://prices.lbma.org.uk/json/gold_pm.json"
    r   = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    result = {}
    for rec in r.json():                    # records are date-ascending
        v = rec.get("v")
        if v and v[0]:
            result[rec["d"][:7]] = float(v[0])   # last record per month wins
    return result


# ── MAIN ───────────────────────────────────────────────────────────────────────
print("Fetching IMF COFER (USD share of world FX reserves)...")
cofer_raw = fetch_imf("IMF.STA,COFER", "G001.AFXRA.CI_USD.SHRO_PT.Q", "1999")
cofer_q   = sorted(cofer_raw.items())               # [('1999-Q1', 71.19), ...]

print("Fetching Treasury TIC foreign official holdings...")
tic = fetch_tic_official()

print("Fetching FRED dollar indices...")
dtwex = fetch_fred("DTWEXBGS", "2006-01-01", "m", "avg")
twexb = fetch_fred("TWEXBMTH", "1989-01-01")

print("Fetching IMF International Liquidity (gold oz + FX reserves)...")
gold_oz = fetch_imf("IMF.STA,IL", "G001.RGV_REVS.FTO.M", "1994")
fx_usd  = fetch_imf("IMF.STA,IL", "G001.RXF11FX_REVS.USD.M", "1994")

print("Fetching LBMA gold PM fix...")
gold_px = fetch_lbma_gold()

# Normalize IMF monthly periods '1995-M01' -> '1995-01'
gold_oz = {p.replace("-M", "-"): v for p, v in gold_oz.items()}
fx_usd  = {p.replace("-M", "-"): v for p, v in fx_usd.items()}

# Splice the dollar index: scale TWEXBMTH so it equals DTWEXBGS at Jan 2006
if SPLICE_YM not in dtwex or SPLICE_YM not in twexb:
    raise RuntimeError("Dollar splice month missing from FRED data")
factor = dtwex[SPLICE_YM] / twexb[SPLICE_YM]
dxy = {ym: v * factor for ym, v in twexb.items() if ym < SPLICE_YM}
dxy.update(dtwex)

for name, s, key in [("COFER", dict(cofer_q), "cofer"), ("TIC", tic, "tic"),
                     ("Dollar", dxy, "dxy"), ("Gold oz", gold_oz, "gold_oz"),
                     ("FX reserves", fx_usd, "fx_usd"), ("Gold price", gold_px, "gold_px")]:
    last = max(s) if s else "n/a"
    print(f"  {name:12s}: {len(s):4d} obs, last = {last}")
    if len(s) < MIN_OBS[key]:
        raise SystemExit(
            f"ERROR: {name} returned only {len(s)} obs (< {MIN_OBS[key]}) — "
            f"refusing to bake degraded data.")

# Month grid: through the latest dollar-index month (the freshest series)
end_ym = max(dxy)
months = month_range(FIRST_MONTH, end_ym)

raw = {
    "tic":    [tic.get(ym) for ym in months],
    "dxy":    [round(dxy[ym], 4) if ym in dxy else None for ym in months],
    "goldOz": [round(gold_oz[ym]) if ym in gold_oz else None for ym in months],
    "goldPx": [round(gold_px[ym], 2) if ym in gold_px else None for ym in months],
    "fxUsd":  [round(fx_usd[ym]) if ym in fx_usd else None for ym in months],
}
cofer_baked = {"q": [q for q, _ in cofer_q], "v": [round(v, 4) for _, v in cofer_q]}

print(f"Built {len(months)} months ({months[0]} - {months[-1]}), "
      f"{len(cofer_baked['q'])} COFER quarters.")

# ── INJECT INTO HTML ───────────────────────────────────────────────────────────
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

today       = datetime.now().strftime("%Y-%m-%d")
baked_block = (
    f"    const DDT_MONTHS   = {json.dumps(months)};\n"
    f"    const DDT_RAW      = {json.dumps(raw)};\n"
    f"    const DDT_COFER_Q  = {json.dumps(cofer_baked)};\n"
    f"    const DDT_BAKED_ON = \"{today}\"; // injected by fetch_ddt.py"
)

pattern  = r"(// @@BAKED_DATA_START@@)[\s\S]*?(// @@BAKED_DATA_END@@)"
new_html, n = re.subn(pattern, r"\g<1>\n" + baked_block + "\n    \\2", html)

if n == 0:
    print("ERROR: Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers.")
    raise SystemExit(1)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(new_html)

print(f"Injected {len(months)} months into {HTML_PATH}")
print("Done.")
