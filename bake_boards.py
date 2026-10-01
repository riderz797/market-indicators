"""
bake_boards.py
Refreshes the BAKED input blocks on the two pages that have no data of their
own — the Strategy Trigger Board and the Heat Map Corroboration page.

Both pages read values derived by other indicators. This script pulls them from
those indicators' already-generated outputs, so run it AFTER rebuild_all.py and
fetch_snider.py:

  acumen   <- indicators/macro/acumen_liquidity.html   (meta block)
  btcliq   <- indicators/btc/btc_liquidity_backtest.html (STATIC_DATA weekly
              grid, recomputed exactly as that page's updateData() does)
  snider   <- indicators/macro/snider_data.json         (heat map fallback only)
  dale     <- indicators/macro/regime_data.json         (heat map fallback only)

No network access. Run:  python bake_boards.py
"""

import json
import math
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
P = lambda *parts: os.path.join(BASE, *parts)

STRATEGY = P('indicators', 'tools', 'strategy_board.html')
HEATMAP  = P('indicators', 'macro', 'heatmap_corroboration.html')

# Must match btc_liquidity_script.js
DISPLAY_LAG   = 13       # weeks
SIGNAL_Q4_ROC = 0.0373   # top-quartile 13-week liquidity growth threshold


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


# ── Acumen ────────────────────────────────────────────────────────────────────
def acumen_inputs():
    html = read(P('indicators', 'macro', 'acumen_liquidity.html'))
    meta = {}
    for key in ('latest_lqi_z', 'latest_proj_z', 'last_equity_date'):
        m = re.search(r'"%s":\s*("[^"]*"|-?[0-9.]+)' % key, html)
        if not m:
            raise RuntimeError(f'acumen_liquidity.html: meta.{key} not found')
        meta[key] = json.loads(m.group(1))
    return {'z': meta['latest_lqi_z'], 'proj_z': meta['latest_proj_z'],
            'as_of': meta['last_equity_date']}


# ── BTC liquidity — a port of updateData() in btc_liquidity_script.js ─────────
def _shift(dates, weeks):
    from datetime import date, timedelta
    return [(date.fromisoformat(d) + timedelta(weeks=weeks)).isoformat() for d in dates]


def _pearson(x, y):
    n = len(x)
    sx, sy = sum(x), sum(y)
    sxy = sum(a * b for a, b in zip(x, y))
    sx2, sy2 = sum(a * a for a in x), sum(b * b for b in y)
    den = math.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy))
    return 0 if den == 0 else (n * sxy - sx * sy) / den


def _linreg(x, y):
    n = len(x)
    sx, sy = sum(x), sum(y)
    sxy, sx2 = sum(a * b for a, b in zip(x, y)), sum(a * a for a in x)
    slope = (n * sxy - sx * sy) / (n * sx2 - sx * sx)
    return slope, (sy - slope * sx) / n


def _tier(gap, roc):
    if roc >= SIGNAL_Q4_ROC:          return 'strong'
    if gap < -0.20 and roc > 0:       return 'active'
    if roc > 0:                       return 'moderate'
    if 0.10 <= gap < 0.30:            return 'avoid'
    return 'stand'


def btcliq_inputs():
    html = read(P('indicators', 'btc', 'btc_liquidity_backtest.html'))
    m = re.search(r'const STATIC_DATA = (\{.*?\});\n', html, re.S)
    if not m:
        raise RuntimeError('btc_liquidity_backtest.html: STATIC_DATA not found')
    sd = json.loads(m.group(1))
    btc, m2, dxy = sd['btc'], sd['m2'], sd['dxy']

    # forward-fill M2 onto the dollar-index dates; liquidity = M2 / DXY
    gl_d, gl_v, si = [], [], 0
    for d, x in zip(dxy['dates'], dxy['values']):
        while si < len(m2['dates']) - 1 and m2['dates'][si + 1] <= d:
            si += 1
        if m2['dates'][si] <= d and x:
            gl_d.append(d)
            gl_v.append(m2['values'][si] * (100 / x))

    btc_map = dict(zip(btc['dates'], btc['values']))

    def pairs(lag):
        xs, ys = [], []
        for d, g in zip(_shift(gl_d, lag), gl_v):
            b = btc_map.get(d)
            if b and b > 0 and g > 0:
                xs.append(math.log(g)); ys.append(math.log(b))
        return xs, ys

    best_lag, best_r = 1, -1
    for lag in range(1, 31):
        xs, ys = pairs(lag)
        if len(xs) >= 52:
            r = _pearson(xs, ys)
            if r > best_r:
                best_r, best_lag = r, lag
    slope, intercept = _linreg(*pairs(best_lag))

    first_btc, last_btc = btc['dates'][0], btc['dates'][-1]
    model_at_today = None
    for d, g in zip(_shift(gl_d, DISPLAY_LAG), gl_v):
        if first_btc <= d <= last_btc:
            model_at_today = math.exp(slope * math.log(g) + intercept)

    gap = math.log(btc['values'][-1] / model_at_today)
    roc = gl_v[-1] / gl_v[-14] - 1
    return {'roc13w': round(roc, 4), 'log_gap': round(gap, 2), 'tier': _tier(gap, roc),
            'as_of': last_btc, 'm2_through': m2['dates'][-1]}


# ── Snider / Dale — the heat map reads these live; baked copies are fallbacks ─
def snider_inputs():
    d = json.load(open(P('indicators', 'macro', 'snider_data.json'), encoding='utf-8'))
    b4 = d['board4']
    return {'growth': round(b4['current']['growth'], 4),
            'inflation': round(b4['current']['inflation'], 4),
            'conviction': round(b4['conviction'], 4), 'agreement': b4['agreement'],
            'quadrant': b4['quadrant'], 'as_of': d['as_of']}


def dale_inputs():
    d = json.load(open(P('indicators', 'macro', 'regime_data.json'), encoding='utf-8'))
    return {'growth': round(d['growth']['score'], 2),
            'inflation': round(d['inflation']['score'], 2),
            'signal_strength': d['signal_strength'], 'risk_on_prob': d['risk_on_prob'],
            'regime': d['regime'], 'market_regime': d['market_regime'], 'as_of': d['as_of']}


# ── Writers ───────────────────────────────────────────────────────────────────
def replace_baked_const(path, new_const):
    """Swap the `const BAKED = {...};` statement inside the marker block,
    keeping the block's explanatory comments."""
    html = read(path)
    start = html.find('// @@BAKED_DATA_START@@')
    end = html.find('// @@BAKED_DATA_END@@')
    if start == -1 or end == -1:
        raise RuntimeError(f'{os.path.basename(path)}: BAKED markers not found')
    block = html[start:end]
    m = re.search(r'const BAKED = \{.*?\n\};\n', block, re.S)
    if not m:
        raise RuntimeError(f'{os.path.basename(path)}: const BAKED not found')
    block = block[:m.start()] + new_const + block[m.end():]
    out = html[:start] + block + html[end:]
    if out != html:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(out)
    print(f'  {os.path.basename(path)}: {"updated" if out != html else "unchanged"}')


def js(v):
    return json.dumps(v)


def main():
    ac, bl = acumen_inputs(), btcliq_inputs()
    sn, dl = snider_inputs(), dale_inputs()
    as_of = min(ac['as_of'], bl['as_of'])
    print(f"acumen z={ac['z']} proj_z={ac['proj_z']} ({ac['as_of']})")
    print(f"btcliq roc13w={bl['roc13w']} log_gap={bl['log_gap']} tier={bl['tier']} "
          f"({bl['as_of']}, M2 through {bl['m2_through']})")
    print(f"snider {sn['quadrant']} ({sn['as_of']}) | dale {dl['regime']} ({dl['as_of']})")

    replace_baked_const(STRATEGY, f'''const BAKED = {{
  as_of: {js(as_of)},
  acumen: {{
    z:     {ac['z']},              // meta.latest_lqi_z
    as_of: {js(ac['as_of'])}        // meta.last_equity_date
  }},
  btcliq: {{
    roc13w:   {bl['roc13w']},
    thrust:   {SIGNAL_Q4_ROC},
    log_gap: {bl['log_gap']},
    as_of:   {js(bl['as_of'])},
    m2_through: {js(bl['m2_through'])}   // last month of published M2; held flat after
  }}
}};
''')

    replace_baked_const(HEATMAP, f'''const BAKED = {{
  as_of: {js(as_of)},
  acumen:  {{ z: {ac['z']}, proj_z: {ac['proj_z']}, as_of: {js(ac['as_of'])} }},
  btcliq:  {{ roc13w: {bl['roc13w']}, thrust_threshold: {SIGNAL_Q4_ROC}, gap: {bl['log_gap']},
             tier: {js(bl['tier'])}, as_of: {js(bl['as_of'])} }},
  // Fallbacks used only if the live fetches fail
  snider:  {{ growth: {sn['growth']}, inflation: {sn['inflation']}, conviction: {sn['conviction']}, agreement: {sn['agreement']},
             quadrant: {js(sn['quadrant'])}, as_of: {js(sn['as_of'])} }},
  dale:    {{ growth: {dl['growth']}, inflation: {dl['inflation']}, signal_strength: {dl['signal_strength']}, risk_on_prob: {dl['risk_on_prob']},
             regime: {js(dl['regime'])}, market_regime: {js(dl['market_regime'])}, as_of: {js(dl['as_of'])} }}
}};
''')


if __name__ == '__main__':
    main()
