"""
bake_seasonality.py
Bakes the per-asset data files behind indicators/macro/seasonality.html.

One config table drives every asset. Each one is fetched, grouped by calendar
year, and written to data/seasonality/<id>.json. The page itself is a plain
static HTML file that loads whichever asset you select — nothing here generates
markup, so the page can be edited directly like any other page on the site.

This replaces bake_sp500.py / bake_btc.py / build_seasonality.py /
build_seasonality_btc.py, the last two of which each embedded a full copy of
the ~1000-line page template inside a Python string and had already drifted
apart.

Assets:
  spx       S&P 500 daily closes since 1942 (Yahoo ^GSPC)
  btc       Bitcoin daily closes since 2014 (Yahoo BTC-USD)
  gold      LBMA PM fix since 1971 (the end of the fixed $35 gold window)
  brent     Brent crude spot since 1987 (US EIA, via FRED)
  cshiller  Case-Shiller US National home price index since 1987 (FRED).
            MONTHLY, and deliberately the NOT-seasonally-adjusted series —
            the adjusted one has the seasonality removed by construction and
            would chart a flat line.

Run:  python bake_seasonality.py
Requires: requests  (pip install requests)
"""

import json
import os
import sys
from datetime import datetime

from market_data import fetch_yahoo, fetch_fred, fetch_lbma_gold

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data", "seasonality")

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Cycle definitions. `anchor` is a year known to sit in bucket 0, so the page
# computes a year's bucket as (year - anchor) % 4.
ELECTION_CYCLE = {
    "id": "election", "label": "Election", "anchor": 2025,
    "names":  ["1 Post-Election", "2 Midterm", "3 Pre-Election", "4 Election"],
    "colors": ["#0277BD", "#2E7D32", "#7B1FA2", "#D84315"],
    "note": "Based on the U.S. presidential cycle. Liquidity and risk appetite "
            "vary by cycle phase.",
}
HALVING_CYCLE = {
    "id": "halving", "label": "Halving", "anchor": 2024,
    "names":  ["1 Halving", "2 Post-Halving", "3 Mid-Cycle", "4 Pre-Halving"],
    "colors": ["#C1441A", "#2E7D32", "#1565C0", "#6A1B9A"],
    "note": "Halvings: Nov 2012, Jul 2016, May 2020, Apr 2024. The supply cut "
            "drives a 4-year cycle.",
}


# ── ASSETS ─────────────────────────────────────────────────────────────────────
# eraWeights: [[through_year, weight], ...] — last entry's year is null, meaning
#   "everything after". Averages are weighted so thin/unrepresentative early
#   history does not carry the same load as the modern record. The spx and btc
#   weights are carried over verbatim from the pages this replaces so their
#   curves are unchanged; the three new assets are left unweighted rather than
#   inventing regime judgements.
# rmseScale: divisor in the path-similarity score, set near the asset's typical
#   annual swing so "close" means the same thing across assets.
ASSETS = [
    {
        "id": "spx", "name": "S&P 500", "badge": "EQUITIES", "mode": "daily",
        "start": 1942, "colorBase": 1942, "rmseScale": 5,
        "eraWeights": [[1951, 0.10], [1970, 0.25], [2008, 1.00], [None, 1.50]],
        "cycles": [ELECTION_CYCLE],
        "live": {"symbol": "^GSPC"},
        "source": "Daily closes since 1942 (Yahoo ^GSPC)",
        "fetch": lambda: fetch_yahoo("^GSPC"),
    },
    {
        "id": "btc", "name": "Bitcoin", "badge": "BTC", "mode": "daily",
        "start": 2014, "colorBase": 2014, "rmseScale": 20,
        "eraWeights": [[2016, 0.50], [None, 1.00]],
        "cycles": [HALVING_CYCLE, ELECTION_CYCLE],
        "live": {"symbol": "BTC-USD"},
        "source": "Daily closes since 2014 (Yahoo BTC-USD)",
        "fetch": lambda: fetch_yahoo("BTC-USD"),
    },
    {
        "id": "gold", "name": "Gold", "badge": "COMMODITIES", "mode": "daily",
        "start": 1971, "colorBase": 1971, "rmseScale": 8,
        "eraWeights": [[None, 1.00]],
        "cycles": [ELECTION_CYCLE],
        "live": {"symbol": "GC=F"},
        "source": "LBMA PM fix since Aug 1971, the end of the fixed gold window. "
                  "Current year extended with COMEX futures (GC=F)",
        "fetch": lambda: [(d, v) for d, v in fetch_lbma_gold() if d >= "1971-08-16"],
    },
    {
        "id": "brent", "name": "Oil (Brent Crude)", "badge": "COMMODITIES",
        "mode": "daily", "start": 1987, "colorBase": 1987, "rmseScale": 12,
        "eraWeights": [[None, 1.00]],
        "cycles": [ELECTION_CYCLE],
        "live": {"symbol": "BZ=F"},
        "source": "Europe Brent spot since May 1987 (US Energy Information "
                  "Administration, via FRED). Current year extended with Brent "
                  "futures (BZ=F)",
        "fetch": lambda: fetch_fred("DCOILBRENTEU"),
    },
    {
        "id": "cshiller", "name": "US Home Prices (Case-Shiller)",
        "badge": "HOUSING", "mode": "monthly",
        "start": 1987, "colorBase": 1987, "rmseScale": None,
        "eraWeights": [[None, 1.00]],
        "cycles": [ELECTION_CYCLE],
        "live": None,                      # FRED needs a key; baked weekly instead
        "source": "S&P CoreLogic Case-Shiller U.S. National Home Price Index, "
                  "NOT seasonally adjusted (FRED CSUSHPINSA), monthly since "
                  "Jan 1987. Publishes about three months in arrears",
        "fetch": lambda: fetch_fred("CSUSHPINSA"),
    },
]


# ── BUILD ──────────────────────────────────────────────────────────────────────
def group_by_year(series, start_year, mode):
    """[(date, value)] -> {year: {"d": [MM-DD...], "c": [value...]}}.

    Dates drop their year prefix — it is already the key, and the page only ever
    renders them as "Jan 5". On the S&P's 84 years that alone saves ~130 KB."""
    years = {}
    for date_str, value in series:
        yr = date_str[:4]
        if int(yr) < start_year:
            continue
        bucket = years.setdefault(yr, {"d": [], "c": []})
        bucket["d"].append(date_str[5:])
        bucket["c"].append(round(value, 4))
    if mode == "monthly":
        # One print per month; guard against a revision arriving twice.
        for yr, b in years.items():
            seen, d, c = set(), [], []
            for md, v in zip(b["d"], b["c"]):
                if md[:2] in seen:
                    continue
                seen.add(md[:2])
                d.append(md)
                c.append(v)
            years[yr] = {"d": d, "c": c}
    return years


def month_ticks(reference):
    """First index of each month within a reference year, 1-based — the x
    positions the page labels Jan..Dec. Daily assets only; monthly ones are
    already indexed by month."""
    first = {}
    for i, md in enumerate(reference["d"]):
        m = int(md[:2])
        if m not in first:
            first[m] = i + 1
    return [first.get(m, 0) for m in range(1, 13)]


def build(spec):
    series = spec["fetch"]()
    if not series:
        raise RuntimeError(f"{spec['name']}: source returned nothing")

    years = group_by_year(series, spec["start"], spec["mode"])
    current_year = datetime.now().year
    complete = sorted(y for y in years if int(y) < current_year)
    if not complete:
        raise RuntimeError(f"{spec['name']}: no complete years")
    baked_through = int(complete[-1])

    payload = {
        "id": spec["id"], "name": spec["name"], "badge": spec["badge"],
        "mode": spec["mode"], "start": spec["start"],
        "colorBase": spec["colorBase"], "rmseScale": spec["rmseScale"],
        "eraWeights": spec["eraWeights"], "cycles": spec["cycles"],
        "live": spec["live"], "source": spec["source"],
        "bakedThrough": baked_through,
        "bakedOn": datetime.now().strftime("%Y-%m-%d"),
        "monthLabels": MONTH_LABELS,
        # Complete years only. The current year is fetched live in-browser for
        # assets that have a `live` symbol, so baking a partial year would just
        # go stale between weekly runs.
        "years": {y: years[y] for y in complete},
    }
    if spec["mode"] == "daily":
        payload["monthTicks"] = month_ticks(years[complete[-1]])
    else:
        payload["monthTicks"] = list(range(1, 13))
        # No live feed, so the page must show the partial current year from here.
        if str(current_year) in years:
            payload["years"][str(current_year)] = years[str(current_year)]

    return payload, len(complete)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    failures = []
    for spec in ASSETS:
        print(f"Fetching {spec['name']}...")
        try:
            payload, n_years = build(spec)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e} — keeping existing file")
            failures.append(spec["id"])
            continue
        path = os.path.join(OUT_DIR, f"{spec['id']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        kb = os.path.getsize(path) / 1024
        yrs = sorted(payload["years"])
        print(f"  {spec['name']:32s} {n_years:3d} complete years "
              f"({yrs[0]}-{payload['bakedThrough']}), {kb:7.1f} KB")

    if failures:
        print(f"\nFailed: {', '.join(failures)}")
        # Partial success still leaves the page working on the assets that did
        # bake, so only a total wipeout is worth a non-zero exit.
        if len(failures) == len(ASSETS):
            raise SystemExit(1)
    print("\nDone.")


if __name__ == "__main__":
    main()
