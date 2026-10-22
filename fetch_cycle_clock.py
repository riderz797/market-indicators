"""
fetch_cycle_clock.py
Builds the Market Cycle Clock: a market-implied growth × inflation regime.

Fetches weekly closes for 13 funds via yfinance, turns 8 price ratios into two
axes, and bakes the full weekly history into market_cycle_clock.html.

  Growth axis    = cyclicals vs staples (XLY/XLP), small vs large caps (IWM/SPY),
                   copper vs gold (CPER/GLD), high beta vs low volatility
                   (SPHB/SPLV), high-yield credit vs Treasuries (HYG/IEF)
  Inflation axis = inflation-protected vs regular Treasuries (TIP/IEF),
                   commodities vs Treasuries (DBC/IEF), energy vs the market (XLE/SPY)

Each ratio scores its 13-week log change against its own typical move (52-week
standard deviation of weekly log changes, scaled to 13 weeks), clipped to ±3.
An axis is the average of its ratios. The signs pick the regime:
  growth+ / inflation-  GOLDILOCKS      growth+ / inflation+  REFLATION
  growth- / inflation+  INFLATION       growth- / inflation-  DEFLATION
The named regime only changes once a new regime has shown HOLD_WEEKS weeks in a row.

Run:  python fetch_cycle_clock.py
Requires: yfinance, numpy
"""

import json
import math
import os
import re
from datetime import date, datetime, timedelta

import numpy as np
import yfinance as yf

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "indicators", "macro", "market_cycle_clock.html")

# (id, numerator, denominator, axis, label, what a rising ratio says)
RATIOS = [
    ("XLY/XLP",   "XLY",  "XLP",  "growth",    "Cyclicals vs Staples",          "consumers spending on wants over needs"),
    ("IWM/SPY",   "IWM",  "SPY",  "growth",    "Small vs Large Caps",           "domestic, credit-sensitive firms leading"),
    ("CPER/GLD",  "CPER", "GLD",  "growth",    "Copper vs Gold",                "industrial demand over safety"),
    ("SPHB/SPLV", "SPHB", "SPLV", "growth",    "High Beta vs Low Volatility",   "appetite for risk"),
    ("HYG/IEF",   "HYG",  "IEF",  "growth",    "High-Yield Credit vs Treasuries", "lenders comfortable with weaker borrowers"),
    ("TIP/IEF",   "TIP",  "IEF",  "inflation", "Inflation-Protected vs Regular Treasuries", "bond market pricing more inflation"),
    ("DBC/IEF",   "DBC",  "IEF",  "inflation", "Commodities vs Treasuries",     "real assets over nominal bonds"),
    ("XLE/SPY",   "XLE",  "SPY",  "inflation", "Energy vs the Market",          "energy costs outrunning the broad market"),
]
TICKERS = sorted({t for r in RATIOS for t in (r[1], r[2])})

START = "2011-06-01"     # CPER starts Nov 2011; first scores need 53 weeks of history
WINDOW = 13              # weeks of change scored
SWING_WEEKS = 52         # weeks used for each ratio's typical move
CLIP = 3.0
HOLD_WEEKS = 3


def monday(d):
    return (d - timedelta(days=d.weekday())).isoformat()


def fetch_weekly(ticker):
    """{monday_iso: close}. yfinance sometimes adds dividend-date rows inside a
    week, so every row is snapped to its week's Monday and the last one wins."""
    hist = yf.Ticker(ticker).history(start=START, interval="1wk").dropna(subset=["Close"])
    if hist.empty:
        raise RuntimeError(f"no data returned for {ticker}")
    return {monday(ts.date()): float(c) for ts, c in hist["Close"].items()}


def ratio_scores(num, den):
    lr = np.log(num / den)
    out = [None] * len(lr)
    for i in range(SWING_WEEKS + 1, len(lr)):
        sd = float(np.std(np.diff(lr[i - SWING_WEEKS:i + 1])))
        z = (lr[i] - lr[i - WINDOW]) / (sd * math.sqrt(WINDOW)) if sd else 0.0
        out[i] = max(-CLIP, min(CLIP, float(z)))
    return out


def regime(g, i):
    if g >= 0:
        return "REFLATION" if i >= 0 else "GOLDILOCKS"
    return "INFLATION" if i >= 0 else "DEFLATION"


def main():
    prices = {}
    for t in TICKERS:
        prices[t] = fetch_weekly(t)
        print(f"  {t:5s}: {len(prices[t])} weeks")

    # Only complete weeks: a week counts once its Friday has passed, so a Monday
    # run bakes through the prior week and never a bar that has barely started.
    last_complete = monday(date.today() - timedelta(days=5))
    weeks = sorted(w for w in set.intersection(*(set(p) for p in prices.values())) if w <= last_complete)
    px = {t: np.array([prices[t][w] for w in weeks]) for t in TICKERS}

    comp = {rid: ratio_scores(px[a], px[b]) for rid, a, b, *_ in RATIOS}
    first = SWING_WEEKS + 1
    dates, growth, inflation, raw, held, comp_out = [], [], [], [], [], {rid: [] for rid in comp}
    for k in range(first, len(weeks)):
        g = float(np.mean([comp[r[0]][k] for r in RATIOS if r[3] == "growth"]))
        i = float(np.mean([comp[r[0]][k] for r in RATIOS if r[3] == "inflation"]))
        dates.append(weeks[k])
        growth.append(round(g, 3))
        inflation.append(round(i, 3))
        raw.append(regime(g, i))
        for rid in comp:
            comp_out[rid].append(round(comp[rid][k], 3))

    named, candidate, run = raw[0], None, 0
    for r in raw:
        if r == named:
            candidate, run = None, 0
        elif r == candidate:
            run += 1
        else:
            candidate, run = r, 1
        if candidate and run >= HOLD_WEEKS:
            named, candidate, run = candidate, None, 0
        held.append(named)

    # 13-week % change of each ratio for the components table
    change = {rid: round(float(px[a][-1] / px[b][-1] / (px[a][-1 - WINDOW] / px[b][-1 - WINDOW]) - 1) * 100, 2)
              for rid, a, b, *_ in RATIOS}

    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "dates": dates, "growth": growth, "inflation": inflation, "raw": raw, "held": held,
        "components": [{"id": rid, "axis": axis, "label": label, "reads": reads,
                        "scores": comp_out[rid], "change13w": change[rid]}
                       for rid, _, _, axis, label, reads in RATIOS],
        "pending": {"regime": candidate, "weeks": run} if candidate else None,
        "hold_weeks": HOLD_WEEKS,
        "baked_through": dates[-1],
        "baked_on": today,
    }

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    block = (f"const CYCLE_CLOCK = {json.dumps(payload, separators=(',', ':'))};\n"
             f"const CYCLE_CLOCK_BAKED = true; // injected by fetch_cycle_clock.py on {today}")
    new_html, n = re.subn(r"(// @@BAKED_DATA_START@@\n)[\s\S]*?(\n// @@BAKED_DATA_END@@)",
                          lambda m: m.group(1) + block + m.group(2), html)
    if n == 0:
        raise RuntimeError("Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers in market_cycle_clock.html")
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"\nBaked {len(dates)} weeks ({dates[0]} .. {dates[-1]}) into {HTML_PATH}")
    print(f"Latest: growth {growth[-1]:+.2f}  inflation {inflation[-1]:+.2f}  "
          f"this week {raw[-1]}  named {held[-1]}  pending {payload['pending']}")


if __name__ == "__main__":
    main()
