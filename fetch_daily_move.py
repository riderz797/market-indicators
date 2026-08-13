"""
fetch_daily_move.py
Bakes data for the Daily Move in Historical Distribution indicator.

For each of eight assets, fetches the full daily price history, computes
every daily move, bins them into a histogram, and injects the binned
distribution plus summary stats into daily_move_distribution.html.
The page only renders — all math lives here.

Sources (all free, no registration beyond the shared FRED key):
  1. Yahoo ^GSPC    — S&P 500 daily closes since Dec 1927, % change
  2. LBMA gold PM   — gold fix USD/oz since 1968; trimmed to Aug 1971
                      (the end of the fixed $35 gold window), % change.
                      The fix is a single 3pm London auction print, so a
                      fix-to-fix change is not the close-to-close change any
                      gold chart shows. The CURRENT move therefore comes from
                      COMEX futures (Yahoo GC=F) whenever those are at least
                      as fresh as the fix — which is every trading day.
  3. FRED DCOILBRENTEU — Brent crude spot USD/bbl since May 1987, % change.
                      Spot publishes a few days behind, so the CURRENT move
                      comes from Brent futures (Yahoo BZ=F) — the same
                      arrangement gold uses.
  4. Yahoo DX-Y.NYB — ICE US Dollar Index since 1971, % change
  5. Yahoo BTC-USD  — Bitcoin since Sep 2014, % change
  6. Yahoo ^TNX     — CBOE 10-year Treasury yield since 1962,
                      move measured in basis points (1 bp = 0.01%)
  7. FRED T10Y2Y    — 10-year minus 2-year Treasury spread since Jun 1976,
                      move measured in basis points
  8. MOVE index     — ICE BofA bond-market volatility, % change. Merged from
                      two feeds: Yahoo ^MOVE reaches back to Nov 2002 but
                      forward-fills holidays and has stopped publishing daily
                      bars entirely; Barchart $MOVE is current but only spans
                      the last 5000 sessions. Barchart wins where they overlap
                      (spot-checked against Yahoo's stale prints), Yahoo
                      supplies the pre-2006 history, and either source alone
                      is enough to bake.

Run:  python fetch_daily_move.py
Requires: requests  (pip install requests)
"""

import requests
import json
import math
import os
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

# Asset names carry typographic characters (the spread's U+2212 minus), which a
# default Windows console encodes as cp1252 and dies on. CI already runs UTF-8.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── CONFIG ─────────────────────────────────────────────────────────────────────
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "indicators", "macro", "daily_move_distribution.html")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# Same public key the other indicator scripts in this repo use.
FRED_API_KEY = "824b29c5afa52f3fc7c6e7dc4925aebb"

N_BINS      = 90    # histogram bins across mean ± 4.5 sd (bin width = sd/10)
BIN_SPAN_SD = 4.5
MAX_GAP_DAYS = 7    # don't compute a "daily" move across a longer gap

# Sanity floors: refuse to bake if a source comes back suspiciously short
# (protects against silent API degradation shrinking the distribution).
# MOVE's floor sits below the ~5000 sessions Barchart alone returns, so losing
# either of its two feeds degrades the history rather than failing the bake.
MIN_MOVES = {"spx": 20000, "gold": 11000, "brent": 9000, "dxy": 11000,
             "btc": 3500, "ust10y": 13000, "t10y2y": 11500, "move": 4500}


# ── FETCHERS ───────────────────────────────────────────────────────────────────
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
    """Best-effort: grab Yahoo session cookies so the chart API is less likely
    to answer 401 from a shared IP. Never fatal."""
    try:
        SESSION.get("https://finance.yahoo.com", timeout=30)
    except requests.RequestException:
        pass


def _yahoo_chart(symbol):
    """Fetch the chart JSON for one symbol, retrying across both Yahoo hosts
    with exponential backoff. Raises only after every attempt is exhausted."""
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
    """Full daily history -> [(date_str, close)]. Uses epoch arithmetic for
    dates because Windows fromtimestamp() rejects pre-1970 timestamps."""
    result = _yahoo_chart(symbol)["chart"]["result"][0]
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


def _with_retry(label, call, retries=4):
    """Retry a single-endpoint fetch with exponential backoff. Yahoo has its own
    retry loop across two hosts; LBMA, FRED and Barchart each have exactly one
    endpoint, so without this a lone timeout or 5xx takes the whole bake down."""
    last_err = None
    for attempt in range(retries):
        try:
            return call()
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < retries - 1:
            backoff = 2 ** attempt + random.uniform(0, 1)
            print(f"  {label}: attempt {attempt + 1}/{retries} failed "
                  f"({last_err}); retrying in {backoff:.1f}s")
            time.sleep(backoff)
    raise RuntimeError(f"{label} failed after {retries} attempts "
                       f"(last error: {last_err})")


def fetch_lbma_gold():
    """LBMA gold PM fix, daily USD/oz -> [(date_str, price)]."""
    url = "https://prices.lbma.org.uk/json/gold_pm.json"

    def call():
        r = requests.get(url, headers=HEADERS, timeout=120)
        r.raise_for_status()
        return r.json()

    out = []
    for rec in _with_retry("LBMA gold PM", call):   # records are date-ascending
        v = rec.get("v")
        if v and v[0]:
            out.append((rec["d"][:10], float(v[0])))
    return out


def fetch_fred(series_id):
    """A daily FRED series -> [(date_str, value)], missing prints ('.') dropped."""
    def call():
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id":         series_id,
                                 "api_key":           FRED_API_KEY,
                                 "file_type":         "json",
                                 "observation_start": "1900-01-01",
                                 "sort_order":        "asc"},
                         headers=HEADERS, timeout=120)
        r.raise_for_status()
        return r.json()["observations"]

    return [(o["date"], float(o["value"])) for o in _with_retry(f"FRED {series_id}", call)
            if o["value"] not in (".", "")]


def fetch_barchart_move():
    """Barchart's end-of-day $MOVE series -> [(date_str, close)].

    Barchart gates its data proxy behind an XSRF cookie handed out by the quote
    page, so load that first and echo the token back. Capped at 5000 sessions
    on their side, which currently reaches back to May 2006."""
    quote_page = "https://www.barchart.com/stocks/quotes/%24MOVE/interactive-chart"

    def call():
        s = requests.Session()                 # fresh session: the token is per-session
        s.headers.update(HEADERS)
        s.get(quote_page, timeout=60)
        token = urllib.parse.unquote(s.cookies.get("XSRF-TOKEN", ""))
        if not token:
            raise RuntimeError("Barchart handed back no XSRF-TOKEN cookie")
        r = s.get("https://www.barchart.com/proxies/timeseries/queryeod.ashx",
                  params={"symbol": "$MOVE", "data": "daily",
                          "maxrecords": "10000", "order": "asc"},
                  headers={"x-xsrf-token": token, "Referer": quote_page},
                  timeout=120)
        r.raise_for_status()
        return r.text

    out = []
    for line in _with_retry("Barchart $MOVE", call).strip().splitlines():
        parts = line.split(",")                # symbol,date,open,high,low,close,volume
        if len(parts) >= 6 and parts[5]:
            out.append((parts[1], float(parts[5])))
    out.sort()
    return out


def fetch_move():
    """MOVE index daily closes -> [(date_str, close)], merged across two feeds.

    Yahoo carries the deeper history but forward-fills bond-market holidays
    (2023-06-20 repeats 06-16 across Juneteenth) and its daily bars have been
    null since mid-2026; Barchart is accurate and current but shallower. So
    Barchart wins every date the two share, and Yahoo backfills the rest.
    Tolerates either feed being down — whatever survives still gets baked."""
    merged, sources = {}, []
    for label, fetch in (("Yahoo ^MOVE", lambda: fetch_yahoo("^MOVE")),
                         ("Barchart $MOVE", fetch_barchart_move)):
        try:
            series = fetch()                   # later source overwrites earlier
            merged.update(dict(series))
            sources.append(f"{label} ({len(series)})")
        except Exception as e:
            print(f"  WARNING: {label} unavailable ({type(e).__name__}: {e})")
    if not merged:
        raise RuntimeError("Both MOVE feeds failed")
    print(f"  MOVE sources: {', '.join(sources)}")
    return sorted(merged.items())


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


def quantum(vals):
    """The smallest step every value is a multiple of — i.e. the precision the
    source publishes at. Series quoted at full float precision bottom out at the
    1e-6 floor, which is the 'no meaningful quantization' answer."""
    g = 0
    for v in vals:
        g = math.gcd(g, int(round(abs(v) * 1e6)))
        if g == 1:
            break
    return g / 1e6


def histogram(vals, mean, sd):
    """Bin the moves across mean ± BIN_SPAN_SD·sd -> (bin_lo, bin_w, counts,
    below, above).

    Normally that is N_BINS equal bins. But a source quantized coarser than one
    bin needs wider ones: FRED publishes the 10y-2y spread to two decimals, so
    every move is a whole number of basis points, and bins narrower than 1 bp
    are structurally unfillable — over half of them would come back empty and
    comb the chart into a picket fence. In that case widen the bins to the data's
    own step and centre them on it, so each bin holds exactly one real value."""
    lo = mean - BIN_SPAN_SD * sd
    hi = mean + BIN_SPAN_SD * sd
    w = (hi - lo) / N_BINS
    q = quantum(vals)
    if q > w:
        w = q
        lo = math.floor((lo + q / 2) / w) * w - q / 2   # grid points at bin centres
        n = int(math.ceil((hi - lo) / w))
    else:
        n = N_BINS

    counts, below, above = [0] * n, 0, 0
    for v in vals:
        if v < lo:
            below += 1
            continue
        i = int((v - lo) / w)
        if i >= n:
            above += 1
        else:
            counts[i] += 1
    return lo, w, counts, below, above


def build_asset(spec, series, cur_override=None):
    moves = compute_moves(series, spec["kind"], spec["max_abs"])
    n = len(moves)
    if n < MIN_MOVES[spec["id"]]:
        raise RuntimeError(f"produced only {n} moves (< {MIN_MOVES[spec['id']]}) "
                           f"— refusing to bake degraded data")

    vals = [m for _, m in moves]
    mean = sum(vals) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)

    cur_d, cur_v = moves[-1]
    # Gold and Brent build their distribution from one feed (the LBMA fix, Brent
    # spot) but quote today's move from another (COMEX / ICE futures), so the
    # headline number matches the chart everyone else is looking at. The test has
    # to be >=, not >: the LBMA fix publishes mid-afternoon London, so by the
    # 22:30 UTC bake it already carries the same date as the futures close, and a
    # strict > would fall back to a 3pm-fix-to-3pm-fix change every single day.
    if cur_override and cur_override[0] >= cur_d:
        cur_d, cur_v = cur_override          # live quote from the matching feed
    rec_min = min(moves, key=lambda t: t[1])
    rec_max = max(moves, key=lambda t: t[1])

    bin_lo, bin_w, counts, below, above = histogram(vals, mean, sd)

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
# Order here is the order the boards appear on the page: risk assets, then
# commodities and the dollar, then the rates block (level, curve, volatility).
# max_abs is a bad-tick guard, so each is set clear of that series' genuine
# extremes — Brent really did move ±50% in April 2020, and the 10y-2y spread
# really did swing ±55 bp under Volcker.
SPECS = [
    {"id": "spx",    "name": "S&P 500",  "kind": "pct", "max_abs": 30,
     "sub": "% change vs prior close", "fetch": lambda: fetch_yahoo("^GSPC")},
    {"id": "gold",   "name": "Gold",     "kind": "pct", "max_abs": 30,
     "sub": "% change vs prior close",
     "fetch": lambda: [(d, v) for d, v in fetch_lbma_gold() if d >= "1971-08-16"],
     "live":  lambda: fetch_yahoo("GC=F")},
    {"id": "brent",  "name": "Oil (Brent Crude)", "kind": "pct", "max_abs": 60,
     "sub": "% change vs prior close",
     "fetch": lambda: fetch_fred("DCOILBRENTEU"),
     "live":  lambda: fetch_yahoo("BZ=F")},
    {"id": "dxy",    "name": "DXY (US Dollar Index)", "kind": "pct", "max_abs": 30,
     "sub": "% change vs prior close", "fetch": lambda: fetch_yahoo("DX-Y.NYB")},
    {"id": "btc",    "name": "Bitcoin",  "kind": "pct", "max_abs": 60,
     "sub": "% change vs prior close", "fetch": lambda: fetch_yahoo("BTC-USD")},
    {"id": "ust10y", "name": "US 10YR Yield", "kind": "bp", "max_abs": 150,
     "sub": "basis-point change vs prior close", "fetch": lambda: fetch_yahoo_tnx()},
    {"id": "t10y2y", "name": "US 10YR − 2YR Spread", "kind": "bp", "max_abs": 100,
     "sub": "basis-point change vs prior close",
     "fetch": lambda: fetch_fred("T10Y2Y")},
    {"id": "move",   "name": "MOVE Index (Bond Volatility)", "kind": "pct", "max_abs": 80,
     "sub": "% change vs prior close", "fetch": fetch_move},
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


def load_previous_assets(html):
    """The entries baked by the previous run, keyed by id. These are the fallback
    when a source is down: one dead feed should cost that board its refresh, not
    freeze the other seven."""
    block = re.search(r"// @@BAKED_DATA_START@@([\s\S]*?)// @@BAKED_DATA_END@@", html)
    if not block:
        return {}
    # Greedy inside the marked block is safe — the only "];" there closes the array.
    m = re.search(r"const DMHD_ASSETS\s*=\s*(\[[\s\S]*\]);", block.group(1))
    if not m:
        return {}
    try:
        return {a["id"]: a for a in json.loads(m.group(1))}
    except (ValueError, KeyError, TypeError):
        return {}


with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

previous = load_previous_assets(html)

assets, stale = [], []
for spec in SPECS:
    print(f"Fetching {spec['name']}...")
    try:
        series = spec["fetch"]()
        cur_override = None
        if "live" in spec:
            # A dead live feed only costs this board its matching-feed quote;
            # the history feed still carries a (staler, different-source) move.
            try:
                live_moves = compute_moves(spec["live"](), spec["kind"], spec["max_abs"])
                if live_moves:
                    cur_override = live_moves[-1]
            except Exception as e:
                print(f"  WARNING: live quote unavailable ({type(e).__name__}: {e}) "
                      f"— falling back to the history feed")
        a = build_asset(spec, series, cur_override)
    except Exception as e:
        prev = previous.get(spec["id"])
        if prev is None:
            raise SystemExit(f"ERROR: {spec['name']} failed ({type(e).__name__}: {e}) "
                             f"with no previously baked data to fall back on.")
        print(f"  WARNING: {spec['name']} failed ({type(e).__name__}: {e}) "
              f"— keeping the last baked values (through {prev['cur']['d']})")
        assets.append(prev)
        stale.append(f"{spec['name']} (through {prev['cur']['d']})")
        continue
    assets.append(a)
    print(f"  {a['name']:30s}: {a['n']:6d} moves since {a['start']}, "
          f"last {a['cur']['d']} = {a['cur']['v']:+.2f}{a['unit']} "
          f"(z {a['z']:+.2f}, {a['pctile']:.1f} pctile, 1-in-{a['oneIn']})")

if stale:
    print(f"\nWARNING: {len(stale)} of {len(SPECS)} boards kept stale data: "
          f"{', '.join(stale)}")

# ── INJECT INTO HTML ───────────────────────────────────────────────────────────

today = datetime.now().strftime("%Y-%m-%d")
baked_block = (
    f"    const DMHD_ASSETS   = {json.dumps(assets)};\n"
    f"    const DMHD_BAKED_ON = \"{today}\"; // injected by fetch_daily_move.py"
)

pattern = r"(// @@BAKED_DATA_START@@)[\s\S]*?(// @@BAKED_DATA_END@@)"
# Replace via a function, not a template string: the baked JSON contains
# backslash escapes (− in the spread's name) that re would otherwise try
# to interpret as replacement-group syntax and reject.
new_html, count = re.subn(
    pattern, lambda m: m.group(1) + "\n" + baked_block + "\n    " + m.group(2), html)

if count == 0:
    print("ERROR: Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers.")
    raise SystemExit(1)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(new_html)

print(f"Injected {len(assets)} assets into {HTML_PATH}")
print("Done.")
