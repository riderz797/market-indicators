"""
fetch_usbc.py
Fetches the five data series needed for the US Business Cycle Indicator,
computes monthly index values, and injects them into
indicators/macro/market_overheat_index.html between the @@BAKED_DATA@@ markers.

Run:  python fetch_usbc.py
Requires: requests, yfinance  (pip install requests yfinance)

NOTE: S&P 500 is fetched from Yahoo Finance via yfinance (free, full history).
      UNRATE, CPIAUCSL, FEDFUNDS, M2SL are fetched from FRED as usual.
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

# ── FETCH S&P 500 FROM YAHOO FINANCE ──────────────────────────────────────────
def fetch_sp500_yfinance(obs_start="1957-01-01"):
    """
    Fetches S&P 500 monthly closes via yfinance. Returns dict {YYYY-MM: float}.
    """
    ticker = yf.Ticker("^GSPC")
    hist   = ticker.history(start=obs_start, interval="1mo")
    result = {}
    for ts, row in hist.iterrows():
        ym = ts.strftime("%Y-%m")
        if not row.empty and row["Close"] > 0:
            result[ym] = float(row["Close"])
    return result


# ── FETCH FROM FRED ────────────────────────────────────────────────────────────
def fetch_fred(series_id, obs_start="1958-01-01", frequency="m"):
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
    y, m   = int(ym[:4]), int(ym[5:7])
    total  = y * 12 + (m - 1) - months_back
    ny     = total // 12
    nm     = (total % 12) + 1
    return f"{ny}-{nm:02d}"


# ── FETCH DATA ─────────────────────────────────────────────────────────────────
print("Fetching data...")
sp500    = fetch_sp500_yfinance("1957-01-01")
unrate   = fetch_fred("UNRATE",   "1959-01-01", "m")
cpi      = fetch_fred("CPIAUCSL", "1958-01-01", "m")   # extra year for YoY
fedfunds = fetch_fred("FEDFUNDS", "1959-01-01", "m")
m2       = fetch_fred("M2SL",     "1959-01-01", "m")

print(f"  SP500 (Yahoo): {len(sp500)} months")
print(f"  UNRATE       : {len(unrate)} months")
print(f"  CPIAUCSL     : {len(cpi)} months")
print(f"  FEDFUNDS     : {len(fedfunds)} months")
print(f"  M2SL         : {len(m2)} months")

# ── COMPUTE INDEX ──────────────────────────────────────────────────────────────
print("Computing index...")
dates  = []
values = []

for ym in sorted(sp500.keys()):
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

    dates.append(ym + "-01")
    values.append(round(val, 6))

print(f"  {len(dates)} monthly data points  ({dates[0]} to {dates[-1]})")

# ── INJECT INTO HTML ───────────────────────────────────────────────────────────
today        = datetime.now().strftime("%Y-%m-%d")
baked_block  = (
    f"    const USBC_DATES  = {json.dumps(dates)};\n"
    f"    const USBC_VALUES = {json.dumps(values)};\n"
    f"    const USBC_BAKED  = true; // injected by fetch_usbc.py on {today}"
)

with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

pattern     = r"(// @@BAKED_DATA_START@@)[\s\S]*?(// @@BAKED_DATA_END@@)"
replacement = r"\g<1>\n" + baked_block + "\n    \\2"
new_html, n = re.subn(pattern, replacement, html)

if n == 0:
    print("ERROR: Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers.")
    raise SystemExit(1)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(new_html)

print(f"Injected into {HTML_PATH}")
print("Done. Open market_overheat_index.html to preview.")
