"""
market_data.py
Shared price-history fetchers for the indicator build scripts.

Every source here returns the same shape — a date-ascending list of
(YYYY-MM-DD, float) — so callers can treat them interchangeably.

Currently used by bake_seasonality.py. fetch_daily_move.py still carries its
own near-identical copies of fetch_yahoo / fetch_fred / fetch_lbma_gold; those
should move here too, but it is deployed and working, so that consolidation is
left as a separate change rather than folded into an unrelated feature.
"""

import math
import random
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# Same public key the other indicator scripts in this repo use.
FRED_API_KEY = "824b29c5afa52f3fc7c6e7dc4925aebb"

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Yahoo rate-limits shared/datacenter IPs (e.g. GitHub Actions runners) with
# HTTP 429, and occasionally gates the chart API behind a cookie with 401. A
# single request is therefore unreliable from CI even when the data is fine, so
# reuse a session and retry across both hosts with exponential backoff.
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
YAHOO_RETRIES = 5


def _warm_yahoo_cookies():
    """Best-effort: grab Yahoo session cookies so the chart API is less likely
    to answer 401 from a shared IP. Never fatal."""
    try:
        SESSION.get("https://finance.yahoo.com", timeout=30)
    except requests.RequestException:
        pass


def _yahoo_chart(symbol):
    """Chart JSON for one symbol, retrying across both Yahoo hosts."""
    path = f"/v8/finance/chart/{urllib.parse.quote(symbol)}"
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
            print(f"    Yahoo {symbol}: attempt {attempt + 1}/{YAHOO_RETRIES} "
                  f"failed ({last_err}); retrying in {backoff:.1f}s")
            time.sleep(backoff)
    raise RuntimeError(f"Yahoo fetch for {symbol} failed after "
                       f"{YAHOO_RETRIES} attempts (last error: {last_err})")


def fetch_yahoo(symbol):
    """Full daily close history -> [(date_str, close)]. Uses epoch arithmetic
    for dates because Windows fromtimestamp() rejects pre-1970 timestamps."""
    result = _yahoo_chart(symbol)["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    out, seen = [], set()
    for ts, c in zip(result["timestamp"], closes):
        if c is None or c <= 0:
            continue
        d = (EPOCH + timedelta(seconds=ts)).strftime("%Y-%m-%d")
        if d in seen:
            continue
        seen.add(d)
        out.append((d, float(c)))
    out.sort()
    return out


def fetch_fred(series_id):
    """A FRED series -> [(date_str, value)], missing prints ('.') dropped."""
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id":         series_id,
                             "api_key":           FRED_API_KEY,
                             "file_type":         "json",
                             "observation_start": "1900-01-01",
                             "sort_order":        "asc"},
                     headers=HEADERS, timeout=120)
    r.raise_for_status()
    return [(o["date"], float(o["value"])) for o in r.json()["observations"]
            if o["value"] not in (".", "")]


def fetch_lbma_gold():
    """LBMA gold PM fix, daily USD/oz -> [(date_str, price)]."""
    r = requests.get("https://prices.lbma.org.uk/json/gold_pm.json",
                     headers=HEADERS, timeout=120)
    r.raise_for_status()
    out = []
    for rec in r.json():                       # records are date-ascending
        v = rec.get("v")
        if v and v[0]:
            out.append((rec["d"][:10], float(v[0])))
    out.sort()
    return out
