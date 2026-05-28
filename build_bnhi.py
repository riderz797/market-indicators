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
    - bitnodes.io snapshots API   — reachable full-node count
    - mempool.space mining API    — pool concentration (top-2 share)

Normalization:
    Each raw metric is smoothed with a 30-day moving average, then
    percentile-ranked against a trailing 4-year (1,460-day) window so
    the index measures health RELATIVE to the network's own baseline —
    not absolute size. Inverted metrics (pool concentration, coin-days-
    destroyed) are flipped so that 100 always means "healthier."

Composite:
    BNHI = weighted sum of 11 normalized 0–100 sub-scores.
    See WEIGHTS below. Bands: 0–25 critical, 25–50 weak,
    50–75 healthy, 75–100 robust.
"""

import json
import os
import sys
import time
from datetime import datetime

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
    "pool_conc":       0.15,   # top-2 pool share (INVERTED)
    "node_count":      0.10,   # reachable full nodes
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
    "Decentralization":     ["pool_conc", "node_count"],
    "Miner Sustainability": ["hashprice", "miner_stress"],
    "Real Usage":           ["active_entities", "settle_vol", "velocity"],
    "Holder Structure":     ["lth_supply"],
}

METRIC_LABELS = {
    "fee_share":       "Fee Share of Revenue",
    "miner_revenue":   "Total Miner Revenue (USD)",
    "hashrate":        "Hashrate",
    "pool_conc":       "Pool Concentration (top-2, inv.)",
    "node_count":      "Reachable Node Count",
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


def get(url, params=None, timeout=90, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as exc:
            if attempt == retries:
                raise
            print(f"    retry {attempt+1}: {exc}", file=sys.stderr)
            time.sleep(2)


# ── Data fetchers ─────────────────────────────────────────────────────────

def blockchain_chart(name):
    """
    Fetch full daily history from blockchain.info charts API.
    Returns a float Series indexed by date (UTC normalized).
    Returns an empty Series (with a warning) on any HTTP error.
    """
    url = "https://api.blockchain.info/charts/" + name
    params = {"timespan": "all", "sampled": "false",
              "format": "json", "cors": "true"}
    try:
        r = get(url, params=params)
    except Exception as exc:
        print(f"  WARNING: blockchain.info/{name} failed ({exc}) — using empty series",
              file=sys.stderr)
        return pd.Series(dtype=float, name=name)

    values = r.json().get("values", [])
    rows = {}
    for v in values:
        if v.get("y") is None:
            continue
        ts = pd.Timestamp(v["x"], unit="s").normalize()
        rows[ts] = float(v["y"])
    if not rows:
        print(f"  WARNING: blockchain.info/{name} returned no data", file=sys.stderr)
        return pd.Series(dtype=float, name=name)
    s = pd.Series(rows, name=name).sort_index()
    return s[~s.index.duplicated(keep="last")]


def fetch_btc_price():
    """BTC/USD daily close from blockchain.info market-price chart."""
    return blockchain_chart("market-price")


def fetch_node_count():
    """
    bitnodes.io /api/v1/snapshots/ — paginated list of network snapshots.
    Returns daily-resampled total_nodes series.
    """
    results = {}
    url = "https://bitnodes.io/api/v1/snapshots/"
    params = {"limit": 100, "page": 1}
    for _ in range(60):   # cap: 60 pages × 100 = 6 000 records ≈ 16 years daily
        r = get(url, params=params, timeout=30)
        data = r.json()
        for snap in data.get("results", []):
            ts = pd.Timestamp(snap["timestamp"], unit="s").normalize()
            n = snap.get("total_nodes") or 0
            if n > 0:
                results[ts] = float(n)
        if not data.get("next"):
            break
        params["page"] += 1

    if not results:
        return pd.Series(dtype=float, name="node_count")
    s = pd.Series(results, name="node_count").sort_index()
    # Multiple snapshots per day → keep max (most complete count)
    return s.groupby(s.index).max()


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
            r = get(url, timeout=30, retries=1)
            data = r.json()
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
        return pd.Series(dtype=float, name="pool_conc")

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

def main():
    print("=== Building Acumen BNHI ===", file=sys.stderr)

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

    print("  bitnodes.io: node count ...", file=sys.stderr)
    try:
        nodes = fetch_node_count()
        print(f"    {len(nodes)} snapshots", file=sys.stderr)
    except Exception as exc:
        print(f"  WARNING: bitnodes.io failed ({exc}) — using empty series", file=sys.stderr)
        nodes = pd.Series(dtype=float, name="node_count")

    print("  mempool.space: pool concentration ...", file=sys.stderr)
    try:
        pool_conc = fetch_pool_concentration()
        print(f"    {len(pool_conc)} daily data points", file=sys.stderr)
    except Exception as exc:
        print(f"  WARNING: mempool.space failed ({exc}) — using empty series", file=sys.stderr)
        pool_conc = pd.Series(dtype=float, name="pool_conc")

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
        "node_count":       align(nodes),
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

    # 6. BNHI composite (weights already sum to 1.0)
    bnhi = pd.Series(0.0, index=idx)
    for m, w in WEIGHTS.items():
        bnhi += normalized[m].fillna(50.0) * w

    # 7. Category sub-scores
    cat_scores: dict[str, pd.Series] = {}
    for cat, mlist in CATEGORY_METRICS.items():
        cat_w = sum(WEIGHTS[m] for m in mlist)
        cat_s = sum(normalized[m].fillna(50.0) * WEIGHTS[m] for m in mlist)
        cat_scores[cat] = cat_s / cat_w

    # 8. Build current-reading summary
    last_bnhi = float(bnhi.iloc[-1])
    current = {
        "date":       idx[-1].strftime("%Y-%m-%d"),
        "bnhi":       round(last_bnhi, 1),
        "band":       band(last_bnhi),
        "categories": {
            cat: round(float(s.iloc[-1]), 1)
            for cat, s in cat_scores.items()
        },
        "metrics": {
            m: round(float(normalized[m].iloc[-1]), 1)
            for m in metrics
        },
    }

    # 9. Serialize to JS
    date_strs = [d.strftime("%Y-%m-%d") for d in idx]

    out: dict = {
        "generated":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        + datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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
        print(f"  {cat:<26} {val:5.1f}   (weight {w_pct:.0f}%)", file=sys.stderr)


if __name__ == "__main__":
    main()
