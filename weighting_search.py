#!/usr/bin/env python3
"""
Weighting-strategy search for the Heat Map allocation, Capital Flows removed.

Method that keeps this honest:
  * Every variant is scored on TRAIN (2016-03..2021-12) and on TEST (2022-03..2026-06).
  * The full table is printed, not just the winner, so the selection is visible.
  * The decisive statistic is the RANK CORRELATION between train and test ordering.
    If picking the best strategy on train does not predict test, then "the best
    weighting strategy" is an artefact of the sample and no amount of tuning fixes it.

Signal inputs after the drop: Snider, Dale, Liquidity (+ the bitcoin thrust on that
one tile). Flows is gone — it was the only input negative in both halves.
"""
import sys, math, bisect, datetime as dt
import backtest_heatmap as B
import attribution_heatmap as A

KEEP = {"snider", "dale", "liq", "btc"}          # flows dropped
SPLIT = "2022-01-01"

# ── weighting helpers ──────────────────────────────────────────────────────
def trailing_vol(px, label, d, weeks=52):
    ds, cs = px[label]
    k = bisect.bisect_right(ds, d) - 1
    if k < weeks: return None
    win = cs[k - weeks:k + 1]
    rets = [win[i] / win[i - 1] - 1 for i in range(1, len(win)) if win[i - 1]]
    if len(rets) < 10: return None
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) or None

def momentum(px, label, d, look=52, skip=4):
    ds, cs = px[label]
    k = bisect.bisect_right(ds, d) - 1
    if k < look + skip: return None
    a, b = cs[k - look], cs[k - skip]
    return (b / a - 1) if a else None

def norm(w):
    t = sum(w.values()) or 1
    return {k: v / t for k, v in w.items()}

# ── strategy families ──────────────────────────────────────────────────────
def make_weights(kind, d, world, px):
    base = {c[0]: c[3] for c in B.CLASSES}
    labels = list(base)

    if kind == "neutral":
        return norm(base)

    if kind == "equal":
        return norm({l: 1.0 for l in labels})

    if kind == "invvol":
        w = {}
        for l in labels:
            v = trailing_vol(px, l, d)
            w[l] = (1.0 / v) if v else 0.0
        return norm(w) if sum(w.values()) else norm(base)

    if kind == "invvol_base":                     # base weight scaled by 1/vol
        w = {}
        for l in labels:
            v = trailing_vol(px, l, d)
            w[l] = base[l] * (1.0 / v) if v else 0.0
        return norm(w) if sum(w.values()) else norm(base)

    if kind.startswith("mom"):                    # 12-1 momentum tilt on base
        k = float(kind.split("_")[1])
        w = {}
        for l in labels:
            m = momentum(px, l, d)
            w[l] = max(0.0, base[l] * (1 + k * math.tanh(3 * m))) if m is not None else base[l]
        return norm(w)

    if kind.startswith("score"):                  # signal tilt, varying strength
        _, kc, fl = kind.split("_")
        return A.score_subset(d, world, KEEP, float(kc), float(fl))

    if kind.startswith("gate"):                   # liquidity de-risking overlay
        thr, shift = (float(x) for x in kind.split("_")[1:])
        liq_d, liq_z = world[1]
        lz = B.at(liq_d, liq_z, d)
        w = dict(base)
        if lz is not None and lz < thr:
            for l in labels: w[l] *= (1 - shift)
            w["Cash / T-Bills"] += shift * sum(base.values()) * 0.5
            w["Treasurys 3-7y"] += shift * sum(base.values()) * 0.5
        return norm(w)

    if kind.startswith("sgate"):                  # score tilt + liquidity gate
        thr, shift = (float(x) for x in kind.split("_")[1:])
        w = dict(A.score_subset(d, world, KEEP, 2.0, 0.0))
        liq_d, liq_z = world[1]
        lz = B.at(liq_d, liq_z, d)
        if lz is not None and lz < thr:
            for l in w: w[l] *= (1 - shift)
            w["Cash / T-Bills"] += shift * 0.5
            w["Treasurys 3-7y"] += shift * 0.5
        return norm(w)

    raise ValueError(kind)

STRATEGIES = [
    "neutral", "equal", "invvol", "invvol_base",
    "score_0.5_0.2", "score_0.9_0.2", "score_1.5_0.0", "score_2.0_0.0", "score_3.0_0.0",
    "mom_0.5", "mom_1.0",
    "gate_-0.5_0.20", "gate_-0.5_0.40", "gate_-1.0_0.40",
    "sgate_-0.5_0.20", "sgate_-1.0_0.40",
]

LABELS = {
    "neutral": "Neutral base weights", "equal": "Equal weight",
    "invvol": "Inverse volatility", "invvol_base": "Base x inverse vol",
    "score_0.5_0.2": "Score tilt k0.5 fl0.2", "score_0.9_0.2": "Score tilt k0.9 fl0.2 (live)",
    "score_1.5_0.0": "Score tilt k1.5 exit", "score_2.0_0.0": "Score tilt k2.0 exit",
    "score_3.0_0.0": "Score tilt k3.0 exit",
    "mom_0.5": "Momentum tilt 0.5", "mom_1.0": "Momentum tilt 1.0",
    "gate_-0.5_0.20": "Liq gate z<-0.5 shift20", "gate_-0.5_0.40": "Liq gate z<-0.5 shift40",
    "gate_-1.0_0.40": "Liq gate z<-1.0 shift40",
    "sgate_-0.5_0.20": "Score + gate -0.5/20", "sgate_-1.0_0.40": "Score + gate -1.0/40",
}

def curve(kind, world, px, qs):
    def ret(l, a, b):
        ds, cs = px[l]; pa, pb = B.at(ds, cs, a), B.at(ds, cs, b)
        return (pb / pa - 1) if (pa and pb and pa > 0) else 0.0
    books = [make_weights(kind, q, world, px) for q in qs]
    cur = [(qs[0], 1.0)]
    for k in range(len(qs) - 1):
        r = sum(w * ret(l, qs[k], qs[k + 1]) for l, w in books[k].items())
        cur.append((qs[k + 1], cur[-1][1] * (1 + r)))
    turn = [sum(abs(books[i][l] - books[i-1][l]) for l in books[i]) / 2
            for i in range(1, len(books))]
    return cur, (sum(turn) / len(turn) if turn else 0)

def spearman(a, b):
    n = len(a)
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    d2 = sum((ra[a[i]] - rb[b[i]]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))

def main():
    print("Building world (cached) …")
    world = A.build_world(); px = world[5]
    allq = B.quarter_ends(B.START, dt.date.today().isoformat())
    allq = [q for q in allq if any(d >= q for d in px["Technology"][0])]
    train = [q for q in allq if q < SPLIT]
    test  = [q for q in allq if q >= SPLIT]
    print(f"  TRAIN n={len(train)}   TEST n={len(test)}\n")

    rows = []
    for s in STRATEGIES:
        ctr, ttr = curve(s, world, px, train)
        cte, tte = curve(s, world, px, test)
        ptr, pte = B.perf(ctr), B.perf(cte)
        rows.append((s, ptr, pte, ttr))

    rows.sort(key=lambda r: -r[1]["cagr"])          # rank by TRAIN, as one would
    print("Ranked by TRAIN CAGR — TEST column is untouched out-of-sample")
    print(f"{'':<30}{'TRAIN':>21}{'':>4}{'TEST':>21}")
    print(f"{'strategy':<30}{'CAGR':>7}{'R/V':>7}{'MDD':>7}    {'CAGR':>7}{'R/V':>7}{'MDD':>7}{'turn':>7}")
    for s, ptr, pte, ttr in rows:
        print(f"{LABELS[s]:<30}{ptr['cagr']*100:>6.1f}%{ptr['sharpe']:>7.2f}{ptr['mdd']*100:>6.1f}%    "
              f"{pte['cagr']*100:>6.1f}%{pte['sharpe']:>7.2f}{pte['mdd']*100:>6.1f}%{ttr*100:>6.1f}%")

    tr = [r[1]["cagr"] for r in rows]; te = [r[2]["cagr"] for r in rows]
    print(f"\nSpearman rank correlation, TRAIN vs TEST CAGR: {spearman(tr, te):+.2f}")
    trs = [r[1]["sharpe"] for r in rows]; tes = [r[2]["sharpe"] for r in rows]
    print(f"Spearman rank correlation, TRAIN vs TEST return/vol: {spearman(trs, tes):+.2f}")
    best_tr = rows[0]
    print(f"\nPicking the TRAIN winner ({LABELS[best_tr[0]]}) would have delivered "
          f"{best_tr[2]['cagr']*100:.1f}% CAGR in TEST,")
    print(f"versus {[r for r in rows if r[0]=='neutral'][0][2]['cagr']*100:.1f}% for doing nothing.")

if __name__ == "__main__":
    sys.exit(main() or 0)
