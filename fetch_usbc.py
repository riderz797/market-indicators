"""
fetch_usbc.py
Incrementally updates the US Business Cycle Indicator.

Reads the existing baked data from market_overheat_index.html, finds the
last computed month, fetches only the data needed to extend forward, and
appends new months. Historical data is preserved as-is.

Run:  python fetch_usbc.py
Requires: requests, yfinance  (pip install requests yfinance)
"""

import requests
import json
import os
import re
from datetime import datetime
import yfinance as yf

# ── CONFIG ─────────────────────────────────────────────────────────────────────
FRED_API_KEY = "824b29c5afa52f3fc7c6e7dc4925aebb"
HTML_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "indicators", "macro", "market_overheat_index.html")

# ── READ EXISTING BAKED DATA FROM HTML ────────────────────────────────────────
def read_baked_data(html):
    """Extract existing USBC_DATES and USBC_VALUES arrays from the HTML."""
    dates_m  = re.search(r'const USBC_DATES\s*=\s*(\[[\s\S]*?\]);', html)
    values_m = re.search(r'const USBC_VALUES\s*=\s*(\[[\s\S]*?\]);', html)
    if not dates_m or not values_m:
        return [], []
    return json.loads(dates_m.group(1)), json.loads(values_m.group(1))


# ── FETCH S&P 500 FROM YAHOO FINANCE ──────────────────────────────────────────
def fetch_sp500_yfinance(obs_start):
    """Returns dict {YYYY-MM: float} from Yahoo Finance."""
    ticker = yf.Ticker("^GSPC")
    hist   = ticker.history(start=obs_start, interval="1mo")
    result = {}
    for ts, row in hist.iterrows():
        ym = ts.strftime("%Y-%m")
        if not row.empty and row["Close"] > 0:
            result[ym] = float(row["Close"])
    return result


# ── FETCH FROM FRED ────────────────────────────────────────────────────────────
def fetch_fred(series_id, obs_start, frequency="m"):
    """Returns dict {YYYY-MM: float} from FRED."""
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


# ── MAIN ───────────────────────────────────────────────────────────────────────
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

existing_dates, existing_values = read_baked_data(html)

if existing_dates:
    last_date_str = existing_dates[-1]          # e.g. "2026-01-01"
    last_ym       = last_date_str[:7]           # e.g. "2026-01"
    print(f"Existing baked data: {len(existing_dates)} points, last = {last_ym}")
else:
    last_ym = "1958-12"
    print("No existing baked data found — computing from scratch.")

# Fetch window: 14 months back from last_ym covers the YoY CPI lookback
fetch_start_cpi = shift_ym(last_ym, 13)   # 13 months back for safe YoY overlap
fetch_start_sp  = shift_ym(last_ym, 1)    # 1 month back to catch any revision

print(f"Fetching new data from {fetch_start_sp} onward...")
sp500    = fetch_sp500_yfinance(fetch_start_sp + "-01")
unrate   = fetch_fred("UNRATE",   fetch_start_sp + "-01", "m")
cpi      = fetch_fred("CPIAUCSL", fetch_start_cpi + "-01", "m")
fedfunds = fetch_fred("FEDFUNDS", fetch_start_sp + "-01", "m")
m2       = fetch_fred("M2SL",     fetch_start_sp + "-01", "m")

print(f"  SP500  : {len(sp500)} months")
print(f"  UNRATE : {len(unrate)} months")
print(f"  CPI    : {len(cpi)} months")
print(f"  FEDFUNDS: {len(fedfunds)} months")
print(f"  M2SL   : {len(m2)} months")

# We need the last 12 months of CPI from the existing baked period for YoY.
# Re-fetch just that window from FRED (small request).
cpi_history_start = shift_ym(last_ym, 13)
cpi_full = fetch_fred("CPIAUCSL", cpi_history_start + "-01", "m")
cpi_full.update(cpi)   # merge, new data wins

# ── COMPUTE NEW MONTHS ONLY ────────────────────────────────────────────────────
print("Computing new months...")
new_dates  = []
new_values = []

for ym in sorted(sp500.keys()):
    if ym <= last_ym:
        continue   # skip anything already baked

    sp       = sp500.get(ym)
    un       = unrate.get(ym)
    cpi_curr = cpi_full.get(ym)
    cpi_prev = cpi_full.get(shift_ym(ym, 12))
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
    print(f"  {len(new_dates)} new point(s): {new_dates[0]} to {new_dates[-1]}")
else:
    print("  No new months available yet — data is already current.")

# ── MERGE AND INJECT ───────────────────────────────────────────────────────────
merged_dates  = existing_dates  + new_dates
merged_values = existing_values + new_values

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

print(f"Injected {len(merged_dates)} total points ({merged_dates[0]} – {merged_dates[-1]}) into {HTML_PATH}")
print("Done.")
