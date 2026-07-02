"""
fetch_capability_data.py
Bakes price-history CSVs for the Age-Indexed Capability Portfolio tool.

For each portfolio bucket, fetches the full daily history from Yahoo and
writes data/{bucket}.csv with two columns: date,close. The tool
(indicators/tools/capability_portfolio.html) loads these via the GitHub
contents API, resamples to quarter-end closes, and derives quarterly
mu / sigma and the cross-bucket correlation matrix client-side.

Closes are dividend/split-adjusted (Yahoo adjclose) where available, so
returns are total-return — this matters most for the cash bucket, whose
entire return is yield.

Buckets (Tactical is intentionally absent — it has no public price
series and stays manual-entry in the tool):
  bitcoin     Yahoo BTC-USD  — since Sep 2014
  stocks      Yahoo SPY      — S&P 500 ETF, total return, since 1993
  realestate  Yahoo VNQ      — US REIT ETF, since 2004
  gold        Yahoo GLD      — gold ETF, since 2004
  cash        Yahoo BIL      — 1-3mo T-bill ETF, since 2007

Run:  python fetch_capability_data.py
Requires: requests  (pip install requests)
"""

import os
import random
import time
from datetime import datetime, timedelta, timezone

import requests

# ── CONFIG ─────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

BUCKETS = [
    {"file": "bitcoin",    "symbol": "BTC-USD", "min_rows": 3000},
    {"file": "stocks",     "symbol": "SPY",     "min_rows": 7000},
    {"file": "realestate", "symbol": "VNQ",     "min_rows": 4500},
    {"file": "gold",       "symbol": "GLD",     "min_rows": 4500},
    {"file": "cash",       "symbol": "BIL",     "min_rows": 4000},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Yahoo rate-limits shared/datacenter IPs (e.g. GitHub Actions runners) with
# HTTP 429, and occasionally gates the chart API behind a cookie with 401. A
# single request is therefore unreliable from CI even when the data is fine, so
# we reuse a session and retry across both Yahoo hosts with exponential backoff.
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
YAHOO_RETRIES = 5


def _warm_yahoo_cookies():
    try:
        SESSION.get("https://finance.yahoo.com", timeout=30)
    except requests.RequestException:
        pass


def _yahoo_chart(symbol):
    path = f"/v8/finance/chart/{symbol}"
    params = {"interval": "1d",
              "period1": "-2208988800",                  # 1900-01-01
              "period2": str(int(time.time()) + 86400)}
    last_err = None
    for attempt in range(YAHOO_RETRIES):
        host = YAHOO_HOSTS[attempt % len(YAHOO_HOSTS)]
        try:
            r = SESSION.get(f"https://{host}{path}", params=params, timeout=120)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
            if r.status_code in (401, 403):       # cookie-gated → warm and retry
                _warm_yahoo_cookies()
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < YAHOO_RETRIES - 1:
            backoff = 2 ** attempt + random.uniform(0, 1)
            print(f"  Yahoo {symbol}: attempt {attempt + 1}/{YAHOO_RETRIES} "
                  f"failed ({last_err}); retrying in {backoff:.1f}s")
            time.sleep(backoff)
    raise RuntimeError(f"Yahoo fetch for {symbol} failed after "
                       f"{YAHOO_RETRIES} attempts (last error: {last_err})")


def fetch_yahoo(symbol):
    """Full daily history -> [(date_str, close)], preferring adjusted close."""
    result = _yahoo_chart(symbol)["chart"]["result"][0]
    stamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    adj = result["indicators"].get("adjclose")
    if adj and adj[0].get("adjclose"):
        closes = adj[0]["adjclose"]
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


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    failures = []
    for b in BUCKETS:
        print(f"Fetching {b['file']} ({b['symbol']})...")
        try:
            series = fetch_yahoo(b["symbol"])
        except RuntimeError as e:
            print(f"  ERROR: {e} — keeping existing CSV if any")
            failures.append(b["file"])
            continue
        if len(series) < b["min_rows"]:
            print(f"  ERROR: only {len(series)} rows (< {b['min_rows']}) — "
                  f"refusing to bake degraded data, keeping existing CSV")
            failures.append(b["file"])
            continue
        path = os.path.join(DATA_DIR, f"{b['file']}.csv")
        with open(path, "w", newline="") as f:
            f.write("date,close\n")
            for d, c in series:
                f.write(f"{d},{c:.6g}\n")
        print(f"  wrote {len(series)} rows -> data/{b['file']}.csv "
              f"({series[0][0]} .. {series[-1][0]})")
    if failures:
        raise SystemExit(f"Failed buckets: {', '.join(failures)}")
    print("All buckets baked.")


if __name__ == "__main__":
    main()
