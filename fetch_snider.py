#!/usr/bin/env python3
"""
fetch_snider.py — data builder for Snider's Signal Board.

Builds the four boards described in indicators/macro/snider_signal_board.html
from Jeff Snider's (Eurodollar University) framework: read monetary conditions
off market signals rather than off macroeconomic aggregates.

  Board 1  Breakeven curve          — is inflation a regime, or a supply shock?
  Board 2  Collateral & dealer      — is the funding/collateral system tightening?
  Board 3  Eurodollar quantity      — is offshore dollar funding expanding?
  Board 4  Mosaic                   — which investment quadrants survive?

WHY THESE SERIES

Snider's #1 signal is the interest-rate swap spread, which bundles forward rate
expectations, dealer balance-sheet capacity, demand for duration and collateral
conditions into one price. That series died on FRED in 2016 (DSWP10 ends
2016-10-28) and live swap rates are licence-restricted, so Board 2 reconstructs
the same information from free official sources: the secured/unsecured and
secured/administered spreads, bills trading through the reverse-repo floor
(pure collateral scarcity), dealer Treasury inventory, and settlement fails.

Board 3's headline is NDFACBW027SBOG — "Net Due to Related Foreign Offices,
All Commercial Banks", the H.8 line measuring US banks' net dollar funding
position with their own offshore offices. It is the eurodollar system's
visible footprint on a domestic statistical release: weekly, current, and
starting 2004-06, so unlike Board 2 it covers August 2007.

COVERAGE (why boards start where they do)
  Board 1  2003-01  T5YIFR is the binding constraint. Covers 2008 AND 2021-22.
  Board 2  2013-04  3 of 5 components; 4 from 2018-04 (SOFR); 5 from 2021-07
                    (IORB). Cannot reach 2008 — no modern funding series does.
  Board 3  2004-06  NDFA start. Covers August 2007.

Treasury International Capital was evaluated as a Board 3 backdrop and dropped:
the global claims file (bc_globl.txt, country code 99996) ends 2003-01, a
casualty of the 2003 reporting-form change.

Output: indicators/macro/snider_data.json  (read by snider_signal_board.html)
Pure stdlib + requests, matching fetch_regime.py, so CI needs no extra deps.

Run:  python fetch_snider.py
"""

import json
import math
import os
import statistics
import datetime
import urllib.request
import urllib.error

FRED_KEY = os.environ.get("FRED_API_KEY", "824b29c5afa52f3fc7c6e7dc4925aebb")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "indicators", "macro", "snider_data.json")

NYFED_PD = "https://markets.newyorkfed.org/api/pd/get/{}.json"

# Rolling z-score windows, in weekly observations
Z_WIN_LONG = 260    # 5 years — structural context (breakevens, curve)
Z_WIN_MID  = 156    # 3 years — funding conditions move faster
Z_MIN_OBS  = 52     # need a year before a z-score means anything

QUADRANTS = ["SWEET SPOT", "INFLATIONARY BOOM", "STAGFLATION", "DEFLATIONARY BUST"]


# ── FETCHERS ───────────────────────────────────────────────────────────────────
def _get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fred(series_id, start="2000-01-01"):
    """Fetch a FRED series as {date: float}. Missing observations ('.') dropped."""
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
           f"&observation_start={start}&sort_order=asc&limit=100000")
    data = _get_json(url)
    if "error_message" in data:
        raise RuntimeError(f"FRED error for {series_id}: {data['error_message']}")
    return {o["date"]: float(o["value"])
            for o in data.get("observations", []) if o["value"] != "."}


def nyfed_pd(keyid):
    """Fetch a NY Fed primary-dealer series as {date: float}.

    These are weekly (Wednesday as-of) and carry periodic series breaks — the
    current one is SBN2024. The API returns all breaks concatenated under the
    same keyid, so a value can repeat across a break boundary; de-duplicating
    by date keeps the latest revision for each date.
    """
    data = _get_json(NYFED_PD.format(keyid))
    out = {}
    for row in data.get("pd", {}).get("timeseries", []):
        v = row.get("value")
        if v in (None, "", "*", "n.a."):
            continue
        try:
            out[row["asofdate"]] = float(v)
        except ValueError:
            continue
    return out


# ── SERIES MATH ────────────────────────────────────────────────────────────────
def to_friday(date_str):
    """Snap a date to the Friday of its week (weekly grid anchor)."""
    d = datetime.date.fromisoformat(date_str)
    return (d + datetime.timedelta(days=(4 - d.weekday()) % 7)).isoformat()


def weekly(series):
    """Resample {date: v} to a Friday-anchored weekly grid, last value wins."""
    out = {}
    for d in sorted(series):
        out[to_friday(d)] = series[d]
    return out


def align(weekly_map, grid):
    """Project a weekly dict onto the master grid, carrying forward the last
    observation. Returns None before the series starts, never after — a stale
    carry is visible in the coverage metadata rather than silently interpolated."""
    out, last = [], None
    for g in grid:
        if g in weekly_map:
            last = weekly_map[g]
        out.append(last)
    return out


def align_stale_capped(weekly_map, grid, max_weeks):
    """align(), but drops back to None once the carried value exceeds max_weeks
    old. Used for monthly series so a discontinued release cannot masquerade
    as current data."""
    out, last, age = [], None, 0
    for g in grid:
        if g in weekly_map:
            last, age = weekly_map[g], 0
        else:
            age += 1
        out.append(last if (last is not None and age <= max_weeks) else None)
    return out


def expanding_median(values, min_obs=104):
    """Median of everything seen up to and including t — no lookahead.

    Deliberately NOT a rolling window. A trailing window re-bases itself after
    a crash, so a forward breakeven merely recovering to its normal level reads
    as 'high and rising' — which inverts the 2021-22 signal. The expanding
    median holds the long-run anchor steady instead.
    """
    out, hist = [], []
    for v in values:
        if v is not None:
            hist.append(v)
        out.append(statistics.median(hist) if len(hist) >= min_obs else None)
    return out


def rolling_z(values, window=Z_WIN_LONG, min_obs=Z_MIN_OBS):
    """Trailing z-score. Uses only past data at each point — no lookahead."""
    out = []
    for i in range(len(values)):
        if values[i] is None:
            out.append(None)
            continue
        lo = max(0, i - window + 1)
        hist = [v for v in values[lo:i + 1] if v is not None]
        if len(hist) < min_obs:
            out.append(None)
            continue
        mu = statistics.fmean(hist)
        sd = statistics.pstdev(hist)
        out.append(round((values[i] - mu) / sd, 4) if sd > 1e-9 else 0.0)
    return out


def change_n(values, n):
    """Level change over n observations (absolute, not percent)."""
    return [None if (i < n or values[i] is None or values[i - n] is None)
            else round(values[i] - values[i - n], 4)
            for i in range(len(values))]


def yoy_pct(values, n=52):
    """Year-over-year percent change on a weekly grid."""
    out = []
    for i in range(len(values)):
        if i < n or values[i] is None or values[i - n] in (None, 0):
            out.append(None)
        else:
            out.append(round(100.0 * (values[i] / values[i - n] - 1.0), 4))
    return out


def diff_series(a, b):
    return [None if (x is None or y is None) else round(x - y, 4)
            for x, y in zip(a, b)]


def mean_of(vals):
    present = [v for v in vals if v is not None]
    return statistics.fmean(present) if present else None


def clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def r4(seq):
    return [None if v is None else round(v, 4) for v in seq]


def last_present(seq):
    for v in reversed(seq):
        if v is not None:
            return v
    return None


# ── BUILD ──────────────────────────────────────────────────────────────────────
def build():
    log = []

    def fetch_soft(label, fn, *args):
        """Fetch that degrades to an empty series rather than killing the run —
        one dead source must not take the whole board down."""
        try:
            s = fn(*args)
            log.append(f"  {label:22s}: {len(s):5d} obs, last = {max(s) if s else 'n/a'}")
            return s
        except Exception as e:                                  # noqa: BLE001
            log.append(f"  {label:22s}: FAILED ({e})")
            return {}

    print("Fetching FRED series...")
    # Board 1 — breakevens
    be5     = fetch_soft("T5YIE",     fred, "T5YIE",   "2003-01-01")
    be10    = fetch_soft("T10YIE",    fred, "T10YIE",  "2003-01-01")
    be5y5y  = fetch_soft("T5YIFR",    fred, "T5YIFR",  "2003-01-01")
    dgs30   = fetch_soft("DGS30",     fred, "DGS30",   "2003-01-01")
    dfii30  = fetch_soft("DFII30",    fred, "DFII30",  "2003-01-01")

    # Board 2 — collateral & dealer capacity
    sofr    = fetch_soft("SOFR",      fred, "SOFR",          "2018-01-01")
    iorb    = fetch_soft("IORB",      fred, "IORB",          "2021-01-01")
    effr    = fetch_soft("EFFR",      fred, "EFFR",          "2013-01-01")
    tb4wk   = fetch_soft("DTB4WK",    fred, "DTB4WK",        "2013-01-01")
    rrpaw   = fetch_soft("RRP award", fred, "RRPONTSYAWARD", "2013-01-01")

    # Board 3 — eurodollar quantity
    ndfa    = fetch_soft("NDFA (H.8)", fred, "NDFACBW027SBOG", "2004-01-01")
    dxy     = fetch_soft("DTWEXBGS",   fred, "DTWEXBGS",       "2004-01-01")
    foroff  = fetch_soft("Foreign official", fred, "FORTREASPOS99990", "2004-01-01")

    # Board 4 — growth axis from the curve
    dgs10   = fetch_soft("DGS10",     fred, "DGS10", "2003-01-01")
    dgs2    = fetch_soft("DGS2",      fred, "DGS2",  "2003-01-01")

    print("Fetching NY Fed primary dealer data...")
    pos     = fetch_soft("Dealer UST pos", nyfed_pd, "PDPOSGST-TOT")
    ftd     = fetch_soft("Fails to deliver", nyfed_pd, "PDFTD-UST")
    ftr     = fetch_soft("Fails to receive", nyfed_pd, "PDFTR-UST")

    print("\n".join(log))

    if not be5y5y:
        raise SystemExit("FATAL: T5YIFR unavailable — Board 1 carries the "
                         "framework's core argument, refusing to bake without it.")

    raw = {
        "be5": be5, "be10": be10, "be5y5y": be5y5y, "dgs30": dgs30, "dfii30": dfii30,
        "sofr": sofr, "iorb": iorb, "effr": effr, "tb4wk": tb4wk, "rrpaw": rrpaw,
        "ndfa": ndfa, "dxy": dxy, "foroff": foroff, "dgs10": dgs10, "dgs2": dgs2,
        "pos": pos, "ftd": ftd, "ftr": ftr,
    }
    # True latest observation, before weekly snapping. The weekly grid labels
    # each week by its Friday, so a Tuesday print rolls the last grid label
    # into the future — that label must not be reported as the as-of date.
    latest_obs = max(max(s) for s in raw.values() if s)

    # Master weekly grid: breakeven history defines the span
    w = {k: weekly(v) for k, v in raw.items()}

    start = min(w["be5y5y"])
    end   = max(max(s) for s in w.values() if s)
    grid, d = [], datetime.date.fromisoformat(to_friday(start))
    end_d = datetime.date.fromisoformat(to_friday(end))
    while d <= end_d:
        grid.append(d.isoformat())
        d += datetime.timedelta(days=7)

    a = {k: align(v, grid) for k, v in w.items()}
    # Foreign official is monthly with a ~2-month publication lag; cap the carry
    # at 20 weeks so a discontinued release cannot look live.
    a["foroff"] = align_stale_capped(w["foroff"], grid, 20)

    print(f"\nWeekly grid: {len(grid)} weeks, {grid[0]} to {grid[-1]}")

    board1 = build_board1(grid, a)
    board2 = build_board2(grid, a)
    board3 = build_board3(grid, a)
    board4 = build_board4(grid, a, board1, board2, board3)

    return {
        "as_of": latest_obs,
        "week_ending": grid[-1],
        "updated_utc": datetime.datetime.now(datetime.timezone.utc)
                               .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dates": grid,
        "board1": board1,
        "board2": board2,
        "board3": board3,
        "board4": board4,
        "meta": build_meta(grid, a, board2),
    }


# ── BOARD 1 — BREAKEVEN CURVE ──────────────────────────────────────────────────
def build_board1(grid, a):
    """Is inflation a regime change, or a front-loaded supply shock?

    The payload is the anchor spread (5y5y forward minus 5y spot), not the
    levels. In 2021-22 the front end went vertical while the forward barely
    moved — the market was pricing a shock passing through, not a new inflation
    regime, which is exactly what happened. A forward that moves on its own is
    the thing that would signal a genuine regime change.
    """
    be5, be10, be5y5y = a["be5"], a["be10"], a["be5y5y"]
    be30 = diff_series(a["dgs30"], a["dfii30"])
    anchor = diff_series(be5y5y, be5)

    fwd_ref   = expanding_median(be5y5y)      # stable long-run anchor
    fwd_dev   = diff_series(be5y5y, fwd_ref)  # forward vs its own anchor
    fwd_chg6m = change_n(be5y5y, 26)          # 26 weeks ≈ 6 months
    anchor_z  = rolling_z(anchor, Z_WIN_LONG)

    # Inflation-axis score. Three terms:
    #   deviation  is the forward away from its own long-run anchor?
    #   momentum   is the forward moving on its own?
    #   shock      is the move front-loaded rather than a regime shift?
    #
    # The shock term is ONE-SIDED on purpose. A deeply negative anchor spread
    # (front end far above the forward, as in 2022) is strong evidence the
    # market is pricing a shock passing through, so it pushes toward
    # elimination. A POSITIVE anchor spread is not the mirror image — it
    # usually means the front end has collapsed in a deflation scare, as in
    # November 2008 when the 5-year breakeven printed -1.94%. Letting it push
    # the score up would read the deepest deflation in modern history as an
    # inflation signal, so it is floored at zero.
    score = []
    for dev, mom, anc in zip(fwd_dev, fwd_chg6m, anchor):
        if dev is None and mom is None:
            score.append(None)
            continue
        d = clamp(dev / 0.40) if dev is not None else 0.0
        m = clamp(mom / 0.40) if mom is not None else 0.0
        s = min(0.0, clamp(anc / 0.60)) if anc is not None else 0.0
        score.append(round(clamp(0.40 * d + 0.25 * m + 0.35 * s), 4))

    cur = last_present(score) or 0.0
    if cur > 0.35:
        state, note = "LIVE", ("Forward breakeven is moving on its own — the market "
                               "is repricing the inflation regime, not just the shock.")
    elif cur < -0.20:
        state, note = "ELIMINATED", ("Forward breakeven anchored and soft. The market "
                                     "is not paying for long-run inflation protection.")
    else:
        state, note = "WATCH", ("Forward breakeven inside its normal band — no regime "
                                "signal either way.")

    return {
        "be5": r4(be5), "be10": r4(be10), "be5y5y": r4(be5y5y), "be30": r4(be30),
        "anchor": r4(anchor), "anchor_z": anchor_z,
        "fwd_ref": r4(fwd_ref), "fwd_dev": r4(fwd_dev), "fwd_chg6m": fwd_chg6m,
        "score": score,
        "current": {
            "be5": last_present(be5), "be10": last_present(be10),
            "be5y5y": last_present(be5y5y), "be30": last_present(be30),
            "anchor": last_present(anchor), "fwd_chg6m": last_present(fwd_chg6m),
            "fwd_ref": last_present(fwd_ref),
        },
        "verdict": {"state": state, "score": round(cur, 4), "note": note},
    }


# ── BOARD 2 — COLLATERAL & DEALER CAPACITY ─────────────────────────────────────
def build_board2(grid, a):
    """The free reconstruction of what a swap spread would tell you.

    Five components, each z-scored so that POSITIVE = TIGHTER:
      sofr_iorb   secured repo above the administered floor = collateral bid
      sofr_effr   secured above unsecured = balance-sheet scarcity
      bill_floor  bills trading through the RRP floor = collateral scarcity
                  (sign flipped: a NEGATIVE spread is the stress signal)
      dealer_pos  dealer Treasury inventory — a balance-sheet capacity read
      fails       settlement fails = collateral genuinely unavailable
    """
    sofr_iorb = diff_series(a["sofr"], a["iorb"])
    sofr_effr = diff_series(a["sofr"], a["effr"])
    bill_floor = diff_series(a["tb4wk"], a["rrpaw"])
    dealer_pos = a["pos"]
    fails = [None if (x is None or y is None) else x + y
             for x, y in zip(a["ftd"], a["ftr"])]

    z = {
        "sofr_iorb":  rolling_z(sofr_iorb, Z_WIN_MID),
        "sofr_effr":  rolling_z(sofr_effr, Z_WIN_MID),
        # Bills BELOW the floor is the stress state, so invert.
        "bill_floor": [None if v is None else -v
                       for v in rolling_z(bill_floor, Z_WIN_MID)],
        # Larger dealer inventory = more balance sheet absorbed = tighter capacity.
        "dealer_pos": rolling_z(dealer_pos, Z_WIN_MID),
        "fails":      rolling_z(fails, Z_WIN_MID),
    }

    composite, n_comp = [], []
    for i in range(len(grid)):
        vals = [z[k][i] for k in z if z[k][i] is not None]
        n_comp.append(len(vals))
        # Three of five is the minimum that makes a composite meaningful.
        composite.append(round(statistics.fmean(vals), 4) if len(vals) >= 3 else None)

    cur = last_present(composite) or 0.0
    if cur > 0.5:
        state, note = "TIGHTENING", ("Collateral and dealer capacity are under "
                                     "pressure — money is tighter than policy says.")
    elif cur < -0.5:
        state, note = "EASING", "Funding and collateral conditions are loose."
    else:
        state, note = "NEUTRAL", "Funding conditions near their trailing norm."

    return {
        "sofr_iorb": r4(sofr_iorb), "sofr_effr": r4(sofr_effr),
        "bill_floor": r4(bill_floor), "dealer_pos": r4(dealer_pos),
        "fails": r4(fails),
        "z": z, "composite": composite, "n_components": n_comp,
        "current": {
            "sofr_iorb": last_present(sofr_iorb), "sofr_effr": last_present(sofr_effr),
            "bill_floor": last_present(bill_floor), "dealer_pos": last_present(dealer_pos),
            "fails": last_present(fails), "n_components": n_comp[-1],
        },
        "verdict": {"state": state, "score": round(cur, 4), "note": note},
    }


# ── BOARD 3 — EURODOLLAR QUANTITY PROXY ────────────────────────────────────────
def build_board3(grid, a):
    """How much offshore dollar funding is actually being created?

    NDFA is US banks' net position with their own foreign offices. Rising = the
    offshore system is being funded; falling = it is being pulled back. Paired
    with the broad dollar, because a rising dollar IS eurodollar scarcity in
    Snider's reading rather than a separate fact about currencies.
    """
    ndfa, dxy, foroff = a["ndfa"], a["dxy"], a["foroff"]

    # NDFA is a NET position: it crosses zero 48 times over the sample and runs
    # from -165bn to +750bn. A year-over-year PERCENT change on it is garbage —
    # it blows past 70,000% either side of a zero crossing. The 52-week level
    # change in billions is well defined across sign changes, and the rolling
    # z-score below handles the fact that a given dollar swing means less as
    # the banking system grows.
    ndfa_chg52 = change_n(ndfa, 52)
    dxy_yoy    = yoy_pct(dxy)
    foroff_yoy = yoy_pct(foroff)

    # Positive composite = eurodollar EXPANSION (easier). Dollar strength is a
    # drain, so it enters negatively.
    z_ndfa = rolling_z(ndfa_chg52, Z_WIN_LONG)
    z_dxy  = rolling_z(dxy_yoy, Z_WIN_LONG)
    composite = []
    for zn, zd in zip(z_ndfa, z_dxy):
        vals = [v for v in (zn, None if zd is None else -zd) if v is not None]
        composite.append(round(statistics.fmean(vals), 4) if vals else None)

    cur = last_present(composite) or 0.0
    if cur < -0.5:
        state, note = "CONTRACTING", ("Offshore dollar funding is being pulled back "
                                      "while the dollar bids — classic eurodollar squeeze.")
    elif cur > 0.5:
        state, note = "EXPANDING", "Offshore dollar funding is growing."
    else:
        state, note = "FLAT", "Offshore dollar funding near its trailing norm."

    return {
        "ndfa": r4(ndfa), "ndfa_chg52": r4(ndfa_chg52),
        "dxy": r4(dxy), "dxy_yoy": r4(dxy_yoy),
        "foroff": r4(foroff), "foroff_yoy": r4(foroff_yoy),
        "z_ndfa": z_ndfa, "z_dxy": z_dxy, "composite": composite,
        "current": {
            "ndfa": last_present(ndfa), "ndfa_chg52": last_present(ndfa_chg52),
            "dxy": last_present(dxy), "dxy_yoy": last_present(dxy_yoy),
            "foroff": last_present(foroff),
        },
        "verdict": {"state": state, "score": round(cur, 4), "note": note},
    }


# ── BOARD 4 — MOSAIC ───────────────────────────────────────────────────────────
def build_board4(grid, a, b1, b2, b3):
    """Which quadrants survive the signals?

    Growth axis follows Friedman's interest-rate fallacy as Snider applies it:
    LOW and FALLING nominal yields mean tight money and weak growth, not easy
    money. So the curve's level enters positively — a depressed 10-year is a
    negative growth signal, not a stimulative one.
    """
    dgs10, dgs2 = a["dgs10"], a["dgs2"]
    slope = diff_series(dgs10, dgs2)
    level_z = rolling_z(dgs10, Z_WIN_LONG)
    slope_z = rolling_z(slope, Z_WIN_LONG)

    infl_score = b1["score"]
    coll = b2["composite"]
    euro = b3["composite"]

    growth = []
    for i in range(len(grid)):
        parts = []
        if level_z[i] is not None:
            parts.append(clamp(level_z[i] / 1.5))          # low yields = weak growth
        if coll[i] is not None:
            parts.append(clamp(-coll[i] / 1.5))            # tight collateral = weak
        if euro[i] is not None:
            parts.append(clamp(euro[i] / 1.5))             # contracting euro$ = weak
        growth.append(round(clamp(statistics.fmean(parts)), 4) if parts else None)

    g = last_present(growth) or 0.0
    f = last_present(infl_score) or 0.0

    if g >= 0 and f >= 0:
        quad = "INFLATIONARY BOOM"
    elif g >= 0 and f < 0:
        quad = "SWEET SPOT"
    elif g < 0 and f >= 0:
        quad = "STAGFLATION"
    else:
        quad = "DEFLATIONARY BUST"

    # Conviction. Both axes sitting near zero is not a quadrant call, it is the
    # absence of one, and the board must say so rather than dress a coin-flip up
    # as a regime. Below the floor nothing is promoted to "live" — the framework
    # earns its keep by eliminating quadrants, not by always naming a winner.
    conviction = round(clamp((abs(g) + abs(f)) / 0.80, 0.0, 1.0), 4)
    decisive = conviction >= 0.35

    # Board 1 is the eliminator: when the forward breakeven is confidently
    # anchored, both inflation quadrants are dead regardless of the growth read.
    # That elimination stands on its own and does not need overall conviction.
    status = {}
    infl_dead = f < -0.20
    for q in QUADRANTS:
        is_infl = q in ("INFLATIONARY BOOM", "STAGFLATION")
        if infl_dead and is_infl:
            status[q] = "dead"
        elif q == quad and decisive:
            status[q] = "live"
        else:
            status[q] = "watch"

    votes = [
        _vote("Breakeven curve", b1["verdict"]["state"], "inflation",
              1 if f >= 0 else -1, b1["verdict"]["note"]),
        _vote("Collateral & dealers", b2["verdict"]["state"], "growth",
              -1 if (last_present(coll) or 0) > 0 else 1, b2["verdict"]["note"]),
        _vote("Eurodollar quantity", b3["verdict"]["state"], "growth",
              1 if (last_present(euro) or 0) >= 0 else -1, b3["verdict"]["note"]),
        _vote("Yield curve", _curve_state(level_z, slope_z), "growth",
              1 if (last_present(level_z) or 0) >= 0 else -1,
              "Curve level read through the interest-rate fallacy: a depressed "
              "10-year is tight money, not stimulus."),
    ]

    # Agreement: how many votes point the same way as the resolved quadrant?
    want_g = 1 if g >= 0 else -1
    want_f = 1 if f >= 0 else -1
    confirms = 0
    for v in votes:
        target = want_f if v["axis"] == "inflation" else want_g
        v["confirms"] = (v["dir"] == target)
        confirms += v["confirms"]

    return {
        "dgs10": r4(dgs10), "dgs2": r4(dgs2), "slope": r4(slope),
        "level_z": level_z, "slope_z": slope_z,
        "growth": growth, "inflation": infl_score,
        "quadrant": quad, "status": status, "votes": votes,
        "agreement": round(confirms / len(votes), 4),
        "conviction": conviction, "decisive": decisive,
        "current": {"growth": round(g, 4), "inflation": round(f, 4),
                    "dgs10": last_present(dgs10), "slope": last_present(slope)},
    }


def _vote(signal, read, axis, direction, note):
    return {"signal": signal, "read": read, "axis": axis,
            "dir": direction, "note": note}


def _curve_state(level_z, slope_z):
    lz = last_present(level_z) or 0.0
    sz = last_present(slope_z) or 0.0
    if lz < -0.5 and sz > 0.5:
        return "BULL STEEPENING"
    if lz < -0.5:
        return "LOW / TIGHT"
    if sz < -0.5:
        return "FLATTENING"
    return "NEUTRAL"


# ── METADATA ───────────────────────────────────────────────────────────────────
def build_meta(grid, a, b2):
    def first_date(key):
        for i, v in enumerate(a[key]):
            if v is not None:
                return grid[i]
        return None

    return {
        "coverage": {
            "board1_start": first_date("be5y5y"),
            "board2_start": next((grid[i] for i, n in enumerate(b2["n_components"])
                                  if n >= 3), None),
            "board2_full":  next((grid[i] for i, n in enumerate(b2["n_components"])
                                  if n >= 5), None),
            "board3_start": first_date("ndfa"),
        },
        "sources": [
            "FRED: T5YIE, T10YIE, T5YIFR, DGS30, DFII30, DGS10, DGS2",
            "FRED: SOFR, IORB, EFFR, DTB4WK, RRPONTSYAWARD",
            "FRED: NDFACBW027SBOG, DTWEXBGS, FORTREASPOS99990",
            "NY Fed primary dealers: PDPOSGST-TOT, PDFTD-UST, PDFTR-UST",
        ],
        "notes": (
            "Interest-rate swap spreads — Snider's primary signal — are not "
            "freely available: FRED's DSWP series ended 2016-10-28 and live "
            "swap rates are licence-restricted. Board 2 reconstructs the same "
            "underlying information (dealer capacity, collateral scarcity) "
            "from official sources."
        ),
    }


# ── MAIN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    payload = build()

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    b4 = payload["board4"]
    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"\nWrote {OUT_PATH} ({size_kb:.0f} KB)")
    print(f"  Board 1 breakevens : {payload['board1']['verdict']['state']}")
    print(f"  Board 2 collateral : {payload['board2']['verdict']['state']}")
    print(f"  Board 3 eurodollar : {payload['board3']['verdict']['state']}")
    print(f"  Board 4 quadrant   : {b4['quadrant']}"
          f"{'' if b4['decisive'] else ' (LOW CONVICTION)'} "
          f"| agreement {b4['agreement']:.0%}"
          f" | conviction {b4['conviction']:.0%}")
