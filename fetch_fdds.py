"""
fetch_fdds.py
Bakes component data for the Fiscal Dominance Debt Spiral indicator.

Fetches the FRED series plus the NY Fed ACM term premium, builds the aligned
monthly component arrays (interest/GDP, core PCE YoY, Fed footprint YoY,
10Y term premium, M2 YoY), and injects them into
fiscal_dominance_debt_spiral.html. The page computes the z-scores and the
index itself, so the formula lives in one place.

Fed footprint is spliced: monetary base (BOGMBASE) YoY before Dec 2003,
Fed total assets (WALCL) YoY from Dec 2003 onward — WALCL only exists from
Dec 2002, and the monetary base is the standard proxy for the Fed's
balance-sheet footprint before that.

Term premium is the NY Fed ACM model (monthly, from Jun 1961); falls back
to FRED's Kim-Wright series (from 1990) if the NY Fed download fails.

Dataset is small (~800 months x 5 series), so this does a full rebuild
on every run rather than an incremental extension.

Run:  python fetch_fdds.py
Requires: requests, pandas, xlrd  (pip install requests pandas xlrd)
"""

import requests
import json
import os
import re
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────────
FRED_API_KEY = "824b29c5afa52f3fc7c6e7dc4925aebb"
HTML_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "indicators", "macro", "fiscal_dominance_debt_spiral.html")

FIRST_MONTH = "1960-01"   # z-score warm-up history; index itself starts ~1964
SPLICE_YM   = "2003-12"   # Fed footprint: monetary base before, WALCL from here
ACM_URL     = ("https://www.newyorkfed.org/medialibrary/media/research/"
               "data_indicators/ACMTermPremium.xls")


# ── FETCH FROM FRED ────────────────────────────────────────────────────────────
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

    r = requests.get(url, params=params, timeout=30)
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


def ym_index(ym):
    return int(ym[:4]) * 12 + int(ym[5:7])


# ── ACM TERM PREMIUM (NY FED) ──────────────────────────────────────────────────
def fetch_acm():
    import io
    import pandas as pd
    r = requests.get(ACM_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    r.raise_for_status()
    df    = pd.read_excel(io.BytesIO(r.content), sheet_name="ACM Monthly")
    dates = pd.to_datetime(df["DATE"], format="%d-%b-%Y")
    return {d.strftime("%Y-%m"): float(v)
            for d, v in zip(dates, df["ACMTP10"]) if pd.notna(v)}


# ── MAIN ───────────────────────────────────────────────────────────────────────
print("Fetching FRED series...")
int_q = fetch_fred("A091RC1Q027SBEA", "1959-01-01")               # quarterly
gdp_q = fetch_fred("GDP",             "1959-01-01")               # quarterly
pce   = fetch_fred("PCEPILFE",        "1959-01-01")               # monthly
base  = fetch_fred("BOGMBASE",        "1959-01-01")               # monthly, monetary base
walcl = fetch_fred("WALCL",           "2002-12-01", "m", "eop")   # weekly -> month-end
m2    = fetch_fred("M2SL",            "1959-01-01")               # monthly
ff    = fetch_fred("FEDFUNDS",        "1959-01-01")               # monthly, spiral flag only
try:
    print("Fetching ACM term premium from NY Fed...")
    tp = fetch_acm()                                              # monthly, from 1961-06
except Exception as e:
    print(f"  WARNING: ACM download failed ({e}) — falling back to Kim-Wright (FRED).")
    try:
        tp = fetch_fred("THREEFYTP10", "1990-01-01", "m", "avg")
    except Exception as e2:
        print(f"  WARNING: Kim-Wright also failed ({e2}) — baking without term premium.")
        tp = {}

for name, s in [("Interest", int_q), ("GDP", gdp_q), ("Core PCE", pce),
                ("Mon. base", base), ("WALCL", walcl), ("M2", m2),
                ("Fed funds", ff), ("Term premium", tp)]:
    last = max(s) if s else "n/a"
    print(f"  {name:13s}: {len(s):4d} obs, last = {last}")

# Interest/GDP %, quarterly
int_gdp_q = sorted(
    (ym, 100.0 * v / gdp_q[ym]) for ym, v in int_q.items() if ym in gdp_q
)

end_ym = max(pce)            # core PCE is the slowest monthly release
months = month_range(FIRST_MONTH, end_ym)

# Forward-fill quarterly interest/GDP to monthly (<= 8 months stale)
int_m, qi = [], -1
for ym in months:
    while qi + 1 < len(int_gdp_q) and int_gdp_q[qi + 1][0] <= ym:
        qi += 1
    if qi < 0 or ym_index(ym) - ym_index(int_gdp_q[qi][0]) > 8:
        int_m.append(None)
    else:
        int_m.append(round(int_gdp_q[qi][1], 4))


def yoy(series):
    out = []
    for ym in months:
        c, p = series.get(ym), series.get(shift_ym(ym, 12))
        out.append(round(100.0 * (c / p - 1), 4) if c is not None and p else None)
    return out


# Fed footprint: monetary base YoY before the splice, WALCL YoY after
fed_base  = yoy(base)
fed_walcl = yoy(walcl)
fed_m = [fed_walcl[i] if months[i] >= SPLICE_YM else fed_base[i]
         for i in range(len(months))]

raw = {
    "int": int_m,
    "pce": yoy(pce),
    "fed": fed_m,
    "tp":  [round(tp[ym], 4) if ym in tp else None for ym in months],
    "m2":  yoy(m2),
    "ff":  [round(ff[ym], 2) if ym in ff else None for ym in months],  # flag only
}

complete = sum(
    1 for i in range(len(months))
    if all(raw[k][i] is not None for k in ("int", "pce", "fed", "m2"))
)
print(f"Built {len(months)} months ({months[0]} - {months[-1]}), "
      f"{complete} with all required components.")

# ── INJECT INTO HTML ───────────────────────────────────────────────────────────
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()


# No-shrink guard: a degraded fetch (e.g. ACM falling back to Kim-Wright, which
# only starts in 1990) must fail loudly rather than silently shorten the chart.
def first_complete(months_list, raw_dict):
    keys = ("int", "pce", "fed", "m2", "tp")
    for i, ym in enumerate(months_list):
        if all(raw_dict[k][i] is not None for k in keys):
            return ym
    return None


months_m = re.search(r'const FDDS_MONTHS\s*=\s*(\[.*?\]);', html)
raw_m    = re.search(r'const FDDS_RAW\s*=\s*(\{.*?\});', html)
if months_m and raw_m:
    try:
        old_start = first_complete(json.loads(months_m.group(1)),
                                   json.loads(raw_m.group(1)))
    except json.JSONDecodeError:
        old_start = None
    new_start = first_complete(months, raw)
    if old_start and (new_start is None or new_start > old_start):
        print(f"ERROR: new data would start {new_start} but existing baked data "
              f"starts {old_start} — refusing to shrink history. Existing bake kept.")
        raise SystemExit(1)

today       = datetime.now().strftime("%Y-%m-%d")
baked_block = (
    f"    const FDDS_MONTHS   = {json.dumps(months)};\n"
    f"    const FDDS_RAW      = {json.dumps(raw)};\n"
    f"    const FDDS_BAKED_ON = \"{today}\"; // injected by fetch_fdds.py"
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
