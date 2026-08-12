#!/usr/bin/env python3
"""
Backtest the Heat Map Corroboration allocation over ~10 years, quarterly rebalanced.

Reproduces the live page's scoring engine (indicators/macro/heatmap_corroboration.html)
at every quarter-end using only data available at that date, then holds the resulting
book until the next rebalance.

Inputs, and how each is reconstructed historically:
  Snider    board4 growth/inflation, straight from snider_data.json (trailing-window
            by construction, per that page's own guarantee).
  Dale      rebuilt from FRED year-over-year z-scores against the 2015-19 baseline,
            the same construction backtest_regime.py uses.
  Liquidity Acumen global liquidity, re-z-scored on an EXPANDING window. The live page
            uses full-sample 2015-present mean/std, which would let 2016 see 2024.
  Flows     six node scores rebuilt from Yahoo weekly volume and closes for the Capital
            Flows ticker set, reproducing computeCycleScores() exactly.
  BTC       13-week growth in M2x100/DXY against the +3.73% thrust threshold, with a
            56-day M2 publication lag applied.

Known limitations, all reported rather than papered over:
  * The betas, priors and thresholds were chosen while looking at current readings.
    This is therefore partly IN-SAMPLE and will flatter itself.
  * FRED serves the current vintage, not point-in-time. Real-economy series are revised,
    so Dale's leg is approximated with hindsight-clean data.
  * The 2015-19 Dale baseline spans future dates for rebalances before 2020. It scales
    the z-scores rather than setting their direction, but it is lookahead.
  * Land/Farmland is excluded: no clean tradeable 10-year series. Weights renormalise.
"""
import os, sys, json, re, math, time, bisect, datetime as dt
import requests

FRED_KEY = os.environ.get("FRED_API_KEY", "824b29c5afa52f3fc7c6e7dc4925aebb")
UA = {"User-Agent": "Mozilla/5.0"}
HERE = os.path.dirname(os.path.abspath(__file__))

START = "2016-01-01"          # ~10 years of quarterly rebalances
DALE_BASELINE = ("2015-01-01", "2019-12-31")
THRUST = 0.0373               # top-quartile 13-week liquidity growth
ABSTAIN = 0.05
PRIOR = {"snider": 0.30, "dale": 0.30, "liq": 0.25, "flows": 0.15, "btc": 0.20}

# ── Asset universe: mirrors the live page minus Land/Farmland ──────────────
# (label, group, etf, base, growth beta, inflation beta, liquidity beta, flow node)
CLASSES = [
 ("Cash / T-Bills",     "Cash & duration", "BIL", 9,  -0.30, -0.40, -0.30, "Fixed Income"),
 ("Treasurys 3-7y",     "Cash & duration", "IEF", 7,  -0.50, -0.50, -0.10, "Fixed Income"),
 ("Treasurys 20y+",     "Cash & duration", "TLT", 5,  -0.80, -0.80, -0.20, "Fixed Income"),
 ("TIPS",               "Cash & duration", "TIP", 5,  -0.20,  0.70,  0.00, "Fixed Income"),
 ("High Yield",         "Credit",          "HYG", 4,   0.70,  0.10,  0.60, None),
 ("Investment Grade",   "Credit",          "LQD", 5,  -0.10, -0.45,  0.20, None),
 ("Technology",         "US equities",     "XLK", 8,   0.80, -0.40,  0.70, "Speculation"),
 ("Financials",         "US equities",     "XLF", 5,   0.70,  0.20,  0.30, "Cyclical"),
 ("Healthcare",         "US equities",     "XLV", 4.5, -0.30, 0.00, -0.10, "Defensive"),
 ("Consumer Cyclical",  "US equities",     "XLY", 4,   0.90, -0.30,  0.50, "Cyclical"),
 ("Communication Svcs", "US equities",     "VOX", 3.5, 0.60, -0.30,  0.50, "Speculation"),
 ("Industrials",        "US equities",     "XLI", 4,   0.80,  0.20,  0.30, "Cyclical"),
 ("Consumer Defensive", "US equities",     "XLP", 3.5, -0.40, 0.20, -0.10, "Defensive"),
 ("Energy",             "US equities",     "XLE", 3,   0.40,  0.90,  0.20, "Commodities"),
 ("Utilities",          "US equities",     "XLU", 2,  -0.40, -0.10, -0.20, "Defensive"),
 ("Basic Materials",    "US equities",     "XLB", 1.5, 0.60,  0.60,  0.30, "Commodities"),
 ("Real Estate",        "US equities",     "VNQ", 1.5, 0.30,  0.30,  0.60, "Defensive"),
 ("Intl Developed",     "International",   "EFA", 6,   0.60,  0.10,  0.50, "Cyclical"),
 ("Emerging Markets",   "International",   "EEM", 4,   0.80,  0.20,  0.90, "Cyclical"),
 ("Commodities Broad",  "Commodities",     "DBC", 3,   0.50,  0.90,  0.30, "Commodities"),
 ("Industrial Metals",  "Commodities",     "DBB", 2.5, 0.80,  0.70,  0.40, "Commodities"),
 ("Agriculture",        "Commodities",     "DBA", 2.5, 0.10,  0.80,  0.10, "Commodities"),
 ("Precious Metals",    "Real assets",     "GLD", 6,  -0.20,  0.70,  0.50, "Debasement"),
 ("Bitcoin",            "Digital",         "BTC", 4,   0.50,  0.40,  1.00, "Debasement"),
 ("US Dollar",          "Currency",        "UUP", 4,  -0.10, -0.20, -0.70, "Fixed Income"),
]

FLOW_NODES = {
  "Debasement":  ["BTC-USD", "GLD"],
  "Cyclical":    ["XLY", "XLF", "IWM", "SPY"],
  "Speculation": ["MSTR", "QQQ", "IGV"],
  "Commodities": ["DBC", "XLE", "DBA"],
  "Defensive":   ["XLP", "VYM", "XLV", "MOAT"],
  "Fixed Income":["SHV", "TLT", "IEF"],
}

# ══════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════
_cache = {}
CACHE_FILE = os.path.join(HERE, ".backtest_cache.json")
_disk = {}
if os.path.exists(CACHE_FILE):
    try: _disk = json.load(open(CACHE_FILE, encoding="utf-8"))
    except Exception: _disk = {}

def _save_disk():
    try: json.dump(_disk, open(CACHE_FILE, "w", encoding="utf-8"))
    except Exception as e: print(f"  ! cache write: {e}", file=sys.stderr)

def yahoo(sym, rng="11y", interval="1wk"):
    """Weekly adjusted closes + volumes. Returns (dates, closes, volumes)."""
    key = (sym, rng, interval)
    if key in _cache: return _cache[key]
    dk = f"y|{sym}|{rng}|{interval}"
    if dk in _disk:
        _cache[key] = tuple(_disk[dk]); return _cache[key]
    for attempt in range(3):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"range": rng, "interval": interval,
                                     "events": "div,split"},
                             headers=UA, timeout=30)
            if r.status_code != 200: raise RuntimeError(r.status_code)
            res = r.json()["chart"]["result"][0]
            ts = res["timestamp"]
            q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
            out = ([], [], [])
            for i, t in enumerate(ts):
                c = adj[i] if adj[i] is not None else q["close"][i]
                if c is None: continue
                out[0].append(dt.date.fromtimestamp(t).isoformat())
                out[1].append(float(c))
                out[2].append(float(q["volume"][i] or 0))
            _cache[key] = out
            _disk[dk] = list(out); _save_disk()
            return out
        except Exception as e:
            if attempt == 2:
                print(f"    ! {sym}: {e}", file=sys.stderr)
                _cache[key] = ([], [], [])
                return _cache[key]
            time.sleep(1.5)

def fred(sid):
    dk = f"f|{sid}"
    if dk in _disk: return [tuple(x) for x in _disk[dk]]
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": sid, "api_key": FRED_KEY, "file_type": "json",
                             "observation_start": "2012-01-01"}, timeout=30)
    r.raise_for_status()
    out = [(o["date"], float(o["value"])) for o in r.json()["observations"]
           if o["value"] not in (".", "")]
    _disk[dk] = out; _save_disk()
    return out

def at(dates, vals, d):
    """Most recent value at or before date d (point-in-time lookup)."""
    k = bisect.bisect_right(dates, d) - 1
    return vals[k] if k >= 0 else None

def zstats(xs):
    n = len(xs)
    if n < 8: return None, None
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, math.sqrt(v) if v > 0 else None

def clamp(v, lo, hi): return max(lo, min(hi, v))

# ══════════════════════════════════════════════════════════════════════════
# INPUT RECONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════
def load_snider():
    d = json.load(open(os.path.join(HERE, "indicators/macro/snider_data.json"), encoding="utf-8"))
    b4 = d["board4"]
    dates, g, i, cv = d["dates"], b4["growth"], b4["inflation"], b4.get("conviction")
    rows = [(dates[k], g[k], i[k]) for k in range(len(dates))
            if g[k] is not None and i[k] is not None]
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]

def _extract_const(path, name):
    s = open(os.path.join(HERE, path), encoding="utf-8", errors="replace").read()
    m = re.search(r"const\s+" + name + r"\s*=\s*(\{)", s)
    i = m.start(1); depth = 0
    for j in range(i, len(s)):
        if s[j] == "{": depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0: break
    return json.loads(s[i:j + 1])

def load_acumen_expanding_z():
    """Re-z-score liquidity on an expanding window — the live page uses full sample."""
    al = _extract_const("indicators/macro/acumen_liquidity.html", "ACUMEN_LIQUIDITY")
    # lqi_z is already z-scored full-sample; recover a level proxy by using its raw shape.
    src = al.get("lqi_raw") or al["lqi_z"]
    dates, vals = src["dates"], src["values"]
    out_d, out_z = [], []
    for k in range(len(vals)):
        if vals[k] is None: continue
        hist = [v for v in vals[:k + 1] if v is not None]
        m, sd = zstats(hist)
        if sd is None: continue
        out_d.append(dates[k]); out_z.append((vals[k] - m) / sd)
    return out_d, out_z

def load_btc_liquidity():
    sd = _extract_const("indicators/btc/btc_liquidity_backtest.html", "STATIC_DATA")
    m2d, m2v = sd["m2"]["dates"], sd["m2"]["values"]
    dxd, dxv = sd["dxy"]["dates"], sd["dxy"]["values"]
    liq_d, liq_v = [], []
    for k in range(len(m2d)):
        dx = at(dxd, dxv, m2d[k])
        if dx: liq_d.append(m2d[k]); liq_v.append(m2v[k] * 100.0 / dx)
    return liq_d, liq_v

def btc_thrust_at(liq_d, liq_v, d):
    """13-week growth in the liquidity index, with a 56-day M2 publication lag."""
    asof = (dt.date.fromisoformat(d) - dt.timedelta(days=56)).isoformat()
    k = bisect.bisect_right(liq_d, asof) - 1
    if k < 1: return None
    target = (dt.date.fromisoformat(liq_d[k]) - dt.timedelta(days=91)).isoformat()
    j = bisect.bisect_right(liq_d, target) - 1
    if j < 0 or liq_v[j] == 0: return None
    return liq_v[k] / liq_v[j] - 1

def build_dale():
    """Growth and inflation z vs the 2015-19 baseline, from FRED year-over-year."""
    GROWTH = ["PAYEMS", "W875RX1", "INDPRO", "CMRMTSPL", "RRSFS"]
    INFLA  = ["PCEPILFE", "CPILFESL"]
    def yoy_z(sids):
        per_series = []
        for sid in sids:
            try: obs = fred(sid)
            except Exception as e:
                print(f"    ! FRED {sid}: {e}", file=sys.stderr); continue
            ds = [o[0] for o in obs]; vs = [o[1] for o in obs]
            yy = [(ds[i], (vs[i] / vs[i - 12] - 1) * 100)
                  for i in range(12, len(vs)) if vs[i - 12]]
            base = [v for d, v in yy if DALE_BASELINE[0] <= d <= DALE_BASELINE[1]]
            m, sd = zstats(base)
            if sd is None: continue
            per_series.append(([d for d, _ in yy], [(v - m) / sd for _, v in yy]))
            time.sleep(0.15)
        return per_series
    return yoy_z(GROWTH), yoy_z(INFLA)

def dale_at(series, d):
    zs = [at(ds, vs, d) for ds, vs in series]
    zs = [z for z in zs if z is not None]
    return sum(zs) / len(zs) if zs else None

def build_flow_history():
    """Rebuild the six node scores weekly, reproducing computeCycleScores()."""
    px = {}
    tickers = sorted({t for v in FLOW_NODES.values() for t in v})
    for t in tickers:
        d, c, v = yahoo(t)
        if d: px[t] = (d, c, v)
        print(f"    flows {t:<9} {len(d):>4} wks")
        time.sleep(0.2)
    # common weekly grid
    grid = sorted({d for t in px for d in px[t][0]})
    hist = {}
    for node, tks in FLOW_NODES.items():
        series = []
        for gi, gd in enumerate(grid):
            tot = cnt = 0
            for t in tks:
                if t not in px: continue
                ds, cs, vs = px[t]
                k = bisect.bisect_right(ds, gd) - 1
                if k < 14: continue
                win = vs[max(0, k - 51):k + 1]
                avg = sum(win) / len(win) or 1
                for m in range(max(1, k - 12), k + 1):
                    if cs[m - 1] == 0: continue
                    ret = cs[m] / cs[m - 1] - 1
                    tot += (vs[m] / avg) * (clamp(ret, -0.10, 0.10) / 0.10)
                    cnt += 1
            series.append(tot / cnt if cnt else 0.0)
        hist[node] = series
    return grid, hist

# ══════════════════════════════════════════════════════════════════════════
# SCORING — mirrors the live page
# ══════════════════════════════════════════════════════════════════════════
def score_all(d, sn, dale_g, dale_i, liq_z, flows, thrust, k_coef, floor_frac):
    sd, sg, si = sn
    s_g, s_i = at(sd, sg, d), at(sd, si, d)
    dg = clamp(dale_g / 2.5, -1, 1) if dale_g is not None else None
    di = clamp(dale_i / 2.5, -1, 1) if dale_i is not None else None
    out = {}
    for (label, grp, etf, base, bg, bi, bl, node) in CLASSES:
        votes = {}
        if s_g is not None:
            votes["snider"] = (math.tanh(1.8 * (bg * s_g + bi * s_i)), 0.30)
        if dg is not None:
            votes["dale"] = (math.tanh(1.4 * (bg * dg + bi * di)), 0.37)
        if liq_z is not None:
            votes["liq"] = (math.tanh(1.1 * bl * liq_z), clamp(abs(liq_z) / 1.5, 0, 1))
        if node and flows.get(node) is not None:
            nv = flows[node]
            votes["flows"] = (math.tanh(9 * nv), clamp(abs(nv) / 0.10, 0, 1))
        if label == "Bitcoin" and thrust is not None:
            v = 0.85 if thrust >= THRUST else (0.30 if thrust > 0 else -0.45)
            votes["btc"] = (v, 0.75)

        num = den = 0.0; voters = []; possible = 0
        for kk, (v, w) in votes.items():
            possible += 1
            if abs(v) < ABSTAIN or w <= 0: continue
            ww = w * PRIOR[kk]
            num += v * ww; den += ww; voters.append(v)
        net = num / den if den else 0.0
        if voters:
            agree = sum(1 for v in voters if (v > 0) == (net > 0)) / len(voters)
            corrob = agree * math.sqrt(len(voters) / possible)
        else:
            corrob = 0.0
        w = base * (1 + k_coef * net * corrob)
        out[label] = max(base * floor_frac, w) if floor_frac else max(0.0, w)
    tot = sum(out.values()) or 1
    return {k: v / tot for k, v in out.items()}

# ══════════════════════════════════════════════════════════════════════════
def quarter_ends(start, end):
    out, y = [], int(start[:4])
    while y <= int(end[:4]):
        for mo, dd in ((3, 31), (6, 30), (9, 30), (12, 31)):
            d = f"{y}-{mo:02d}-{dd:02d}"
            if start <= d <= end: out.append(d)
        y += 1
    return out

def perf(curve):
    if len(curve) < 2: return {}
    total = curve[-1][1] / curve[0][1]
    yrs = (dt.date.fromisoformat(curve[-1][0]) - dt.date.fromisoformat(curve[0][0])).days / 365.25
    rets = [curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve))]
    n = len(rets); mu = sum(rets) / n
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1)) if n > 1 else 0
    ann_vol = sd * math.sqrt(4)
    peak = -1e9; mdd = 0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    cagr = total ** (1 / yrs) - 1 if yrs > 0 else 0
    return {"cagr": cagr, "vol": ann_vol, "mdd": mdd,
            "sharpe": (cagr / ann_vol) if ann_vol else 0, "total": total - 1}

def main():
    print("Loading inputs …")
    sn = load_snider();                       print(f"  snider    {sn[0][0]} -> {sn[0][-1]}  n={len(sn[0])}")
    liq_d, liq_z = load_acumen_expanding_z(); print(f"  liquidity {liq_d[0]} -> {liq_d[-1]}  n={len(liq_d)} (expanding z)")
    bl_d, bl_v = load_btc_liquidity();        print(f"  btc liq   {bl_d[0]} -> {bl_d[-1]}  n={len(bl_d)}")
    print("  dale — rebuilding from FRED …")
    dale_G, dale_I = build_dale();            print(f"    growth series {len(dale_G)}, inflation series {len(dale_I)}")
    print("  flows — rebuilding from Yahoo …")
    fgrid, fhist = build_flow_history();      print(f"    flows grid {fgrid[0]} -> {fgrid[-1]}  n={len(fgrid)}")

    print("Loading asset prices …")
    px = {}
    for (label, grp, etf, *_ ) in CLASSES:
        sym = "BTC-USD" if etf == "BTC" else etf
        d, c, v = yahoo(sym)
        px[label] = (d, c)
        print(f"    {label:<20} {sym:<9} {len(d):>4} wks  {d[0] if d else '-'}")
        time.sleep(0.2)
    for b in ("SPY", "IEF"):
        d, c, v = yahoo(b); px["_" + b] = (d, c)

    qs = quarter_ends(START, dt.date.today().isoformat())
    qs = [q for q in qs if any(dd >= q for dd in px["Technology"][0])]
    print(f"\nRebalances: {len(qs)}  ({qs[0]} -> {qs[-1]})\n")

    books = {"signal": [], "signal_livecfg": [], "neutral": []}
    for q in qs:
        fl = {n: (fhist[n][bisect.bisect_right(fgrid, q) - 1]
                  if bisect.bisect_right(fgrid, q) - 1 >= 0 else None) for n in FLOW_NODES}
        args = (q, sn, dale_at(dale_G, q), dale_at(dale_I, q),
                at(liq_d, liq_z, q), fl, btc_thrust_at(bl_d, bl_v, q))
        books["signal"].append(score_all(*args, k_coef=2.0, floor_frac=0.0))
        books["signal_livecfg"].append(score_all(*args, k_coef=0.9, floor_frac=0.20))
        tot = sum(c[3] for c in CLASSES)
        books["neutral"].append({c[0]: c[3] / tot for c in CLASSES})

    def ret_between(label, a, b):
        d, c = px[label]
        pa, pb = at(d, c, a), at(d, c, b)
        return (pb / pa - 1) if (pa and pb and pa > 0) else 0.0

    curves = {}
    for name, seq in books.items():
        cur = [(qs[0], 1.0)]
        for k in range(len(qs) - 1):
            r = sum(w * ret_between(lbl, qs[k], qs[k + 1]) for lbl, w in seq[k].items())
            cur.append((qs[k + 1], cur[-1][1] * (1 + r)))
        curves[name] = cur
    # benchmarks
    for name, mix in (("SPY", {"_SPY": 1.0}), ("60/40", {"_SPY": 0.6, "_IEF": 0.4})):
        cur = [(qs[0], 1.0)]
        for k in range(len(qs) - 1):
            r = sum(w * ret_between(t, qs[k], qs[k + 1]) for t, w in mix.items())
            cur.append((qs[k + 1], cur[-1][1] * (1 + r)))
        curves[name] = cur

    order = ["signal", "signal_livecfg", "neutral", "60/40", "SPY"]
    names = {"signal": "Heat map (exit rule)", "signal_livecfg": "Heat map (live page cfg)",
             "neutral": "Neutral base weights", "60/40": "60/40 SPY-IEF", "SPY": "SPY buy & hold"}

    years = sorted({q[:4] for q in qs})
    print("YEARLY RETURN, %")
    print(f"{'':<26}" + "".join(f"{y[2:]:>7}" for y in years))
    for nm in order:
        cur = dict(curves[nm]); ds = [d for d, _ in curves[nm]]
        row = ""
        for y in years:
            ys = [d for d in ds if d[:4] == y]
            if not ys: row += f"{'—':>7}"; continue
            prior = [d for d in ds if d < ys[0]]
            a = cur[prior[-1]] if prior else cur[ys[0]]
            row += f"{(cur[ys[-1]] / a - 1) * 100:>7.1f}"
        print(f"{names[nm]:<26}{row}")

    print("\nSUMMARY")
    print(f"{'':<26}{'CAGR':>8}{'Vol':>8}{'MaxDD':>8}{'Ret/Vol':>9}{'Total':>9}")
    for nm in order:
        p = perf(curves[nm])
        print(f"{names[nm]:<26}{p['cagr']*100:>7.1f}%{p['vol']*100:>7.1f}%"
              f"{p['mdd']*100:>7.1f}%{p['sharpe']:>9.2f}{p['total']*100:>8.1f}%")

    # ── Diagnostics: is the signal actually moving the book at all? ──────
    print("\nSIGNAL DIAGNOSTICS")
    for nm in ("signal", "signal_livecfg"):
        seq = books[nm]; neu = books["neutral"][0]
        dev = [sum(abs(b[k] - neu[k]) for k in b) / 2 for b in seq]      # active share
        turn = [sum(abs(seq[i][k] - seq[i-1][k]) for k in seq[i]) / 2
                for i in range(1, len(seq))]
        zeros = [sum(1 for v in b.values() if v < 0.001) for b in seq]
        print(f"  {names[nm]:<26} active share avg {sum(dev)/len(dev)*100:5.1f}%  "
              f"max {max(dev)*100:5.1f}%   turnover/qtr {sum(turn)/len(turn)*100:5.1f}%  "
              f"zero-weight tiles avg {sum(zeros)/len(zeros):.1f}")
    # widest and narrowest tiles under the exit rule
    seq = books["signal"]
    rng = {k: (min(b[k] for b in seq), max(b[k] for b in seq)) for k in seq[0]}
    wide = sorted(rng.items(), key=lambda kv: kv[1][0] - kv[1][1])[:4]
    print("  most-varying tiles (min -> max weight):")
    for k, (lo, hi) in wide:
        print(f"    {k:<20} {lo*100:5.1f}% -> {hi*100:5.1f}%")

    print("\nCaveats: parameters chosen with sight of current readings (partly in-sample);")
    print("FRED current-vintage data (revisions); Dale 2015-19 baseline is lookahead pre-2020;")
    print("Land/Farmland excluded; gross of tax and transaction costs.")

if __name__ == "__main__":
    sys.exit(main() or 0)
