"""
fetch_yield_curve.py
Builds the "Howell's Yield Curve Allocator" page (yield_curve_regime.html): Howell's
GLI (Global Liquidity Indexes) yield curve taxonomy turned into a weekly call, plus his
asset allocation table and a test of that table against real fund returns.

The curve is the 2-year and 10-year Treasury yields (FRED DGS2, DGS10). Two moves
over the last 13 weeks:
  level = average change of the two yields     up = "bear",  down = "bull"
  slope = change in the 10-year minus 2-year gap   up = steepening, down = flattening
  bull steepening -> REBOUND        bear steepening -> CALM
  bear flattening -> SPECULATION    bull flattening -> TURBULENCE
(The sign of the average is the direction of whichever end moved more, which is the
usual market definition.) The named regime only changes once a new regime has shown
HOLD_WEEKS weeks in a row. An early read applies the same rule to 4-week moves, no hold.

Evidence: weekly total returns of fund proxies (Yahoo adjusted closes, weekdays only)
are grouped by the regime named at the end of the PRIOR week, so nothing uses
information that wasn't available yet. Asset rows use the fund's own return; sector
rows use return relative to SPY, since the slide ranks sectors against each other.

Run:  python fetch_yield_curve.py          (writes the page)
      python fetch_yield_curve.py --dry    (prints results, writes nothing)
Requires: requests, numpy, yfinance. FRED key from FRED_API_KEY, else read from the
already-published macro_cycle_dashboard.html.
"""

import json
import math
import os
import re
import sys
import time
import warnings
from datetime import date, datetime, timedelta

import numpy as np
import requests
import yfinance as yf

ROOT = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(ROOT, "indicators", "macro", "yield_curve_regime.html")
MACRO_DASH = os.path.join(ROOT, "indicators", "macro", "macro_cycle_dashboard.html")

YIELD_START = "1976-06-01"   # DGS2 begins June 1976
FUND_START = "1998-12-01"    # sector funds begin Dec 1998
WINDOW = 13                  # weeks of change behind the named regime
EARLY_WINDOW = 4             # weeks of change behind the early read
HOLD_WEEKS = 3
SD_WEEKS = 156               # trailing weeks used to size a "normal" move (confidence)
EARLY_HORIZON = 8            # weeks the early-read test looks ahead

REGIMES = ["REBOUND", "CALM", "SPECULATION", "TURBULENCE"]   # cycle order on the slide

# GLI's table: +1 favour (green), 0 neutral (orange), -1 avoid (red),
# in REGIMES order: Rebound, Calm, Speculation, Turbulence.
# (id, group, label, tickers, basis, source, gli)
ROWS = [
    ("beta",        "assets",  "Beta / Risk On",        ["SPHB"],              "abs", "gli",    [0, 1, 0, -1]),
    ("equities",    "assets",  "Equities",              ["SPY"],               "abs", "gli",    [1, 1, 0, -1]),
    ("credits",     "assets",  "Credits",               ["HYG"],               "abs", "gli",    [1, 0, -1, 0]),
    ("commodities", "assets",  "Commodities",           ["DBC"],               "abs", "gli",    [-1, 1, 1, -1]),
    ("duration",    "assets",  "Bond Duration",         ["TLT"],               "abs", "gli",    [-1, -1, 0, 1]),
    ("bitcoin",     "assets",  "Bitcoin",               ["BTC-USD"],           "abs", "tested", None),
    ("gold",        "assets",  "Gold",                  ["GLD"],               "abs", "tested", None),
    ("cyclicals",   "sectors", "Cyclicals",             ["XLY", "XLI", "XLB"], "rel", "gli",    [1, 1, -1, -1]),
    ("technology",  "sectors", "Technology",            ["XLK"],               "rel", "gli",    [1, 1, -1, -1]),
    ("financials",  "sectors", "Financials",            ["XLF"],               "rel", "gli",    [0, 1, 0, -1]),
    ("energy",      "sectors", "Energy / Commodities",  ["XLE"],               "rel", "gli",    [-1, 1, 1, -1]),
    ("defensives",  "sectors", "Defensives",            ["XLP", "XLU", "XLV"], "rel", "gli",    [-1, -1, 1, 1]),
    ("smallcaps",   "sectors", "Small Caps",            ["IWM"],               "rel", "tested", None),
]
warnings.filterwarnings("ignore", message="Mean of empty slice")
BENCH = "SPY"
TICKERS = sorted({t for r in ROWS for t in r[3]} | {BENCH})

# A tested cell is "favour"/"avoid" only if the regime's average differs from the
# rest of history by at least T_CUTOFF standard errors AND points the same way in
# both halves of the fund's history.
T_CUTOFF = 1.5


# ── helpers ──────────────────────────────────────────────────────────────────
def monday(d):
    return (d - timedelta(days=d.weekday())).isoformat()


def weekly_last(daily):
    """{date: value} -> {monday_iso: last value that week}."""
    out = {}
    for d in sorted(daily):
        out[monday(d)] = daily[d]
    return out


def fred_key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if k:
        return k
    try:
        with open(MACRO_DASH, encoding="utf-8") as f:
            m = re.search(r'FRED_API_KEY\s*=\s*"([a-f0-9]{32})"', f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def fetch_fred(sid, key):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": sid, "api_key": key, "file_type": "json", "observation_start": YIELD_START}
    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=60)
            r.raise_for_status()
            obs = r.json()["observations"]
            out = {}
            for o in obs:
                if o["value"] not in (".", ""):
                    out[date.fromisoformat(o["date"])] = float(o["value"])
            if not out:
                raise RuntimeError(f"{sid}: no observations")
            return out
        except Exception as e:      # FRED maintenance pages, timeouts
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"FRED {sid} failed: {last_err}")


def fetch_fund(ticker):
    """Weekly closes keyed by Monday, from DAILY adjusted closes (weekdays only), so the
    weekly-bar anchor problem can't shift anything and BTC lines up with Friday closes."""
    hist = yf.Ticker(ticker).history(start=FUND_START, interval="1d", auto_adjust=True)
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise RuntimeError(f"no data for {ticker}")
    daily = {}
    for ts, c in hist["Close"].items():
        d = ts.date()
        if d.weekday() < 5:
            daily[d] = float(c)
    return weekly_last(daily)


def regime_of(slope, level):
    if slope >= 0:
        return 0 if level < 0 else 1      # REBOUND / CALM
    return 2 if level >= 0 else 3         # SPECULATION / TURBULENCE


def hold(raw, weeks):
    named, cand, run, out = raw[0], None, 0, []
    for r in raw:
        if r == named:
            cand, run = None, 0
        elif r == cand:
            run += 1
        else:
            cand, run = r, 1
        if cand is not None and run >= weeks:
            named, cand, run = cand, None, 0
        out.append(named)
    return out, (cand, run)


def runs(mask):
    """Number of separate stretches where mask is True."""
    return int(np.sum(mask[1:] & ~mask[:-1]) + (1 if len(mask) and mask[0] else 0))


# ── evidence ─────────────────────────────────────────────────────────────────
def row_returns(row, weeks, prices):
    """Weekly return series for a row (NaN where unavailable), aligned to weeks.
    ret[k] = return from week k-1's close to week k's close."""
    tickers, basis = row[3], row[4]
    n = len(weeks)

    def rets(t):
        p = np.array([prices[t].get(w, np.nan) for w in weeks])
        r = np.full(n, np.nan)
        r[1:] = p[1:] / p[:-1] - 1
        return r

    basket = np.nanmean(np.vstack([rets(t) for t in tickers]), axis=0) if len(tickers) > 1 else rets(tickers[0])
    if len(tickers) > 1:   # only weeks where every member traded
        ok = np.all(np.vstack([~np.isnan(rets(t)) for t in tickers]), axis=0)
        basket = np.where(ok, basket, np.nan)
    if basis == "rel":
        basket = basket - rets(BENCH)
    return basket


def cell_stats(r, reg, k):
    """Stats for regime k given weekly returns r and the prior-week regime reg."""
    ok = ~np.isnan(r)
    inside = ok & (reg == k)
    outside = ok & (reg != k)
    n_in, n_out = int(inside.sum()), int(outside.sum())
    if n_in < 20 or n_out < 20:
        return None
    a, b = r[inside], r[outside]
    se = math.sqrt(a.var(ddof=1) / n_in + b.var(ddof=1) / n_out)
    t = (a.mean() - b.mean()) / se if se else 0.0

    # same direction in both halves of this row's history?
    idx = np.where(ok)[0]
    mid = idx[len(idx) // 2]
    halves = []
    for lo, hi in ((idx[0], mid), (mid, idx[-1] + 1)):
        m = np.zeros_like(ok)
        m[lo:hi] = True
        ai, bi = r[inside & m], r[outside & m]
        halves.append(float(ai.mean() - bi.mean()) if len(ai) >= 8 and len(bi) >= 8 else 0.0)
    tilt = a.mean() - r[ok].mean()
    same = (halves[0] > 0 and halves[1] > 0) or (halves[0] < 0 and halves[1] < 0)
    call = 0
    if same and abs(t) >= T_CUTOFF:
        call = 1 if t > 0 else -1
    return {
        "ann": round(float(a.mean()) * 52 * 100, 1),           # % a year while in this regime
        "tilt": round(float(tilt) * 52 * 100, 1),               # vs the row's all-weeks average
        "t": round(float(t), 2),
        "n": n_in,
        "halves": [round(h * 52 * 100, 1) for h in halves],
        "call": call,
    }


def evidence(weeks, held, raw, prices):
    n = len(weeks)
    # regime known at the end of the prior week, attributed to this week's return
    prior = np.full(n, -1)
    prior[1:] = np.array(held[:-1])
    rows_out = []
    series = {}
    for row in ROWS:
        rid, group, label, tickers, basis, source, gli = row
        r = row_returns(row, weeks, prices)
        r = np.where(prior >= 0, r, np.nan)
        series[rid] = r
        ok = ~np.isnan(r)
        first = weeks[int(np.argmax(ok))] if ok.any() else None
        cells = []
        for k in range(4):
            c = cell_stats(r, prior, k)
            if c:
                c["episodes"] = runs(ok & (prior == k))
            cells.append(c)
        rows_out.append({
            "id": rid, "group": group, "label": label, "tickers": tickers, "basis": basis,
            "source": source, "gli": gli, "start": first, "weeks": int(ok.sum()),
            "avg": round(float(np.nanmean(r)) * 52 * 100, 1),
            "cells": cells,
            "tested": [c["call"] if c else 0 for c in cells],
        })

    # Whole-table test: each week, average of GLI's favoured rows minus average of
    # its avoided rows for the regime named last week (GLI rows only) — "predicts".
    # Alongside it, the same spread over the 13 weeks that DEFINED each week's raw
    # regime — "describes": does the table fit what assets did while the curve moved?
    table = {}
    win_mean = {}
    for rid, r in series.items():
        m = np.full(n, np.nan)
        for i in range(WINDOW, n):
            v = r[i - WINDOW + 1:i + 1]
            if np.sum(~np.isnan(v)) >= WINDOW - 2:
                m[i] = np.nanmean(v)
        win_mean[rid] = m

    def fav_minus_avoid(grows, k, values, i):
        fav = [values[r["id"]][i] for r in grows if r["gli"][k] == 1 and not np.isnan(values[r["id"]][i])]
        avo = [values[r["id"]][i] for r in grows if r["gli"][k] == -1 and not np.isnan(values[r["id"]][i])]
        return np.mean(fav) - np.mean(avo) if fav and avo else np.nan

    for group in ("assets", "sectors"):
        grows = [r for r in rows_out if r["group"] == group and r["source"] == "gli"]
        spread = np.full(n, np.nan)
        desc = np.full(n, np.nan)
        for i in range(n):
            if prior[i] >= 0:
                spread[i] = fav_minus_avoid(grows, prior[i], series, i)
            desc[i] = fav_minus_avoid(grows, raw[i], win_mean, i)
        ok = ~np.isnan(spread)
        s = spread[ok]
        idx = np.where(ok)[0]
        mid = idx[len(idx) // 2]
        by_regime = []
        for k in range(4):
            m = ok & (prior == k)
            v = spread[m]
            h1, h2 = spread[m & (np.arange(n) < mid)], spread[m & (np.arange(n) >= mid)]
            d = desc[(np.array(raw) == k) & ~np.isnan(desc)]
            by_regime.append({
                "ann": round(float(v.mean()) * 52 * 100, 1) if len(v) else None,
                "n": int(m.sum()),
                "t": round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2) if len(v) > 2 else None,
                "halves": [round(float(h.mean()) * 52 * 100, 1) if len(h) else None for h in (h1, h2)],
                "describes": round(float(d.mean()) * 52 * 100, 1) if len(d) else None,
            })
        years = {}
        for i in np.where(ok)[0]:
            years.setdefault(weeks[i][:4], []).append(spread[i])
        full_years = {y: v for y, v in years.items() if len(v) >= 40}
        pos = sum(1 for v in full_years.values() if sum(v) > 0)
        table[group] = {
            "ann": round(float(s.mean()) * 52 * 100, 1),
            "t": round(float(s.mean() / (s.std(ddof=1) / math.sqrt(len(s)))), 2),
            "weeks": int(ok.sum()),
            "start": weeks[int(np.argmax(ok))],
            "split": weeks[mid],
            "years_positive": pos, "years": len(full_years),
            "by_regime": by_regime,
        }
    return rows_out, table


def agreement(rows_out):
    """Over GLI's favour/avoid cells only: how many history confirms, contradicts,
    or can't separate from noise."""
    calls = confirmed = contradicted = 0
    for r in rows_out:
        if r["source"] != "gli":
            continue
        for k in range(4):
            g = r["gli"][k]
            if r["cells"][k] is None or g == 0:
                continue
            calls += 1
            t = r["tested"][k]
            confirmed += g == t
            contradicted += g * t == -1
    return {"calls": calls, "confirmed": confirmed, "contradicted": contradicted,
            "no_edge": calls - confirmed - contradicted}


def early_test(held, early):
    """When the 4-week read differs from the named regime, how often does the named
    regime become that read within EARLY_HORIZON weeks, versus one of the other two?"""
    flagged = hit = other_hits = other_n = 0
    n = len(held)
    for i in range(n - EARLY_HORIZON):
        if early[i] == held[i]:
            continue
        ahead = set(held[i + 1:i + 1 + EARLY_HORIZON])
        flagged += 1
        hit += early[i] in ahead
        for k in range(4):
            if k not in (held[i], early[i]):
                other_n += 1
                other_hits += k in ahead
    return {
        "flagged": flagged,
        "hit": round(100 * hit / flagged, 1) if flagged else None,
        "other": round(100 * other_hits / other_n, 1) if other_n else None,
        "horizon": EARLY_HORIZON,
    }


# ── main ─────────────────────────────────────────────────────────────────────
def main(dry=False):
    key = fred_key()
    if not key:
        print("No FRED key (FRED_API_KEY env or macro_cycle_dashboard.html) — keeping the existing page.")
        return
    try:
        y2d, y10d = fetch_fred("DGS2", key), fetch_fred("DGS10", key)
    except Exception as e:
        print(f"{e} — keeping the existing page.")
        return
    latest_obs = min(max(y2d), max(y10d)).isoformat()
    y2w, y10w = weekly_last(y2d), weekly_last(y10d)

    # A week counts once its Friday has passed (same rule as the Market Cycle Clock).
    last_complete = monday(date.today() - timedelta(days=5))
    weeks = sorted(w for w in set(y2w) & set(y10w) if w <= last_complete)
    y2 = np.array([y2w[w] for w in weeks])
    y10 = np.array([y10w[w] for w in weeks])
    gap = y10 - y2
    lvl = (y10 + y2) / 2

    def moves(W):
        s = np.full(len(weeks), np.nan)
        l = np.full(len(weeks), np.nan)
        s[W:] = gap[W:] - gap[:-W]
        l[W:] = lvl[W:] - lvl[:-W]
        return s, l

    slope13, level13 = moves(WINDOW)
    slope4, level4 = moves(EARLY_WINDOW)

    # confidence: the weaker of the two 13-week moves, in units of a normal 13-week move
    dg, dl = np.diff(gap, prepend=np.nan), np.diff(lvl, prepend=np.nan)
    conf = np.full(len(weeks), np.nan)
    for i in range(SD_WEEKS + 1, len(weeks)):
        sg = np.nanstd(dg[i - SD_WEEKS + 1:i + 1]) * math.sqrt(WINDOW)
        sl = np.nanstd(dl[i - SD_WEEKS + 1:i + 1]) * math.sqrt(WINDOW)
        if sg and sl:
            conf[i] = min(abs(slope13[i]) / sg, abs(level13[i]) / sl)

    first = SD_WEEKS + 1
    weeks = weeks[first:]
    y2, y10, slope13, level13, slope4, level4, conf = (a[first:] for a in (y2, y10, slope13, level13, slope4, level4, conf))
    raw = [regime_of(s, l) for s, l in zip(slope13, level13)]
    early = [regime_of(s, l) for s, l in zip(slope4, level4)]
    held, (cand, run) = hold(raw, HOLD_WEEKS)

    # confidence bands from history: bottom third low, top third high
    q1, q2 = (round(float(q), 2) for q in np.nanpercentile(conf, [33.3, 66.7]))

    print(f"Yields: {len(weeks)} weeks {weeks[0]} .. {weeks[-1]} (latest daily obs {latest_obs})")
    print(f"  2y {y2[-1]:.2f}  10y {y10[-1]:.2f}  13wk slope {slope13[-1]*100:+.0f}bp level {level13[-1]*100:+.0f}bp "
          f"conf {conf[-1]:.2f} (bands {q1}/{q2})")
    print(f"  raw {REGIMES[raw[-1]]}  named {REGIMES[held[-1]]}  early {REGIMES[early[-1]]}  pending {cand, run}")
    changes = sum(1 for a, b in zip(held, held[1:]) if a != b)
    print(f"  named regime changes/yr: {changes / (len(held) / 52):.1f}")

    # funds
    prices = {}
    for t in TICKERS:
        prices[t] = fetch_fund(t)
        print(f"  {t:8s} {len(prices[t])} weeks from {min(prices[t])}")

    rows_out, table = evidence(weeks, held, raw, prices)
    agr = agreement(rows_out)
    et = early_test(held, early)

    print("\nEvidence (annualised tilt vs row average, t, GLI call -> tested call):")
    for r in rows_out:
        cells = []
        for k in range(4):
            c = r["cells"][k]
            g = "  " if r["gli"] is None else f"{r['gli'][k]:+d}"
            cells.append("     n/a      " if not c else f"{c['tilt']:+6.1f} t{c['t']:+5.1f} {g}>{c['call']:+d}")
        print(f"  {r['label'][:16]:16s} {r['start']}  " + " | ".join(cells))
    print(f"\nAgreement with GLI: {agr}")
    for g, v in table.items():
        print(f"Table test {g}: favoured minus avoided {v['ann']:+.1f}%/yr t={v['t']} "
              f"({v['years_positive']}/{v['years']} years positive) by regime "
              + ", ".join(f"{REGIMES[k][:4]} {b['ann']:+.1f} (t {b['t']}, halves {b['halves']}, describes {b['describes']:+.1f})"
                          for k, b in enumerate(v["by_regime"])))
    print(f"Early read: {et}")

    if dry:
        return

    bp = lambda a: [None if np.isnan(v) else int(round(v * 100)) for v in a]
    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "dates": weeks,
        "y2": [round(float(v), 2) for v in y2],
        "y10": [round(float(v), 2) for v in y10],
        "slope": bp(slope13), "level": bp(level13),
        "slope4": bp(slope4), "level4": bp(level4),
        "conf": [None if np.isnan(v) else round(float(v), 2) for v in conf],
        "raw": raw, "held": held, "early": early,
        "pending": {"regime": cand, "weeks": run} if cand is not None else None,
        "conf_bands": [q1, q2],
        "rows": rows_out, "table_test": table, "agreement": agr, "early_test": et,
        "params": {"window": WINDOW, "early_window": EARLY_WINDOW, "hold_weeks": HOLD_WEEKS,
                   "t_cutoff": T_CUTOFF, "sd_weeks": SD_WEEKS},
        "latest_obs": latest_obs,
        "baked_through": weeks[-1],
        "baked_on": today,
    }

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    block = (f"const YIELD_CURVE = {json.dumps(payload, separators=(',', ':'))};\n"
             f"const YIELD_CURVE_BAKED = true; // injected by fetch_yield_curve.py on {today}")
    new_html, n = re.subn(r"(// @@BAKED_DATA_START@@\n)[\s\S]*?(\n// @@BAKED_DATA_END@@)",
                          lambda m: m.group(1) + block + m.group(2), html)
    if n == 0:
        raise RuntimeError("Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers in yield_curve_regime.html")
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"\nBaked {len(weeks)} weeks into {HTML_PATH}")


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
