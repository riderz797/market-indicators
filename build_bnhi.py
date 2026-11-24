"""
ACUMEN BITCOIN NETWORK HEALTH INDEX (BNHI)
==========================================
Composite 0–100 score measuring Bitcoin network fundamentals —
security budget, decentralization, miner sustainability, real usage,
and holder structure.

Usage:
    python build_bnhi.py

Writes: indicators/btc/bnhi_baked.js

Data sources (all free, no API keys required):
    - blockchain.info charts API  — mining revenue, hashrate, on-chain activity
    - mempool.space mining API    — pool concentration (top-2 share)

Normalization:
    Each raw metric is smoothed with a 30-day moving average, then
    percentile-ranked against a trailing 4-year (1,460-day) window so
    the index measures health RELATIVE to the network's own baseline —
    not absolute size. Inverted metrics (pool concentration, coin-days-
    destroyed) are flipped so that 100 always means "healthier."

Composite:
    BNHI = weighted sum of 10 normalized 0–100 sub-scores.
    See WEIGHTS below. Bands: 0–25 critical, 25–50 weak,
    50–75 healthy, 75–100 robust.

    Any metric with no score on a given day (e.g. still in its percentile
    warm-up) is *dropped* and the remaining weights are renormalized — a
    missing metric never silently injects a neutral 50 that would distort
    the composite.

Source outages:
    Every source is required.  If one can't be fetched after retries, the
    previous bnhi_baked.js is left untouched (rebuilding the whole history
    without a metric would quietly change the index).  The run exits 0 with
    a warning while the baked data is <= STALE_AFTER_DAYS old, so one bad
    weekly run doesn't send a failure email; after that it exits 1.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(BASE, "indicators", "btc", "bnhi_baked.js")

# ── Configuration ─────────────────────────────────────────────────────────

MA_DAYS      = 30      # smoothing window applied to each raw series
WINDOW_DAYS  = 1460    # trailing window (days) for percentile ranking
MIN_PERIODS  = 180     # min days of history before ranking starts
START_DATE   = "2017-01-01"

WEIGHTS = {
    # Security Budget — 35%
    "fee_share":       0.15,   # fees / (fees + block reward)
    "miner_revenue":   0.10,   # total miner revenue in USD
    "hashrate":        0.10,   # 30d average hashrate
    # Decentralization — 25%
    "pool_conc":       0.25,   # top-2 pool share (INVERTED)
    # Miner Sustainability — 15%
    "hashprice":       0.10,   # revenue per TH/s/day
    "miner_stress":    0.05,   # 30d hashprice momentum (higher = less stress)
    # Real Usage — 20%
    "active_entities": 0.08,   # daily unique active addresses (proxy)
    "settle_vol":      0.07,   # estimated on-chain settlement volume USD
    "velocity":        0.05,   # settle_vol / market_cap
    # Holder Structure — 5%
    "lth_supply":      0.05,   # n-transactions INVERTED (fewer txns = more HODLing)
}

# Higher raw value = worse health → percentile is flipped to 100 - pct
INVERTED = {"pool_conc", "lth_supply"}

CATEGORY_METRICS = {
    "Security Budget":      ["fee_share", "miner_revenue", "hashrate"],
    "Decentralization":     ["pool_conc"],
    "Miner Sustainability": ["hashprice", "miner_stress"],
    "Real Usage":           ["active_entities", "settle_vol", "velocity"],
    "Holder Structure":     ["lth_supply"],
}

METRIC_LABELS = {
    "fee_share":       "Fee Share of Revenue",
    "miner_revenue":   "Total Miner Revenue (USD)",
    "hashrate":        "Hashrate",
    "pool_conc":       "Pool Concentration (top-2, inv.)",
    "hashprice":       "Hashprice (rev/TH/s/day)",
    "miner_stress":    "Miner Stress Signal (inv.)",
    "active_entities": "Active Addresses (proxy)",
    "settle_vol":      "Settlement Volume (USD)",
    "velocity":        "On-chain Velocity",
    "lth_supply":      "LTH Proxy (tx count inv.)",
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"


# ── HTTP helpers ─────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AcumenBNHI/1.0)"}

# requests' `timeout` only limits the silence between chunks, so a server
# trickling bytes can stall a download indefinitely (the 2026-11-23 CI run
# hung for 65 minutes).  Each attempt therefore also gets a hard deadline.
# market-cap is the big one: ~34 MB, ~10 s on a normal connection.
CONNECT_TIMEOUT = 20          # seconds to open the connection
READ_TIMEOUT    = 60          # max seconds of silence mid-download
DEADLINE        = 180         # max seconds for one whole download
RETRY_WAITS     = (15, 60)    # pauses between attempts → 3 attempts

STALE_AFTER_DAYS = 10         # tolerate one missed weekly run, then fail


class FetchError(RuntimeError):
    """A required data source could not be fetched."""


def get_json(url, params=None, waits=RETRY_WAITS):
    """GET `url` and parse the JSON body, retrying transient failures.

    Client errors (4xx other than 408/429) are not retried — they won't fix
    themselves.  Raises FetchError once attempts are exhausted.
    """
    last = None
    for attempt in range(len(waits) + 1):
        if attempt:
            print(f"    retry {attempt} in {waits[attempt-1]}s ({last})", file=sys.stderr)
            time.sleep(waits[attempt - 1])
        try:
            start = time.monotonic()
            with requests.get(url, params=params, headers=HEADERS, stream=True,
                              timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)) as r:
                r.raise_for_status()
                body = bytearray()
                for chunk in r.iter_content(chunk_size=1 << 16):
                    body.extend(chunk)
                    if time.monotonic() - start > DEADLINE:
                        raise TimeoutError(f"download passed {DEADLINE}s "
                                           f"({len(body) / 1e6:.1f} MB so far)")
            return json.loads(body)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code is not None and 400 <= code < 500 and code not in (408, 429):
                raise FetchError(f"{url}: {exc}") from exc
            last = exc
        except (requests.RequestException, TimeoutError, ValueError) as exc:
            last = exc     # ValueError covers a truncated / non-JSON body
    raise FetchError(f"{url}: {last}")


# ── Data fetchers ─────────────────────────────────────────────────────────

def blockchain_chart(name):
    """
    Fetch full daily history from blockchain.info charts API.
    Returns a float Series indexed by date (UTC normalized).
    Raises FetchError if the source is unreachable or returns no data.
    """
    url = "https://api.blockchain.info/charts/" + name
    params = {"timespan": "all", "sampled": "false",
              "format": "json", "cors": "true"}
    data = get_json(url, params=params)

    values = data.get("values", []) if isinstance(data, dict) else []
    rows = {}
    for v in values:
        if v.get("y") is None:
            continue
        ts = pd.Timestamp(v["x"], unit="s").normalize()
        rows[ts] = float(v["y"])
    if not rows:
        raise FetchError(f"blockchain.info/{name} returned no data")
    s = pd.Series(rows, name=name).sort_index()
    return s[~s.index.duplicated(keep="last")]


def fetch_btc_price():
    """BTC/USD daily close from blockchain.info market-price chart."""
    return blockchain_chart("market-price")


def fetch_pool_concentration():
    """
    mempool.space /api/v1/mining/pool/{slug}/hashrate — daily hashrate share.
    Fetches history for the consistently dominant pools, sums top-2 share
    per day.  Returns a daily series of combined top-2 share (0.0–1.0).
    """
    # These five pools have held top-2 at different points in recent history.
    # We fetch all of them and dynamically pick the top-2 each day.
    slugs = ["foundryusa", "antpool", "viabtc", "f2pool", "marapool",
             "binancepool", "luxor", "btccom"]
    daily_shares: dict[pd.Timestamp, list[float]] = {}
    fetched = 0
    for slug in slugs:
        url = f"https://mempool.space/api/v1/mining/pool/{slug}/hashrate"
        try:
            data = get_json(url, waits=(10,))
            # API returns a bare list of {timestamp, avgHashrate, share, poolName}
            items = data if isinstance(data, list) else data.get("hashrates", [])
            for pt in items:
                ts = pd.Timestamp(pt["timestamp"], unit="s").normalize()
                share = float(pt.get("share") or 0)
                if share > 0:
                    daily_shares.setdefault(ts, []).append(share)
            fetched += 1
        except Exception as exc:
            print(f"    pool/{slug}: {exc}", file=sys.stderr)

    if not daily_shares or fetched == 0:
        raise FetchError("mempool.space: no pool hashrate history fetched")

    result = {}
    for ts, shares in daily_shares.items():
        top2 = sum(sorted(shares, reverse=True)[:2])
        result[ts] = min(top2, 1.0)   # cap at 100 % (data artefacts)

    s = pd.Series(result, name="pool_conc").sort_index()
    return s[s > 0]


# ── Normalization ─────────────────────────────────────────────────────────

def rolling_percentile(series: pd.Series, window=WINDOW_DAYS,
                       min_periods=MIN_PERIODS) -> pd.Series:
    """
    For each date t: percentile rank of series[t] within the trailing
    `window` calendar days of values.  Uses a mid-point tie rule.
    Returns a 0–100 Series aligned to series.index.
    """
    def _pct(arr: np.ndarray) -> float:
        if len(arr) < 2:
            return 50.0
        below = np.sum(arr[:-1] < arr[-1])
        equal = np.sum(arr[:-1] == arr[-1])
        return (below + 0.5 * equal) / (len(arr) - 1) * 100.0

    return series.rolling(window=window, min_periods=min_periods).apply(
        _pct, raw=True
    )


# ── Helpers ───────────────────────────────────────────────────────────────

def band(score: float) -> str:
    if score < 25:  return "CRITICAL"
    if score < 50:  return "WEAK"
    if score < 75:  return "HEALTHY"
    return "ROBUST"


def to_list(s: pd.Series, dec: int = 1) -> list:
    return [round(float(v), dec) if pd.notna(v) else None for v in s]


# ── Main pipeline ─────────────────────────────────────────────────────────

def previous_baked_through():
    """Date the existing bnhi_baked.js runs through, or None if unreadable."""
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            head = f.read(500)
    except OSError:
        return None
    m = re.search(r'"baked_through":"(\d{4}-\d{2}-\d{2})"', head)
    return pd.Timestamp(m.group(1)) if m else None


def main():
    print("=== Building Acumen BNHI ===", file=sys.stderr)
    try:
        build()
    except FetchError as exc:
        prev = previous_baked_through()
        age = (pd.Timestamp.today().normalize() - prev).days if prev is not None else None
        kept = (f"keeping data baked through {prev.date()} ({age} days old)"
                if prev is not None else "no previous data found")
        # ::warning:: / ::error:: lines become annotations on the Actions run
        if age is not None and age <= STALE_AFTER_DAYS:
            print(f"::warning::BNHI not refreshed, {kept}. Source down: {exc}")
            return 0
        print(f"::error::BNHI not refreshed, {kept}. Source down: {exc}")
        return 1
    return 0


def build():
    # 1. Fetch raw data
    print("  blockchain.info: miners-revenue ...", file=sys.stderr)
    miners_rev = blockchain_chart("miners-revenue")       # USD/day

    print("  blockchain.info: transaction-fees-usd ...", file=sys.stderr)
    fees_usd   = blockchain_chart("transaction-fees-usd") # USD/day

    print("  blockchain.info: hash-rate ...", file=sys.stderr)
    hashrate   = blockchain_chart("hash-rate")            # TH/s

    print("  blockchain.info: n-unique-addresses ...", file=sys.stderr)
    active_addr = blockchain_chart("n-unique-addresses")

    print("  blockchain.info: estimated-transaction-volume-usd ...", file=sys.stderr)
    settle_vol  = blockchain_chart("estimated-transaction-volume-usd")

    print("  blockchain.info: market-cap ...", file=sys.stderr)
    market_cap  = blockchain_chart("market-cap")          # USD

    print("  blockchain.info: n-transactions (LTH proxy) ...", file=sys.stderr)
    cdd         = blockchain_chart("n-transactions")   # inverted: fewer txns = more HODLing

    print("  blockchain.info: market-price (BTC/USD) ...", file=sys.stderr)
    btc_price   = fetch_btc_price()

    print("  mempool.space: pool concentration ...", file=sys.stderr)
    pool_conc = fetch_pool_concentration()
    print(f"    {len(pool_conc)} daily data points", file=sys.stderr)

    # 2. Derived pre-smoothing series
    fee_share = (fees_usd / miners_rev.clip(lower=1.0)).clip(0.0, 1.0)
    hashprice = miners_rev / hashrate.clip(lower=1.0)    # USD / (TH/s · day)
    velocity  = (settle_vol / market_cap.clip(lower=1.0)).clip(lower=0.0)

    # 3. Align everything to a clean daily index
    idx = pd.date_range(START_DATE,
                        pd.Timestamp.today().normalize() - pd.Timedelta(days=1),
                        freq="D")

    def align(s):
        return s.reindex(idx).ffill().bfill()

    raw = pd.DataFrame({
        "fee_share":        align(fee_share),
        "miner_revenue":    align(miners_rev),
        "hashrate":         align(hashrate),
        "pool_conc":        align(pool_conc),
        "hashprice":        align(hashprice),
        "active_entities":  align(active_addr),
        "settle_vol":       align(settle_vol),
        "velocity":         align(velocity),
        "lth_supply":       align(cdd),
        # for output
        "_btc_price":       align(btc_price),
    })

    # 4. Apply 30-day smoothing to all raw series
    smoothed = raw.rolling(MA_DAYS, min_periods=1).mean()

    # Miner stress = 30d pct change in smoothed hashprice.
    # POSITIVE momentum → miners are more profitable → less forced selling.
    hp = smoothed["hashprice"]
    hp_lag = hp.shift(30)
    miner_stress = ((hp - hp_lag) / hp_lag.clip(lower=1e-9)).clip(-1.0, 5.0)
    smoothed["miner_stress"] = miner_stress

    # 5. Percentile-rank each metric
    metrics = list(WEIGHTS.keys())
    normalized = pd.DataFrame(index=idx)
    for m in metrics:
        pct = rolling_percentile(smoothed[m])
        normalized[m] = 100.0 - pct if m in INVERTED else pct

    # 6. BNHI composite + category sub-scores.
    #    For each date, take the weighted average of the metrics that
    #    actually have data, renormalizing by the weight of the metrics
    #    present.  A metric whose source is missing (all-NaN) or still in
    #    its percentile warm-up drops out instead of silently injecting a
    #    neutral 50 that would distort the score toward the midpoint.
    def weighted_score(mlist):
        num = pd.Series(0.0, index=idx)
        den = pd.Series(0.0, index=idx)
        for m in mlist:
            w = WEIGHTS[m]
            avail = normalized[m].notna()
            num = num.add(normalized[m].where(avail, 0.0) * w, fill_value=0.0)
            den = den.add(avail.astype(float) * w, fill_value=0.0)
        return num / den.where(den > 0)

    bnhi = weighted_score(metrics)

    # 7. Category sub-scores
    cat_scores: dict[str, pd.Series] = {
        cat: weighted_score(mlist) for cat, mlist in CATEGORY_METRICS.items()
    }

    # 8. Build current-reading summary
    def safe_round(x, dec=1):
        return round(float(x), dec) if pd.notna(x) else None

    last_bnhi = float(bnhi.iloc[-1])
    current = {
        "date":       idx[-1].strftime("%Y-%m-%d"),
        "bnhi":       round(last_bnhi, 1),
        "band":       band(last_bnhi),
        "categories": {
            cat: safe_round(s.iloc[-1])
            for cat, s in cat_scores.items()
        },
        "metrics": {
            m: safe_round(normalized[m].iloc[-1])
            for m in metrics
        },
    }

    # 9. Serialize to JS
    date_strs = [d.strftime("%Y-%m-%d") for d in idx]

    out: dict = {
        "generated":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baked_through": date_strs[-1],
        "dates":       date_strs,
        "bnhi":        to_list(bnhi),
        "btc_price":   to_list(smoothed["_btc_price"], dec=0),
        "current":     current,
        "weights":     {k: round(v, 4) for k, v in WEIGHTS.items()},
        "metric_labels": METRIC_LABELS,
        "categories_config": CATEGORY_METRICS,
        "inverted":    sorted(INVERTED),
    }
    for m in metrics:
        out[m] = to_list(normalized[m])
    for cat, s in cat_scores.items():
        key = "cat_" + cat.lower().replace(" ", "_")
        out[key] = to_list(s)

    js = (
        "// Auto-generated by build_bnhi.py — "
        + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        + "\nconst BNHI_DATA = "
        + json.dumps(out, separators=(",", ":"))
        + ";\n"
    )

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(js)

    kb = len(js) / 1024
    print(f"\nWrote {OUTPUT}", file=sys.stderr)
    print(f"  {len(date_strs)} days ({date_strs[0]} → {date_strs[-1]}), {kb:.0f} KB",
          file=sys.stderr)
    print(f"\nBNHI {date_strs[-1]}: {last_bnhi:.1f}  [{current['band']}]",
          file=sys.stderr)
    for cat, val in current["categories"].items():
        w_pct = sum(WEIGHTS[m] for m in CATEGORY_METRICS[cat]) * 100
        shown = f"{val:5.1f}" if val is not None else "  n/a"
        print(f"  {cat:<26} {shown}   (weight {w_pct:.0f}%)", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
