"""
fetch_usbc.py
Incrementally updates the US Business Cycle Indicator.

Reads the existing baked data from market_overheat_index.html, finds the
last computed month and any gaps, fetches only the data needed to extend
forward and fill gaps, then writes the result back.

Run:  python fetch_usbc.py
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
                            "indicators", "macro", "market_overheat_index.html")


# ── READ EXISTING BAKED DATA FROM HTML ────────────────────────────────────────
def read_baked_data(html):
    dates_m  = re.search(r'const USBC_DATES\s*=\s*(\[[\s\S]*?\]);', html)
    values_m = re.search(r'const USBC_VALUES\s*=\s*(\[[\s\S]*?\]);', html)
    if not dates_m or not values_m:
        return [], []
    return json.loads(dates_m.group(1)), json.loads(values_m.group(1))


# ── FETCH FROM FRED ────────────────────────────────────────────────────────────
def fetch_fred(series_id, obs_start, frequency="m", aggregation_method=None):
    url    = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id":         series_id,
        "api_key":           FRED_API_KEY,
        "file_type":         "json",
        "observation_start": obs_start,
        "sort_order":        "asc",
        "limit":             100000,
        "frequency":         frequency,
    }
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
        ym = obs["date"][:7]
        result[ym] = float(obs["value"])
    return result


# ── DATE MATH ──────────────────────────────────────────────────────────────────
def shift_ym(ym, months_back):
    y, m  = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (m - 1) - months_back
    return f"{total // 12}-{(total % 12) + 1:02d}"


def find_gaps(dates):
    """Return list of YYYY-MM strings missing from a sorted date list."""
    if not dates:
        return []
    gaps = []
    prev_y, prev_m = None, None
    for d in sorted(dates):
        y, m = int(d[:4]), int(d[5:7])
        if prev_y is not None:
            ey, em = (prev_y, prev_m + 1) if prev_m < 12 else (prev_y + 1, 1)
            while (ey, em) != (y, m):
                gaps.append(f"{ey}-{em:02d}")
                em += 1
                if em > 12:
                    ey += 1
                    em = 1
        prev_y, prev_m = y, m
    return gaps


# ── MAIN ───────────────────────────────────────────────────────────────────────
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

existing_dates, existing_values = read_baked_data(html)
existing_set = {d[:7] for d in existing_dates}

if existing_dates:
    last_ym = existing_dates[-1][:7]
    print(f"Existing baked data: {len(existing_dates)} points, last = {last_ym}")
else:
    last_ym = "1958-12"
    print("No existing baked data found — computing from scratch.")

gaps = find_gaps(existing_dates)
if gaps:
    print(f"Gaps detected: {gaps}")
    earliest_gap = gaps[0]
else:
    earliest_gap = None

# Fetch far enough back to cover both gaps and 1-month revision window
if earliest_gap and earliest_gap < shift_ym(last_ym, 1):
    effective_start = earliest_gap
else:
    effective_start = shift_ym(last_ym, 1)

fetch_start_cpi = shift_ym(effective_start, 13)  # 13-month lookback for YoY CPI

print(f"Fetching data from {effective_start} onward (CPI from {fetch_start_cpi})...")

# SP500 from FRED (end-of-period monthly close) — replaces yfinance for reliability
sp500    = fetch_fred("SP500",    effective_start + "-01", "m", "eop")
unrate   = fetch_fred("UNRATE",   effective_start + "-01", "m")
cpi      = fetch_fred("CPIAUCSL", fetch_start_cpi + "-01", "m")
fedfunds = fetch_fred("FEDFUNDS", effective_start + "-01", "m")
m2       = fetch_fred("M2SL",     effective_start + "-01", "m")

print(f"  SP500    : {len(sp500)} months")
print(f"  UNRATE   : {len(unrate)} months")
print(f"  CPI      : {len(cpi)} months")
print(f"  FEDFUNDS : {len(fedfunds)} months")
print(f"  M2SL     : {len(m2)} months")

# Months to compute: any month in the fetch window not already baked
all_months = sorted(
    (set(sp500) | set(unrate) | set(m2) | set(fedfunds)) - existing_set
)

print("Computing missing/new months...")
new_dates  = []
new_values = []

for ym in all_months:
    sp       = sp500.get(ym)
    un       = unrate.get(ym)
    cpi_curr = cpi.get(ym)
    cpi_prev = cpi.get(shift_ym(ym, 12))
    fed      = fedfunds.get(ym)
    m2_val   = m2.get(ym)

    if None in (sp, un, cpi_curr, cpi_prev, fed, m2_val):
        continue
    if un <= 0 or m2_val <= 0 or cpi_prev <= 0:
        continue

    yoy_cpi = (cpi_curr / cpi_prev - 1) * 100
    val     = (sp / (un ** 2)) * (yoy_cpi * fed) / m2_val

    new_dates.append(ym + "-01")
    new_values.append(round(val, 6))

if new_dates:
    print(f"  {len(new_dates)} new/filled point(s): {new_dates[0]} -> {new_dates[-1]}")
else:
    print("  No new months available yet — data is already current.")

# Merge into sorted combined list
combined = dict(zip(existing_dates, existing_values))
for d, v in zip(new_dates, new_values):
    combined[d] = v

merged_dates  = sorted(combined.keys())
merged_values = [combined[d] for d in merged_dates]

today       = datetime.now().strftime("%Y-%m-%d")
baked_block = (
    f"    const USBC_DATES  = {json.dumps(merged_dates)};\n"
    f"    const USBC_VALUES = {json.dumps(merged_values)};\n"
    f"    const USBC_BAKED  = true; // injected by fetch_usbc.py on {today}"
)

pattern  = r"(// @@BAKED_DATA_START@@)[\s\S]*?(// @@BAKED_DATA_END@@)"
new_html, n = re.subn(pattern, r"\g<1>\n" + baked_block + "\n    \\2", html)

if n == 0:
    print("ERROR: Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers.")
    raise SystemExit(1)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(new_html)

total_range = f"{merged_dates[0]} – {merged_dates[-1]}" if merged_dates else "empty"
print(f"Injected {len(merged_dates)} total points ({total_range}) into {HTML_PATH}")
print("Done.")
