#!/usr/bin/env python3
"""
Attribution for the Heat Map Corroboration allocation.

Answers, before any tuning: does ANY single framework carry allocation information,
and does whatever we find survive on data the tuning never touched?

  TRAIN  2016-03 .. 2021-12   (23 rebalances)  — where any tinkering is allowed
  TEST   2022-03 .. 2026-06   (19 rebalances)  — touched once, at the end

Each variant is scored against the neutral base-weight book on the SAME universe,
so the number reported is the value added by the signal, not by the asset menu.
"""
import sys, math, datetime as dt, bisect
import backtest_heatmap as B

SPLIT = "2022-01-01"

def build_world():
    sn = B.load_snider()
    liq_d, liq_z = B.load_acumen_expanding_z()
    bl_d, bl_v = B.load_btc_liquidity()
    dale_G, dale_I = B.build_dale()
    fgrid, fhist = B.build_flow_history()
    px = {}
    for (label, grp, etf, *_) in B.CLASSES:
        sym = "BTC-USD" if etf == "BTC" else etf
        d, c, v = B.yahoo(sym); px[label] = (d, c)
    for b in ("SPY", "IEF"):
        d, c, v = B.yahoo(b); px["_" + b] = (d, c)
    return sn, (liq_d, liq_z), (bl_d, bl_v), (dale_G, dale_I), (fgrid, fhist), px

def score_subset(d, world, keep, k_coef, floor_frac):
    """Same engine as the live page, but only the frameworks named in `keep` vote."""
    sn, (liq_d, liq_z), (bl_d, bl_v), (dale_G, dale_I), (fgrid, fhist), px = world
    sd, sg, si = sn
    s_g, s_i = B.at(sd, sg, d), B.at(sd, si, d)
    dg_raw, di_raw = B.dale_at(dale_G, d), B.dale_at(dale_I, d)
    dg = B.clamp(dg_raw / 2.5, -1, 1) if dg_raw is not None else None
    di = B.clamp(di_raw / 2.5, -1, 1) if di_raw is not None else None
    lz = B.at(liq_d, liq_z, d)
    fi = bisect.bisect_right(fgrid, d) - 1
    fl = {n: (fhist[n][fi] if fi >= 0 else None) for n in B.FLOW_NODES}
    thrust = B.btc_thrust_at(bl_d, bl_v, d)

    out = {}
    for (label, grp, etf, base, bg, bi, blq, node) in B.CLASSES:
        votes = {}
        if "snider" in keep and s_g is not None:
            votes["snider"] = (math.tanh(1.8 * (bg * s_g + bi * s_i)), 0.30)
        if "dale" in keep and dg is not None:
            votes["dale"] = (math.tanh(1.4 * (bg * dg + bi * di)), 0.37)
        if "liq" in keep and lz is not None:
            votes["liq"] = (math.tanh(1.1 * blq * lz), B.clamp(abs(lz) / 1.5, 0, 1))
        if "flows" in keep and node and fl.get(node) is not None:
            nv = fl[node]
            votes["flows"] = (math.tanh(9 * nv), B.clamp(abs(nv) / 0.10, 0, 1))
        if "btc" in keep and label == "Bitcoin" and thrust is not None:
            v = 0.85 if thrust >= B.THRUST else (0.30 if thrust > 0 else -0.45)
            votes["btc"] = (v, 0.75)

        num = den = 0.0; voters = []; possible = 0
        for kk, (v, w) in votes.items():
            possible += 1
            if abs(v) < B.ABSTAIN or w <= 0: continue
            ww = w * B.PRIOR[kk]
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

def run(world, qs, keep, k_coef=2.0, floor=0.0):
    px = world[5]
    def ret(lbl, a, b):
        d, c = px[lbl]; pa, pb = B.at(d, c, a), B.at(d, c, b)
        return (pb / pa - 1) if (pa and pb and pa > 0) else 0.0
    books = [score_subset(q, world, keep, k_coef, floor) for q in qs]
    cur = [(qs[0], 1.0)]
    for k in range(len(qs) - 1):
        r = sum(w * ret(l, qs[k], qs[k + 1]) for l, w in books[k].items())
        cur.append((qs[k + 1], cur[-1][1] * (1 + r)))
    return cur, books

def neutral_curve(world, qs):
    px = world[5]
    tot = sum(c[3] for c in B.CLASSES)
    wts = {c[0]: c[3] / tot for c in B.CLASSES}
    def ret(lbl, a, b):
        d, c = px[lbl]; pa, pb = B.at(d, c, a), B.at(d, c, b)
        return (pb / pa - 1) if (pa and pb and pa > 0) else 0.0
    cur = [(qs[0], 1.0)]
    for k in range(len(qs) - 1):
        r = sum(w * ret(l, qs[k], qs[k + 1]) for l, w in wts.items())
        cur.append((qs[k + 1], cur[-1][1] * (1 + r)))
    return cur

def stats(cur):
    p = B.perf(cur); return p["cagr"], p["vol"], p["mdd"], p["sharpe"]

def hit_rate(cur, base):
    """Share of quarters the variant beat the neutral book."""
    a = [cur[i][1] / cur[i-1][1] - 1 for i in range(1, len(cur))]
    b = [base[i][1] / base[i-1][1] - 1 for i in range(1, len(base))]
    n = min(len(a), len(b))
    return sum(1 for i in range(n) if a[i] > b[i]) / n if n else 0

def main():
    print("Building world (cached) …")
    world = build_world()
    px = world[5]
    allq = B.quarter_ends(B.START, dt.date.today().isoformat())
    allq = [q for q in allq if any(d >= q for d in px["Technology"][0])]
    train = [q for q in allq if q < SPLIT]
    test  = [q for q in allq if q >= SPLIT]
    print(f"  TRAIN {train[0]} .. {train[-1]}  n={len(train)}")
    print(f"  TEST  {test[0]} .. {test[-1]}  n={len(test)}\n")

    variants = [
        ("Snider only",    {"snider"}),
        ("Dale only",      {"dale"}),
        ("Liquidity only", {"liq"}),
        ("Flows only",     {"flows"}),
        ("All four",       {"snider", "dale", "liq", "flows", "btc"}),
    ]

    for tag, qs in (("TRAIN", train), ("TEST", test)):
        base = neutral_curve(world, qs)
        bc, bv, bd, bs = stats(base)
        print(f"── {tag}  ({qs[0]} .. {qs[-1]}) ─────────────────────────────")
        print(f"{'':<18}{'CAGR':>8}{'vs neut':>9}{'Vol':>7}{'MaxDD':>8}{'Ret/Vol':>8}{'HitRate':>9}")
        print(f"{'Neutral base':<18}{bc*100:>7.1f}%{'—':>9}{bv*100:>6.1f}%{bd*100:>7.1f}%{bs:>8.2f}{'—':>9}")
        for name, keep in variants:
            cur, _ = run(world, qs, keep)
            c, v, d, s = stats(cur)
            print(f"{name:<18}{c*100:>7.1f}%{(c-bc)*100:>+8.1f}%{v*100:>6.1f}%"
                  f"{d*100:>7.1f}%{s:>8.2f}{hit_rate(cur,base)*100:>8.0f}%")
        print()

if __name__ == "__main__":
    sys.exit(main() or 0)
