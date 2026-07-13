#!/usr/bin/env python3
"""
Backtest of the BTC Liquidity Index (M2 * 100/DXY, dynamic lead-lag) as a
CALL-BUYING timing signal.

Realism constraints (both matter — the live page ignores them):
  * WALK-FORWARD FIT: the best lag and log-log regression are refit each week
    using ONLY data available up to that week (the live page fits on the full
    history, which overstates r for trading purposes).
  * M2 PUBLICATION LAG: FRED M2SL for month m is released ~4th week of m+1,
    i.e. ~8 weeks after the observation date. A signal at week t may only use
    liquidity values dated <= t - 56 days. (The 13-week display lag means the
    model gap IS implementable in real time; raw liquidity momentum is not
    without this haircut.)

Signals tested, each against unconditional baseline, forward horizons
4/8/13/26 weeks, metrics geared to option buying: win rate and P(move > 10/20/30%).

  1. Liquidity momentum: 13-week rate of change of known liquidity (quartiles)
  2. Liquidity turn-up formation: ROC crosses from negative to positive
  3. Model gap: BTC % above/below walk-forward model price (buckets)
  4. Combined formation: gap deeply negative AND liquidity ROC > 0
  5. Gap recovery formation: gap crosses up through -25% from below

Also reports pre-2020 vs 2020+ split for regime robustness, and independent
episode counts (weekly rows overlap heavily at long horizons).

Usage: python backtest_btc_liquidity.py            (prints tables)
       python backtest_btc_liquidity.py --json F   (also dumps results to F)
       python backtest_btc_liquidity.py --signal   (today's call-buy signal card
                                                    + writes liquidity_signal.json)
"""
import json, sys, math, os, urllib.request
from datetime import datetime, timedelta

import numpy as np

FRED_KEY = '824b29c5afa52f3fc7c6e7dc4925aebb'
M2_PUB_LAG_DAYS = 56          # M2SL observation-date -> public availability
DISPLAY_LAG = 13              # weeks, same as the live page
MIN_FIT_WEEKS = 156           # need 3y of paired data before first walk-forward fit
HORIZONS = [4, 8, 13, 26]     # forward-return horizons in weeks
MOVE_THRESHOLDS = [0.10, 0.20, 0.30]


# ── data fetch (mirrors rebuild_all.py) ─────────────────────────────────────
def fetch_fred(series_id, start='2000-01-01'):
    url = (f'https://api.stlouisfed.org/fred/series/observations'
           f'?series_id={series_id}&api_key={FRED_KEY}'
           f'&file_type=json&observation_start={start}')
    data = json.loads(urllib.request.urlopen(url, timeout=30).read())
    obs = [(o['date'], float(o['value'])) for o in data['observations'] if o['value'] != '.']
    return [o[0] for o in obs], [o[1] for o in obs]


def fetch_yfinance(ticker, start):
    import yfinance as yf
    df = yf.download(ticker, start=start, interval='1d', progress=False, auto_adjust=True)
    dates = [d.strftime('%Y-%m-%d') for d in df.index]
    values = [float(v) for v in df['Close'].values.flatten()]
    return dates, values


def resample_weekly_friday(dates, values):
    weekly = {}
    for d_str, v in zip(dates, values):
        d = datetime.strptime(d_str, '%Y-%m-%d')
        bucket = d + timedelta(days=(4 - d.weekday()) % 7)
        weekly[bucket.strftime('%Y-%m-%d')] = v
    items = sorted(weekly.items())
    return [k for k, _ in items], [v for _, v in items]


# ── model machinery ─────────────────────────────────────────────────────────
def best_lag_fit(gl_dates, gl_log, btc_map, cutoff, avail_cutoff, max_lag=30):
    """Fit best lag (1..max_lag weeks) and OLS on log-log pairs using only
    (liquidity dated d, BTC at d + lag) with d + lag <= cutoff and d <= avail_cutoff."""
    best = None
    date_objs = [datetime.strptime(d, '%Y-%m-%d') for d in gl_dates]
    for lag in range(1, max_lag + 1):
        xs, ys = [], []
        for i, d in enumerate(date_objs):
            if gl_dates[i] > avail_cutoff:
                break
            target = (d + timedelta(weeks=lag)).strftime('%Y-%m-%d')
            if target > cutoff:
                continue
            bv = btc_map.get(target)
            if bv and bv > 0:
                xs.append(gl_log[i]); ys.append(math.log(bv))
        if len(xs) >= 52:
            x = np.asarray(xs); y = np.asarray(ys)
            r = np.corrcoef(x, y)[0, 1]
            if best is None or r > best[1]:
                slope, intercept = np.polyfit(x, y, 1)
                best = (lag, r, slope, intercept)
    return best  # (lag, r, slope, intercept) or None


def pct(x):
    return f'{x*100:+6.1f}%'


def stats_block(rets):
    """rets: list of forward returns (may contain None -> dropped)."""
    r = np.asarray([x for x in rets if x is not None])
    if len(r) == 0:
        return None
    out = {
        'n': int(len(r)),
        'mean': float(r.mean()),
        'median': float(np.median(r)),
        'win': float((r > 0).mean()),
        'min': float(r.min()),
        'max': float(r.max()),
    }
    for th in MOVE_THRESHOLDS:
        out[f'p_gt_{int(th*100)}'] = float((r > th).mean())
    return out


def count_episodes(mask):
    """Number of distinct runs of True in a boolean list (independent signal episodes)."""
    n, prev = 0, False
    for m in mask:
        if m and not prev:
            n += 1
        prev = m
    return n


def fmt_stats(label, s, episodes=None):
    if s is None:
        return f'  {label:<34} (no samples)'
    ep = f' ep={episodes:<3}' if episodes is not None else ''
    return (f'  {label:<34} n={s["n"]:<4}{ep} mean={pct(s["mean"])} med={pct(s["median"])} '
            f'win={s["win"]*100:5.1f}%  >10%={s["p_gt_10"]*100:5.1f}%  '
            f'>20%={s["p_gt_20"]*100:5.1f}%  >30%={s["p_gt_30"]*100:5.1f}%  '
            f'worst={pct(s["min"])}')


# Rough ATM call premium as % of spot at ~50 implied vol (0.4 * sigma * sqrt(T)).
# Used only to translate spot-move analogs into a return-on-premium estimate.
PREMIUM_PCT = {8: 0.078, 13: 0.10, 26: 0.14}


def emit_signal(rows, out_path):
    """Grade the latest week and print a signal card with backtested analogs."""
    cur = rows[-1]
    rocs = sorted(r['roc'] for r in rows if r['roc'] is not None)
    q4_th = rocs[int(len(rocs) * 0.75)]
    import bisect
    roc_pct = bisect.bisect_left(rocs, cur['roc']) / len(rocs) if cur['roc'] is not None else None

    # condition hierarchy: first match wins
    def cond_thrust(r):   return r['roc'] is not None and r['roc'] >= q4_th
    def cond_cheap(r):    return (r['gap'] is not None and r['roc'] is not None
                                  and r['gap'] < -0.20 and r['roc'] > 0)
    def cond_mod(r):      return r['roc'] is not None and r['roc'] > 0
    def cond_danger(r):   return r['gap'] is not None and 0.10 <= r['gap'] < 0.30
    def cond_flat(r):     return r['roc'] is None or r['roc'] <= 0
    tiers = [
        ('STRONG - liquidity thrust (top-quartile momentum)', cond_thrust),
        ('ACTIVE - cheap vs model + liquidity rising', cond_cheap),
        ('MODERATE - liquidity rising, no valuation edge', cond_mod),
        ('AVOID - BTC 10-30% above model (negative expectancy)', cond_danger),
        ('STAND ASIDE - liquidity contracting, no tested edge', cond_flat),
    ]
    for label, fn in tiers:
        if fn(cur):
            break

    # analog weeks = every past week matching the same condition
    analogs = [r for r in rows[:-1] if fn(r)]
    print('=' * 74)
    print(f'CALL-OPTION SIGNAL  |  week of {cur["date"]}  |  BTC ${cur["px"]:,.0f}')
    print('=' * 74)
    gap_s = f'{cur["gap"]*100:+.0f}%' if cur['gap'] is not None else 'n/a'
    roc_s = (f'{cur["roc"]*100:+.2f}% ({roc_pct*100:.0f}th pct)'
             if cur['roc'] is not None else 'n/a')
    print(f'  Gap vs model: {gap_s}   |   Liquidity 13w growth: {roc_s}')
    print(f'\n  SIGNAL: {label}')
    print(f'  Historical analogs: {len(analogs)} weeks '
          f'({count_episodes([fn(r) for r in rows])} distinct episodes)\n')

    sig = {'date': cur['date'], 'px': cur['px'], 'gap': cur['gap'], 'roc': cur['roc'],
           'roc_pctile': roc_pct, 'signal': label, 'n_analogs': len(analogs),
           'horizons': {}}
    for h in HORIZONS:
        s = stats_block([r['fwd'][h] for r in analogs])
        if s is None:
            continue
        line = (f'  {h:>2}w: est. spot move mean {pct(s["mean"])} / median {pct(s["median"])}'
                f'  win {s["win"]*100:.0f}%  P(>+20%) {s["p_gt_20"]*100:.0f}%')
        prem = PREMIUM_PCT.get(h)
        if prem:
            # expected intrinsic call payoff, vs the same for ALL history --
            # relative edge is robust to the premium guess; absolute EV is not
            # (BTC's past bull drift would make any always-long call look great)
            a_pay = [max(r['fwd'][h], 0.0) for r in analogs if r['fwd'][h] is not None]
            b_pay = [max(r['fwd'][h], 0.0) for r in rows[:-1] if r['fwd'][h] is not None]
            ratio = (sum(a_pay) / len(a_pay)) / (sum(b_pay) / len(b_pay))
            p_prof = sum(1 for r in analogs
                         if r['fwd'][h] is not None and r['fwd'][h] > prem) / len(a_pay)
            line += (f'  |  ATM call ~{prem*100:.0f}% prem: P(profit) {p_prof*100:.0f}%, '
                     f'payoff x{ratio:.1f} vs avg week')
            s['call_p_profit'] = p_prof; s['payoff_vs_avg'] = ratio; s['premium_pct'] = prem
        print(line)
        sig['horizons'][str(h)] = s

    # what would upgrade / invalidate the signal
    print()
    if cur['roc'] is not None and cur['roc'] <= 0 and cur['gap'] is not None and cur['gap'] < -0.20:
        print('  WATCH: gap already < -20%. Liquidity 13w growth crossing above 0 '
              'activates the "cheap + rising" formation (13w: win 63%, mean +36%).')
    if fn is cond_cheap and cur['roc'] < q4_th:
        print(f'  NOTE: momentum is positive but below the +{q4_th*100:.1f}% thrust threshold — '
              'this is the weaker tier of the signal. Prefer 3-6 month expiries.')
    if fn is cond_thrust:
        print('  Strongest tested condition. Edge peaks at 8-13 weeks; still only '
              '~a dozen historical episodes — size to lose the full premium.')
    print('  Estimates are backtest analogs, not forecasts. Premiums are rough '
          '(~50 vol); check DVOL before paying up.')

    with open(out_path, 'w') as f:
        json.dump(sig, f, indent=1)
    print(f'\n  Signal JSON -> {out_path}')


def main():
    json_out = None
    if '--json' in sys.argv:
        json_out = sys.argv[sys.argv.index('--json') + 1]
    signal_mode = '--signal' in sys.argv

    print('Fetching data...')
    m2_d, m2_v = fetch_fred('M2SL')
    btc_d, btc_v = fetch_yfinance('BTC-USD', '2013-01-01')
    try:
        dxy_d, dxy_v = fetch_yfinance('DX-Y.NYB', '2000-01-01')
    except Exception as e:
        print(f'  Yahoo DXY failed ({e}); using FRED DTWEXBGS')
        dxy_d, dxy_v = fetch_fred('DTWEXBGS')
    print(f'  M2 {len(m2_d)} pts to {m2_d[-1]} | BTC {len(btc_d)} pts to {btc_d[-1]} '
          f'| DXY {len(dxy_d)} pts to {dxy_d[-1]}')

    btc_wd, btc_wv = resample_weekly_friday(btc_d, btc_v)
    dxy_wd, dxy_wv = resample_weekly_friday(dxy_d, dxy_v)
    btc_map = dict(zip(btc_wd, btc_wv))

    # Global liquidity on the DXY weekly grid, forward-filling monthly M2.
    # Also record when each M2 observation became publicly known.
    m2_pairs = list(zip(m2_d, m2_v))
    gl_dates, gl_vals, gl_known = [], [], []   # gl_known = availability date of the M2 obs used
    mi = 0
    for d, dv in zip(dxy_wd, dxy_wv):
        while mi < len(m2_pairs) - 1 and m2_pairs[mi + 1][0] <= d:
            mi += 1
        if m2_pairs[mi][0] <= d and dv:
            gl_dates.append(d)
            gl_vals.append(m2_pairs[mi][1] * 100.0 / dv)
            known = datetime.strptime(m2_pairs[mi][0], '%Y-%m-%d') + timedelta(days=M2_PUB_LAG_DAYS)
            gl_known.append(known.strftime('%Y-%m-%d'))
    gl_log = [math.log(v) for v in gl_vals]
    gl_idx = {d: i for i, d in enumerate(gl_dates)}

    # Full-sample fit, for comparison with the live page
    full = best_lag_fit(gl_dates, gl_log, btc_map, cutoff='9999', avail_cutoff='9999')
    print(f'\nFull-sample fit (what the live page shows): lag={full[0]}w  r={full[1]:.3f}  '
          f'slope={full[2]:.2f}')

    # ── walk-forward pass over BTC weeks ────────────────────────────────────
    print('Running walk-forward fits (refit every 4 weeks)...')
    rows = []          # one dict per BTC week with signals + forward returns
    cached_fit = None
    for ti, t in enumerate(btc_wd):
        t_dt = datetime.strptime(t, '%Y-%m-%d')
        avail_cut = (t_dt - timedelta(days=M2_PUB_LAG_DAYS)).strftime('%Y-%m-%d')

        # refit every 4 weeks (cheap approximation of weekly refit)
        if ti % 4 == 0 or cached_fit is None:
            cached_fit = best_lag_fit(gl_dates, gl_log, btc_map, cutoff=t,
                                      avail_cutoff=avail_cut)
        fit = cached_fit
        if fit is None:
            continue
        lag, r, slope, intercept = fit

        # paired-sample length check for MIN_FIT_WEEKS
        # (best_lag_fit needs >=52; require longer history before trading)
        first_pair = max(gl_dates[0], btc_wd[0])
        weeks_hist = (t_dt - datetime.strptime(first_pair, '%Y-%m-%d')).days / 7
        if weeks_hist < MIN_FIT_WEEKS:
            continue

        # model gap: model price at t uses liquidity dated t - DISPLAY_LAG weeks
        src = (t_dt - timedelta(weeks=DISPLAY_LAG)).strftime('%Y-%m-%d')
        gi = gl_idx.get(src)
        gap = None
        if gi is not None and gl_known[gi] <= t:
            model = math.exp(slope * gl_log[gi] + intercept)
            gap = math.log(btc_map[t] / model)

        # liquidity 13w ROC using only publicly-known values at t
        ki = None
        for j in range(len(gl_dates) - 1, -1, -1):
            if gl_dates[j] <= t and gl_known[j] <= t:
                ki = j
                break
        roc = None
        if ki is not None and ki >= 13:
            roc = gl_vals[ki] / gl_vals[ki - 13] - 1.0

        fwd = {}
        for h in HORIZONS:
            th = (t_dt + timedelta(weeks=h)).strftime('%Y-%m-%d')
            bv = btc_map.get(th)
            fwd[h] = (bv / btc_map[t] - 1.0) if bv else None

        rows.append({'date': t, 'lag': lag, 'r': r, 'gap': gap, 'roc': roc,
                     'px': btc_map[t], 'fwd': fwd})

    print(f'  {len(rows)} tradable weeks from {rows[0]["date"]} to {rows[-1]["date"]}')

    if signal_mode:
        emit_signal(rows, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'liquidity_signal.json'))
        return

    # ── evaluate signals ────────────────────────────────────────────────────
    results = {'meta': {'first': rows[0]['date'], 'last': rows[-1]['date'],
                        'full_fit': {'lag': full[0], 'r': full[1], 'slope': full[2]}},
               'signals': {}}

    def evaluate(name, mask, sub=None):
        use = [(rw, m) for rw, m in zip(rows, mask)]
        if sub == 'pre2020':
            use = [(rw, m) for rw, m in use if rw['date'] < '2020-01-01']
        elif sub == 'post2020':
            use = [(rw, m) for rw, m in use if rw['date'] >= '2020-01-01']
        ep = count_episodes([m for _, m in use])
        out = {}
        for h in HORIZONS:
            out[h] = stats_block([rw['fwd'][h] for rw, m in use if m])
        return out, ep

    def report(name, mask):
        out, ep = evaluate(name, mask)
        results['signals'][name] = {'horizons': {str(h): out[h] for h in HORIZONS},
                                    'episodes': ep}
        print(f'\n{name}  (episodes={ep})')
        for h in HORIZONS:
            print(fmt_stats(f'{h:>2}w fwd', out[h]))
        # regime split at 13w
        for sub, tag in [('pre2020', 'pre-2020'), ('post2020', '2020+')]:
            o2, _ = evaluate(name, mask, sub)
            s = o2[13]
            if s:
                print(f'    [{tag:<8} 13w] n={s["n"]:<4} mean={pct(s["mean"])} '
                      f'win={s["win"]*100:5.1f}%  >20%={s["p_gt_20"]*100:5.1f}%')
        results['signals'][name]['pre2020_13w'] = evaluate(name, mask, 'pre2020')[0][13]
        results['signals'][name]['post2020_13w'] = evaluate(name, mask, 'post2020')[0][13]

    # 0. baseline
    report('BASELINE (all weeks)', [True] * len(rows))

    # 1. liquidity momentum quartiles
    rocs = sorted(rw['roc'] for rw in rows if rw['roc'] is not None)
    if rocs:
        qs = [rocs[int(len(rocs) * q)] for q in (0.25, 0.5, 0.75)]
        print(f'\nLiquidity 13w ROC quartile breakpoints: '
              f'{qs[0]*100:.2f}% / {qs[1]*100:.2f}% / {qs[2]*100:.2f}%')
        labels = ['Q1 (weakest)', 'Q2', 'Q3', 'Q4 (strongest)']
        bounds = [(-9, qs[0]), (qs[0], qs[1]), (qs[1], qs[2]), (qs[2], 9)]
        for lb, (lo, hi) in zip(labels, bounds):
            mask = [rw['roc'] is not None and lo <= rw['roc'] < hi for rw in rows]
            report(f'LIQ ROC {lb}', mask)

    # simple positive/negative
    report('LIQ ROC > 0', [rw['roc'] is not None and rw['roc'] > 0 for rw in rows])
    report('LIQ ROC <= 0', [rw['roc'] is not None and rw['roc'] <= 0 for rw in rows])

    # 2. turn-up formation: ROC crosses above 0
    cross_up = []
    for i, rw in enumerate(rows):
        prev = rows[i - 1]['roc'] if i else None
        cross_up.append(rw['roc'] is not None and prev is not None
                        and prev <= 0 < rw['roc'])
    report('FORMATION: liq ROC crosses above 0', cross_up)

    # 3. model gap buckets
    gaps = [rw['gap'] for rw in rows if rw['gap'] is not None]
    print(f'\nModel gap distribution: min={min(gaps)*100:.0f}% p25={np.percentile(gaps,25)*100:.0f}% '
          f'med={np.percentile(gaps,50)*100:.0f}% p75={np.percentile(gaps,75)*100:.0f}% max={max(gaps)*100:.0f}%'
          f'  (log % vs walk-forward model)')
    buckets = [('gap < -30%', -9, -0.30), ('-30% .. -10%', -0.30, -0.10),
               ('-10% .. +10%', -0.10, 0.10), ('+10% .. +30%', 0.10, 0.30),
               ('gap > +30%', 0.30, 9)]
    for lb, lo, hi in buckets:
        mask = [rw['gap'] is not None and lo <= rw['gap'] < hi for rw in rows]
        report(f'MODEL GAP {lb}', mask)

    # 4. combined formation
    combo = [rw['gap'] is not None and rw['roc'] is not None
             and rw['gap'] < -0.20 and rw['roc'] > 0 for rw in rows]
    report('FORMATION: gap < -20% AND liq ROC > 0', combo)

    # 5. gap recovery: crosses up through -25%
    recov = []
    for i, rw in enumerate(rows):
        prev = rows[i - 1]['gap'] if i else None
        recov.append(rw['gap'] is not None and prev is not None
                     and prev <= -0.25 < rw['gap'])
    report('FORMATION: gap crosses up through -25%', recov)

    if json_out:
        # attach the weekly rows for charting
        results['rows'] = [{'date': rw['date'], 'px': rw['px'], 'gap': rw['gap'],
                            'roc': rw['roc'], 'lag': rw['lag'], 'r': rw['r'],
                            'fwd13': rw['fwd'][13]} for rw in rows]
        with open(json_out, 'w') as f:
            json.dump(results, f)
        print(f'\nJSON written to {json_out}')


if __name__ == '__main__':
    main()
