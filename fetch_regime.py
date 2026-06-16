#!/usr/bin/env python3
"""
fetch_regime.py — 42 Macro "Darius Dale" Regime Compass data builder.

Reverse-engineers the two regime engines in the 42 Macro deck:

  1. Fundamental GRID (deck pp. 34 / 73)  -> sets the HEADLINE regime quadrant.
     Growth    = composite of US coincident indicators (the official NBER-style
                 four: payrolls, real income ex-transfers, industrial production,
                 real mfg+trade sales) plus real retail sales.
     Inflation = Core PCE + Core CPI.
     Each series is scored as a 50/50 blend of (a) level vs its trailing 5yr
     norm and (b) 6-month rate-of-change (acceleration), z-scored. The signs of
     the growth and inflation composites pick the quadrant:
         growth+ / inflation-  = GOLDILOCKS
         growth+ / inflation+  = REFLATION
         growth- / inflation+  = INFLATION
         growth- / inflation-  = DEFLATION

  2. Global Macro Risk Matrix (deck pp. 52-55) -> fills the "share of confirming
     markets" bars + strength-of-signal. A basket of ~16 liquid markets each
     vote: a market "confirms" a regime when its current momentum sign matches
     how that market is expected to trade in the regime (deck p. 40 playbook).

Output: indicators/macro/regime_data.json  (read by darius_dale_regime.html).
Pure stdlib + requests, so the GitHub Action only needs `pip install requests`.
"""

import os, sys, json, time, statistics, datetime
import requests

FRED_KEY = os.environ.get("FRED_API_KEY", "")   # set via env var / GitHub Actions secret
OUT_PATH = os.path.join("indicators", "macro", "regime_data.json")
REGIMES  = ["GOLDILOCKS", "REFLATION", "INFLATION", "DEFLATION"]

# ── Fundamental inputs (FRED, monthly) ──────────────────────────────────────
GROWTH_SERIES = {
    "PAYEMS":   "Nonfarm Payrolls",
    "W875RX1":  "Real Income ex-Transfers",
    "INDPRO":   "Industrial Production",
    "CMRMTSPL": "Real Mfg & Trade Sales",
    "RRSFS":    "Real Retail Sales",
}
INFLATION_SERIES = {
    "PCEPILFE": "Core PCE",
    "CPILFESL": "Core CPI",
}

# 42 Macro reference: score growth/inflation vs the 2015-19 trend (their baseline,
# the dotted reference lines throughout the deck) rather than a trailing window that
# is distorted by the 2022 inflation spike. Blend level-vs-trend with 6-month RoC.
BASELINE = ("2015-01-01", "2019-12-31")
W_LEVEL  = 0.6

# ── Market basket (Yahoo Finance chart API, daily) ──────────────────────────
# expected momentum sign per regime: [GOLDILOCKS, REFLATION, INFLATION, DEFLATION]
RISK_ON   = [ 1,  1, -1, -1]   # risk assets: up risk-on, down risk-off
INFL_SENS = [-1,  1,  1, -1]   # commodities: up when inflation accelerating
ANTI_INFL = [ 1, -1, -1,  1]   # bonds: up when inflation decelerating
USD_VEC   = [-1, -1,  1,  1]   # dollar: safe haven, up in risk-off
GOLD_VEC  = [ 1,  1, -1,  1]   # gold favored in G/R/D, not I (deck currency row)

SINGLES = {
    "SPY": RISK_ON, "QQQ": RISK_ON, "IWM": RISK_ON, "EEM": RISK_ON,
    "HYG": RISK_ON, "XLF": RISK_ON, "IBIT": RISK_ON,
    "DBB": INFL_SENS, "DBA": INFL_SENS, "USO": INFL_SENS,
    "TLT": ANTI_INFL, "IEF": ANTI_INFL,
    "UUP": USD_VEC,
    "GLD": GOLD_VEC,
}
RATIOS = {  # numerator / denominator ; rising ratio = risk-on
    "High Beta / Low Beta":   ("SPHB", "SPLV", RISK_ON),
    "Cyclicals / Defensives": ("XLY",  "XLP",  RISK_ON),
    "Small / Large Cap":      ("IWM",  "SPY",  RISK_ON),
}
NICE = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000",
    "EEM": "Emerging Mkts", "HYG": "High Yield", "XLF": "Financials",
    "IBIT": "Bitcoin", "DBB": "Base Metals", "DBA": "Agriculture",
    "USO": "Crude Oil", "TLT": "Long Bonds", "IEF": "7-10y Treasurys",
    "UUP": "US Dollar", "GLD": "Gold",
}


# ── helpers ─────────────────────────────────────────────────────────────────
def clip(x, lo=-3.0, hi=3.0):
    return max(lo, min(hi, x))


def fred_series(sid, start="2008-01-01"):
    url = "https://api.stlouisfed.org/fred/series/observations"
    p = {"series_id": sid, "api_key": FRED_KEY, "file_type": "json",
         "observation_start": start, "sort_order": "asc"}
    r = requests.get(url, params=p, timeout=30)
    r.raise_for_status()
    out = []
    for o in r.json()["observations"]:
        v = o["value"]
        if v not in (".", "", None):
            out.append((o["date"], float(v)))
    return out


def yoy(obs):
    return [(obs[i][0], (obs[i][1] / obs[i - 12][1] - 1) * 100.0)
            for i in range(12, len(obs)) if obs[i - 12][1]]


def series_score(obs):
    ys = yoy(obs)
    if len(ys) < 20:
        return None
    vals = [v for _, v in ys]
    base = [v for d, v in ys if BASELINE[0] <= d <= BASELINE[1]]
    if len(base) < 12:                          # pre-2015 history missing -> trailing 5yr
        base = vals[-60:]
    b_mean = statistics.mean(base)
    b_std = statistics.pstdev(base) or 1.0
    level_z = (vals[-1] - b_mean) / b_std        # level vs 2015-19 trend
    accel = vals[-1] - vals[-7]                  # 6-month change in YoY
    accel_z = accel / b_std                      # same scale
    score = clip(W_LEVEL * level_z + (1 - W_LEVEL) * accel_z)
    return score, ys[-1][0], vals[-1], accel


def composite(series_map):
    scores, detail, latest = [], {}, None
    for sid, name in series_map.items():
        try:
            r = series_score(fred_series(sid))
            if r is None:
                continue
            sc, d, lvl, accel = r
            scores.append(sc)
            detail[name] = {"yoy": round(lvl, 2), "accel6m": round(accel, 2),
                            "score": round(sc, 2)}
            latest = d if latest is None or d > latest else latest
        except Exception as e:
            print(f"  ! {sid} failed: {e}", file=sys.stderr)
    return (statistics.mean(scores), detail, latest) if scores else None


def yahoo_closes(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    r = requests.get(url, params={"range": "1y", "interval": "1d"}, timeout=30,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(ts, closes):
        if c is not None:
            d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d")
            out.append((d, float(c)))
    return out


def momentum(closes):
    if len(closes) < 110:
        return None
    p = closes[-1][1]
    sma100 = statistics.mean([c for _, c in closes[-100:]])
    p63 = closes[-64][1]
    m = 0.5 * (p / sma100 - 1) + 0.5 * (p / p63 - 1)
    return 1 if m >= 0 else -1


def ratio_momentum(a, b):
    da, db = dict(yahoo_closes(a)), dict(yahoo_closes(b))
    dates = sorted(set(da) & set(db))
    return momentum([(d, da[d] / db[d]) for d in dates])


def market_breadth():
    counts = {r: 0 for r in REGIMES}
    markets = []

    def vote(name, mom, vec):
        if mom is None:
            return
        confirms = [REGIMES[i] for i in range(4) if vec[i] == mom]
        for r in confirms:
            counts[r] += 1
        markets.append({"name": name, "mom": "up" if mom > 0 else "down",
                        "confirms": confirms})

    for sym, vec in SINGLES.items():
        try:
            vote(NICE.get(sym, sym), momentum(yahoo_closes(sym)), vec)
        except Exception as e:
            print(f"  ! {sym} failed: {e}", file=sys.stderr)
        time.sleep(0.25)
    for name, (a, b, vec) in RATIOS.items():
        try:
            vote(name, ratio_momentum(a, b), vec)
        except Exception as e:
            print(f"  ! {name} failed: {e}", file=sys.stderr)
        time.sleep(0.25)

    n = len(markets)
    total = sum(counts.values()) or 1
    shares = {r: round(100 * counts[r] / total) for r in REGIMES}
    drift = 100 - sum(shares.values())
    if drift and shares:
        shares[max(shares, key=shares.get)] += drift
    return shares, markets, n


def quad(g, i):
    if g >= 0:
        return "REFLATION" if i >= 0 else "GOLDILOCKS"
    return "INFLATION" if i >= 0 else "DEFLATION"


def main():
    if not FRED_KEY:
        print("FRED_API_KEY not set (env var / repo secret) — keeping existing regime_data.json.",
              file=sys.stderr)
        return 1
    print("Fundamental: growth ...")
    g = composite(GROWTH_SERIES)
    print("Fundamental: inflation ...")
    inf = composite(INFLATION_SERIES)
    if not g or not inf:
        print("Insufficient fundamental data — keeping existing JSON.", file=sys.stderr)
        return 1
    g_score, g_detail, g_date = g
    i_score, i_detail, i_date = inf
    regime = quad(g_score, i_score)

    print("Market breadth ...")
    shares, markets, n = market_breadth()
    if n == 0:                                   # markets unreachable: lean on fundamentals
        shares = {r: (55 if r == regime else 15) for r in REGIMES}
    mkt_regime = max(shares, key=shares.get)
    risk_on = shares["GOLDILOCKS"] + shares["REFLATION"]

    data = {
        "as_of": max(g_date, i_date),
        "updated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline": "2015-2019 trend",
        "regime": regime,
        "growth":    {"dir": "Improving" if g_score >= 0 else "Slowing",
                      "score": round(g_score, 2)},
        "inflation": {"dir": "Rising" if i_score >= 0 else "Easing",
                      "score": round(i_score, 2)},
        "market_regime": mkt_regime,
        "shares": shares,
        "signal_strength": max(shares.values()),
        "risk_on_prob": risk_on,
        "n_markets": n,
        "components": {"growth": g_detail, "inflation": i_detail, "markets": markets},
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {OUT_PATH}: fundamental={regime}  market={mkt_regime}  shares={shares}  n={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
