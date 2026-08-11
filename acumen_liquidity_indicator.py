"""
================================================================================
ACUMEN GLOBAL LIQUIDITY INDICATOR
================================================================================

A Howell-style global liquidity index built from public data sources, designed
to lead US equities by ~6.5 months.

USAGE:
    python acumen_liquidity_indicator.py

REQUIREMENTS:
    pip install pandas numpy matplotlib requests

INPUTS (all free, no API keys):
    - FRED:  WALCL, WTREGEN, RRPONTSYD, TOTBKCR, NDFACBW027SBOG, ECBASSETSW,
             JPNASSETS, TRESEGCNM052N, DTWEXBGS, DCOILWTICO, DEXUSEU, DEXJPUS,
             DTB4WK, RRPONTSYAWARD
    - Yahoo: ^MOVE, ^GSPC, ^NDX, ^RUT, ^DJI

CONSTRUCTION:
    1. Central Bank Liquidity = Fed (WALCL - TGA - RRP) + ECB + BoJ + China FX
    2. Private Liquidity      = US bank credit (H.8) + eurodollar leg (NDFA)
    3. Gross Global Liquidity = CB + Private
    4. Drains:
         -3% per +$10/bbl oil      vs 2y rolling baseline   (Howell)
         -4% per +10 MOVE points   vs 2y rolling baseline   (Howell)
        -10% per +10% DXY          vs 2y rolling baseline   (Howell)
         -3% per -10bp bills vs the RRP floor               (UNVALIDATED)
       Total drain capped at +/-30%
    5. Net Liquidity = Gross * (1 + drain_pct)
    6. Indicator = 3-month MA of YoY % change in Net Liquidity

2026-08 REVISION (Snider inputs):
    The private leg was domestic bank credit alone, which measures the onshore
    banking system and misses the offshore dollar entirely. NDFACBW027SBOG —
    US banks' net position with their own foreign offices — adds the eurodollar
    leg from the same weekly H.8 release. A collateral drain was added on top,
    driven by bills trading through the reverse-repo floor.

    This changed the index, so the lead and correlations were re-derived rather
    than carried over. Measured on the same basis the page publishes (UNSMOOTHED
    equity YoY vs smoothed liquidity YoY), scanning the lead on each variant:

        variant                          lead   r full   r post-2020
        old (bank credit, 3 drains)      190d    0.749       0.794
        + eurodollar leg only            190d    0.748       0.791
        + collateral drain only          195d    0.755       0.812
        new (both)                       200d    0.754       0.809

    Read that honestly: the improvement is MARGINAL and within noise, and it
    comes almost entirely from the collateral drain. The eurodollar leg does not
    improve the equity-lead fit at all — it is retained because the private leg
    measuring only onshore bank credit was conceptually wrong for a "global"
    liquidity index, not because it scores better. It is also small in level
    (~$418bn against ~$19,750bn of bank credit), so its effect is at the margin.

EMPIRICAL RESULTS (2015-present, vs USEQUITIES = equal-weighted SPX/NDX/RUT/DJI):
    - Best forward lead: 200 days
    - Correlation: 0.75 full sample, 0.81 post-2020
================================================================================
"""

import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import StringIO

# ============================================================================
# CONFIG
# ============================================================================

LEAD_DAYS = 200             # forward lead empirically optimized vs USEQUITIES
SMOOTH_DAYS = 63            # ~3-month MA on the YoY series
DRAIN_BASELINE_DAYS = 504   # ~2-year rolling baseline for oil/DXY/MOVE drains
DRAIN_CAP = 0.30            # cap total drain at +/-30%

# Collateral drain coefficient. UNVALIDATED — this is a judgment call, not a
# fitted parameter. Howell publishes coefficients for oil, MOVE and the dollar;
# he does not publish one for collateral. 0.30 sizes a 10bp move in bills
# relative to the reverse-repo floor at roughly a 3% drain, putting it on the
# same order as the existing MOVE term. Treat it as a placeholder to revisit,
# not as a calibrated input.
COLL_DRAIN_COEF = 0.30
PLOT_START = '2015-01-01'

# Acumen palette (warm/light version for PNG)
BG = '#F5F0E8'
CARD = '#FFFFFF'
ORANGE = '#F0A030'
HEADER = '#B8860B'
BODY = '#333333'
MUTED = '#999999'
BORDER = '#E0D8CC'

OUTPUT_PATH = 'acumen_liquidity_indicator.png'
JS_OUTPUT_PATH = 'indicators/macro/acumen_liquidity_baked.js'

# ============================================================================
# DATA FETCHERS
# ============================================================================

FRED_API_KEY = '824b29c5afa52f3fc7c6e7dc4925aebb'


def fred(series_id):
    """Fetch a FRED series.

    Primary path is the JSON API on api.stlouisfed.org; the legacy CSV
    endpoint on fred.stlouisfed.org is kept as a fallback because that host
    is intermittently unreachable from some networks (hangs / read timeout).
    """
    api_url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={series_id}&api_key={FRED_API_KEY}"
               f"&file_type=json&sort_order=asc")
    try:
        r = requests.get(api_url, timeout=30)
        r.raise_for_status()
        obs = r.json().get('observations', [])
        if not obs:
            raise ValueError(f'no observations returned for {series_id}')
        df = pd.DataFrame([(o['date'], o['value']) for o in obs],
                          columns=['date', series_id])
    except Exception:
        # Fallback: legacy public CSV endpoint (no API key needed)
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r = requests.get(url, timeout=30)
        df = pd.read_csv(StringIO(r.text))
        df.columns = ['date', series_id]
    df['date'] = pd.to_datetime(df['date'])
    df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
    return df.dropna().set_index('date')


def yahoo(symbol, name):
    """Fetch a Yahoo Finance series via the public chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"period1": 1262304000, "period2": 1900000000, "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    j = r.json()
    result = j['chart']['result'][0]
    ts = result['timestamp']
    closes = result['indicators']['quote'][0]['close']
    df = pd.DataFrame({
        'date': pd.to_datetime(ts, unit='s').normalize(),
        name: closes
    }).dropna()
    return df.set_index('date')


# ============================================================================
# BUILD THE INDICATOR
# ============================================================================

def build_liquidity_index():
    """Build the Acumen Global Liquidity Index from public data."""
    print("Fetching FRED data...")
    walcl   = fred('WALCL')         # Fed total assets, $MM, weekly
    tga     = fred('WTREGEN')       # Treasury General Account, $MM, weekly
    rrp     = fred('RRPONTSYD')     # Reverse repo, $B, daily
    bankcr  = fred('TOTBKCR')       # Bank credit (H.8), $B, weekly
    ecb     = fred('ECBASSETSW')    # ECB assets, EUR MM, weekly
    boj     = fred('JPNASSETS')     # BoJ assets, JPY 100M units, monthly
    cnfx    = fred('TRESEGCNM052N') # China FX reserves, $M, monthly
    dxy     = fred('DTWEXBGS')      # broad dollar index, daily
    oil     = fred('DCOILWTICO')    # WTI oil, $/bbl, daily
    eurusd  = fred('DEXUSEU')       # USD per EUR, daily
    jpyusd  = fred('DEXJPUS')       # JPY per USD, daily
    # Eurodollar leg: US banks' net position with their own foreign offices
    # (H.8, weekly, $B). Makes the private-liquidity leg cross-border rather
    # than purely domestic. Same release as TOTBKCR, so alignment is trivial.
    ndfa    = fred('NDFACBW027SBOG')
    # Collateral drain inputs: bills trading through the reverse-repo floor
    tb4wk   = fred('DTB4WK')        # 4-week bill, %, daily
    rrpaw   = fred('RRPONTSYAWARD') # ON RRP award rate, %, daily

    print("Fetching Yahoo data...")
    move = yahoo('^MOVE', 'move')

    # Build daily master frame
    print("Building master frame...")
    idx = pd.date_range('2014-01-01', pd.Timestamp.today(), freq='D')
    m = pd.DataFrame(index=idx)

    m['walcl']  = walcl['WALCL'].reindex(idx).ffill()
    m['tga']    = tga['WTREGEN'].reindex(idx).ffill()
    m['rrp']    = rrp['RRPONTSYD'].reindex(idx).ffill() * 1000  # $B -> $MM
    m['bankcr'] = bankcr['TOTBKCR'].reindex(idx).ffill()        # already $B
    m['ecb']    = ecb['ECBASSETSW'].reindex(idx).ffill()
    m['boj']    = boj['JPNASSETS'].reindex(idx).ffill()
    m['cnfx']   = cnfx['TRESEGCNM052N'].reindex(idx).ffill()
    m['dxy']    = dxy['DTWEXBGS'].reindex(idx).ffill()
    m['oil']    = oil['DCOILWTICO'].reindex(idx).ffill()
    m['eurusd'] = eurusd['DEXUSEU'].reindex(idx).ffill()
    m['jpyusd'] = jpyusd['DEXJPUS'].reindex(idx).ffill()
    m['move']   = move['move'].reindex(idx).ffill()
    m['ndfa']   = ndfa['NDFACBW027SBOG'].reindex(idx).ffill()   # already $B
    m['tb4wk']  = tb4wk['DTB4WK'].reindex(idx).ffill()
    m['rrpaw']  = rrpaw['RRPONTSYAWARD'].reindex(idx).ffill()

    # ----- Central Bank Liquidity (USD billions) -----
    # Fed: (WALCL - TGA - RRP) in $MM, convert to $B
    m['fed_liq_b'] = (m['walcl'] - m['tga'] - m['rrp']) / 1000.0
    # ECB: EUR MM * USD/EUR / 1000 -> USD B
    m['ecb_usd_b'] = m['ecb'] * m['eurusd'] / 1000.0
    # BoJ: JPNASSETS is in 100 million yen units; * 1e8 yen / jpyusd / 1e9 -> USD B
    m['boj_usd_b'] = m['boj'] * 1e8 / m['jpyusd'] / 1e9
    # China FX reserves in $M -> $B (used as PBoC balance sheet proxy)
    m['cn_usd_b']  = m['cnfx'] / 1000.0

    m['cb_liq']   = m['fed_liq_b'] + m['ecb_usd_b'] + m['boj_usd_b'] + m['cn_usd_b']
    # Private liquidity = domestic bank credit + the offshore (eurodollar) leg.
    # NDFA is a net position and can be negative, which is correct here: when
    # US banks pull funding back from their foreign offices that is a genuine
    # contraction of private dollar liquidity, not a missing observation.
    m['priv_liq'] = m['bankcr'] + m['ndfa']
    m['gl_gross'] = m['cb_liq'] + m['priv_liq']

    # ----- Drains (Howell coefficients vs 2-year rolling baseline) -----
    win = DRAIN_BASELINE_DAYS
    m['oil_base']  = m['oil'].rolling(win, min_periods=180).mean()
    m['dxy_base']  = m['dxy'].rolling(win, min_periods=180).mean()
    m['move_base'] = m['move'].rolling(win, min_periods=180).mean()

    # Collateral: bills trading BELOW the reverse-repo floor means collateral is
    # scarce enough that buyers accept a yield worse than the risk-free floor.
    m['bill_floor'] = m['tb4wk'] - m['rrpaw']
    m['bill_base']  = m['bill_floor'].rolling(win, min_periods=180).mean()

    m['oil_drain']  = -0.003 * (m['oil']  - m['oil_base'])
    m['move_drain'] = -0.004 * (m['move'] - m['move_base'])
    m['dxy_drain']  = -0.010 * ((m['dxy'] / m['dxy_base'] - 1.0) * 100.0)
    # COLL_DRAIN_COEF is a judgment call, not a fitted parameter — see config.
    m['coll_drain'] = COLL_DRAIN_COEF * (m['bill_floor'] - m['bill_base'])

    m['total_drain'] = (m['oil_drain'] + m['move_drain'] + m['dxy_drain']
                        + m['coll_drain'].fillna(0.0)
                        ).clip(-DRAIN_CAP, DRAIN_CAP)
    m['gl_net'] = m['gl_gross'] * (1.0 + m['total_drain'])

    # ----- Final Indicator: smoothed YoY % of net global liquidity -----
    m['liquidity_yoy'] = (m['gl_net'].pct_change(365)
                          .rolling(SMOOTH_DAYS).mean() * 100.0)

    return m


# ============================================================================
# BUILD US EQUITIES BENCHMARK (USEQUITIES = equal-weight Dow/SPX/RUT/NDX)
# ============================================================================

def build_usequities(idx):
    print("Fetching US equity indices...")
    components = {
        '^DJI':  'Dow',
        '^GSPC': 'SP500',
        '^RUT':  'Russell2000',
        '^NDX':  'Nasdaq100',
    }
    basket = pd.DataFrame(index=idx)
    for sym, name in components.items():
        df = yahoo(sym, name)
        basket[name] = df[name].reindex(idx).ffill()

    norm_date = '2015-01-02'
    for col in basket.columns:
        base = basket.loc[norm_date, col]
        basket[col] = basket[col] / base * 100.0

    useq = basket.mean(axis=1)
    useq.name = 'USEQUITIES'
    return useq


# ============================================================================
# BAKE TO JS FOR HTML VERSION
# ============================================================================

def bake_js(m, useq, write_file=True):
    """Build the baked data payload. Writes standalone JS file unless write_file=False."""
    import os, json

    liq_yoy = m['liquidity_yoy']
    useq_yoy = useq.pct_change(365) * 100

    plot_start = '2015-01-01'
    liq_window = liq_yoy.loc[plot_start:].dropna()
    useq_window = useq_yoy.loc[plot_start:].dropna()

    lqi_mean, lqi_std = liq_window.mean(), liq_window.std()
    useq_mean, useq_std = useq_window.mean(), useq_window.std()

    lqi_z  = (liq_yoy  - lqi_mean)  / lqi_std
    useq_z = (useq_yoy - useq_mean) / useq_std

    # Projected liquidity (dates shifted forward)
    lqi_proj = lqi_z.copy()
    lqi_proj.index = lqi_proj.index + pd.Timedelta(days=LEAD_DAYS)

    # Clip to plot range
    lqi_z_plot   = lqi_z.loc[plot_start:].dropna()
    useq_z_plot  = useq_z.loc[plot_start:].dropna()
    lqi_proj_plot = lqi_proj.loc[plot_start:].dropna()

    last_eq_date = useq_z_plot.index.max()

    # Correlations
    corr_full   = useq_yoy.loc[plot_start:].corr(liq_yoy.shift(LEAD_DAYS).loc[plot_start:])
    corr_post20 = useq_yoy.loc['2020-01-01':].corr(liq_yoy.shift(LEAD_DAYS).loc['2020-01-01':])

    # Current liquidity signal
    latest_lqi_z   = float(lqi_z.dropna().iloc[-1])
    latest_lqi_raw = float(liq_yoy.dropna().iloc[-1])
    latest_liq_proj_date = lqi_proj_plot.index.max().strftime('%Y-%m-%d')
    latest_liq_proj_val  = float(lqi_proj_plot.iloc[-1])

    # Component breakdown (latest values)
    latest = m.dropna(subset=['fed_liq_b','ecb_usd_b','boj_usd_b','cn_usd_b','priv_liq']).iloc[-1]

    def to_js_series(series, label):
        clean = series.dropna()
        dates = [d.strftime('%Y-%m-%d') for d in clean.index]
        vals  = [round(float(v), 4) if not np.isnan(v) else None for v in clean.values]
        return {'label': label, 'dates': dates, 'values': vals}

    # ----- Buy signals: local minima of lqi_z <= -0.3, de-duped by 180-day clusters -----
    def find_local_minima(s, order=60):
        vals, idx = s.values, s.index
        mins = []
        for i in range(order, len(vals) - order):
            if vals[i] == vals[i-order:i+order+1].min():
                mins.append((idx[i], float(vals[i])))
        return mins

    def dedupe_troughs(troughs, gap_days=180):
        out, troughs = [], sorted(troughs, key=lambda x: x[0])
        i = 0
        while i < len(troughs):
            cluster, j = [troughs[i]], i + 1
            while j < len(troughs) and (troughs[j][0] - cluster[0][0]).days < gap_days:
                cluster.append(troughs[j]); j += 1
            out.append(min(cluster, key=lambda x: x[1])); i = j
        return out

    raw_troughs = [(d, v) for d, v in find_local_minima(lqi_z_plot, order=60) if v <= -0.3]
    troughs = dedupe_troughs(raw_troughs, gap_days=180)

    DRAWDOWN_THRESHOLD = 0.5   # close when lqi_z drops 0.5σ from its post-trough peak

    def tier(dz):
        if dz is None:  return 'pending'
        if dz > 1.5:    return 'exceptional'
        if dz > 0.8:    return 'strong'
        if dz > 0.3:    return 'buy'
        if dz < -0.3:   return 'miss'
        return 'flat'

    # Close signal: rolling peak drawdown — close when lqi_z drops DRAWDOWN_THRESHOLD
    # below its highest point since the trough. Minimum 60 days after trough to avoid
    # firing before lqi_z has had a chance to build a meaningful peak.
    def find_close_date(lqi_z, after_date, min_hold_days=60, search_window_days=1000):
        window = lqi_z.loc[after_date:].iloc[:search_window_days]
        if len(window) == 0:
            return None, None
        rolling_peak = window.expanding().max()
        drawdown     = rolling_peak - window
        # Require: (a) at least min_hold_days in, (b) drawdown >= threshold,
        # (c) lqi_z has actually risen above trough before we can draw down from it
        # — i.e. rolling_peak must be above the trough value to avoid firing instantly
        first_val = float(window.iloc[0])
        for i, (date, dd) in enumerate(drawdown.items()):
            if i < min_hold_days:
                continue
            peak_so_far = float(rolling_peak.loc[date])
            if peak_so_far <= first_val + 0.1:  # hasn't risen meaningfully yet
                continue
            if dd >= DRAWDOWN_THRESHOLD:
                return date, round(float(rolling_peak.loc[date]), 3)
        return None, None

    # Lookup helper: find lqi_proj value at a given date (nearest)
    def proj_y_at(date):
        if date is None: return None
        idx = lqi_proj_plot.index.searchsorted(date)
        if idx >= len(lqi_proj_plot): return None
        return round(float(lqi_proj_plot.iloc[idx]), 3)

    buy_signals = []
    for td, tv in troughs:
        entry_date  = td + pd.Timedelta(days=LEAD_DAYS)

        # Close: rolling peak drawdown on lqi_z after the trough
        # The close signal fires on the lqi_z timeline, then shift forward by LEAD_DAYS
        # (same lead as entry) so it appears on the projected/equity chart at the right time
        close_cross, peak_val = find_close_date(lqi_z_plot, td + pd.Timedelta(days=30))
        close_date = (close_cross + pd.Timedelta(days=LEAD_DAYS)) if close_cross is not None else None

        # Equity z-score at entry and close (for historical period)
        def eq_z_at(date):
            if date is None: return None
            i = useq_z_plot.index.searchsorted(date)
            return round(float(useq_z_plot.iloc[i]), 3) if i < len(useq_z_plot) else None

        ez_entry = eq_z_at(entry_date)
        ez_close = eq_z_at(close_date)

        e6i  = useq_z_plot.index.searchsorted(entry_date + pd.Timedelta(days=182)) if ez_entry is not None else None
        e12i = useq_z_plot.index.searchsorted(entry_date + pd.Timedelta(days=365)) if ez_entry is not None else None
        e6z  = float(useq_z_plot.iloc[e6i])  if e6i  is not None and e6i  < len(useq_z_plot) else None
        e12z = float(useq_z_plot.iloc[e12i]) if e12i is not None and e12i < len(useq_z_plot) else None

        d6   = round(e6z  - ez_entry, 3) if e6z  is not None and ez_entry is not None else None
        d12  = round(e12z - ez_entry, 3) if e12z is not None and ez_entry is not None else None

        last_eq = useq_z_plot.index.max()

        # y-positions for projected line markers (for future signals)
        entry_proj_y = proj_y_at(entry_date)
        close_proj_y = proj_y_at(close_date) if close_date is not None else None

        buy_signals.append({
            'trough_date':     td.strftime('%Y-%m-%d'),
            'trough_liq_z':    round(tv, 3),
            'peak_liq_z':      peak_val,
            'entry_date':      entry_date.strftime('%Y-%m-%d'),
            'entry_eq_z':      ez_entry if ez_entry is not None else None,
            'entry_proj_y':    entry_proj_y,
            'entry_is_future': entry_date > last_eq,
            'close_date':      close_date.strftime('%Y-%m-%d') if close_date is not None else None,
            'close_eq_z':      ez_close if ez_close is not None else None,
            'close_proj_y':    close_proj_y,
            'close_is_future': (close_date > last_eq) if close_date is not None else True,
            'fwd_6mo_dz':      d6,
            'fwd_12mo_dz':     d12,
            'tier':            tier(d6),
        })

    payload = {
        'meta': {
            'lead_days':            LEAD_DAYS,
            'smooth_days':          SMOOTH_DAYS,
            'drawdown_threshold':   DRAWDOWN_THRESHOLD,
            'corr_full':            round(float(corr_full), 3),
            'corr_post20':          round(float(corr_post20), 3),
            'last_equity_date':     last_eq_date.strftime('%Y-%m-%d'),
            'proj_end_date':        latest_liq_proj_date,
            'latest_lqi_z':         round(latest_lqi_z, 2),
            'latest_lqi_raw_pct':   round(latest_lqi_raw, 2),
            'latest_proj_z':        round(latest_liq_proj_val, 2),
            'components_b': {
                'Fed':     round(float(latest['fed_liq_b']),  1),
                'ECB':     round(float(latest['ecb_usd_b']),  1),
                'BoJ':     round(float(latest['boj_usd_b']),  1),
                'China FX': round(float(latest['cn_usd_b']),  1),
                # priv_liq is bank credit PLUS the eurodollar leg, so the label
                # has to say so — it read "US Bank Credit" while carrying both.
                'Bank Credit + Eurodollar': round(float(latest['priv_liq']), 1),
            },
        },
        'lqi_z':      to_js_series(lqi_z_plot,   'Acumen Liquidity (z-score)'),
        'useq_z':     to_js_series(useq_z_plot,   'US Equities YoY% (z-score)'),
        'lqi_proj':   to_js_series(lqi_proj_plot, 'Liquidity Projected'),
        'buy_signals': buy_signals,
    }

    if write_file:
        os.makedirs(os.path.dirname(JS_OUTPUT_PATH), exist_ok=True)
        js_content = f"const ACUMEN_LIQUIDITY = {json.dumps(payload, separators=(',', ':'))};"
        with open(JS_OUTPUT_PATH, 'w') as f:
            f.write(js_content)
        print(f"Baked JS written to {JS_OUTPUT_PATH}")
    return payload


# ============================================================================
# PLOT (PNG version)
# ============================================================================

def plot_indicator(liquidity_yoy, useq, lead_days=LEAD_DAYS,
                   plot_start=PLOT_START, output_path=OUTPUT_PATH):
    """Plot the indicator vs USEQUITIES, both as z-scores, liquidity projected forward."""

    useq_yoy = useq.pct_change(365) * 100

    useq_window = useq_yoy.loc[plot_start:].dropna()
    lqi_window  = liquidity_yoy.loc[plot_start:].dropna()
    useq_mean, useq_std = useq_window.mean(), useq_window.std()
    lqi_mean,  lqi_std  = lqi_window.mean(),  lqi_window.std()

    useq_z = (useq_yoy - useq_mean) / useq_std
    lqi_z  = (liquidity_yoy - lqi_mean) / lqi_std

    lqi_projected = lqi_z.copy()
    lqi_projected.index = lqi_projected.index + pd.Timedelta(days=lead_days)

    useq_z_plot = useq_z.loc[plot_start:].dropna()
    lqi_z_plot  = lqi_projected.loc[plot_start:].dropna()

    last_equity_date = useq_z_plot.index.max()
    xmin = pd.Timestamp(plot_start)
    xmax = lqi_z_plot.index.max()

    corr_full = useq_yoy.loc[plot_start:].corr(liquidity_yoy.shift(lead_days).loc[plot_start:])
    corr_post20 = useq_yoy.loc['2020-01-01':].corr(liquidity_yoy.shift(lead_days).loc['2020-01-01':])
    print(f"\nFull sample (2015+) correlation: {corr_full:.3f}")
    print(f"Post-2020 correlation:          {corr_post20:.3f}")
    print(f"Liquidity projection extends to: {lqi_z_plot.index[-1].date()}")
    print(f"Final projected z-score:         {lqi_z_plot.iloc[-1]:+.2f}  "
          f"(raw YoY: {lqi_z_plot.iloc[-1] * lqi_std + lqi_mean:+.1f}%)")

    fig, ax = plt.subplots(figsize=(15, 7.5), facecolor=BG)
    ax.set_facecolor(CARD)

    ax.plot(useq_z_plot.index, useq_z_plot.values, color=BODY, linewidth=1.7,
            label='USEQUITIES YoY % (z-score)', zorder=3)

    historical_part = lqi_z_plot.loc[:last_equity_date]
    future_part     = lqi_z_plot.loc[last_equity_date:]
    ax.plot(historical_part.index, historical_part.values, color=ORANGE, linewidth=2.0,
            label=f'Acumen Liquidity YoY % (z-score, projected {lead_days}d forward)',
            zorder=2)
    ax.plot(future_part.index, future_part.values, color=ORANGE, linewidth=2.0,
            linestyle='--', alpha=0.85, zorder=2,
            label=f'Liquidity projection (next {lead_days} days)')

    ax.axvline(last_equity_date, color=MUTED, linestyle=':', linewidth=1.2, alpha=0.7, zorder=1)
    ax.text(last_equity_date, 0.97, ' today', transform=ax.get_xaxis_transform(),
            color=MUTED, fontsize=9, fontweight='bold', va='top', ha='left')
    ax.axhline(0, color=MUTED, linewidth=0.8, linestyle='--', alpha=0.5, zorder=1)
    ax.axvspan(last_equity_date, xmax, alpha=0.04, color=ORANGE, zorder=0)

    all_vals = pd.concat([useq_z_plot, lqi_z_plot]).dropna()
    ymin, ymax = all_vals.min(), all_vals.max()
    ypad = (ymax - ymin) * 0.08
    ax.set_ylim(ymin - ypad, ymax + ypad)
    xpad = pd.Timedelta(days=30)
    ax.set_xlim(xmin - xpad, xmax + xpad)

    ax.set_ylabel('Z-score (standard deviations from 2015-present mean)',
                  color=BODY, fontsize=11, fontweight='bold')
    ax.tick_params(axis='y', labelcolor=BODY)
    ax.grid(True, which='major', alpha=0.25, color=BORDER)

    fig.suptitle('Acumen Global Liquidity Index leads US Equities',
                 fontsize=17, fontweight='bold', color=HEADER, x=0.5, y=0.97)
    ax.set_title(f"Both series as YoY % z-scores  |  Liquidity projected {lead_days} days forward  |  "
                 f"r = {corr_full:.2f} full sample, {corr_post20:.2f} post-2020",
                 fontsize=10, color=MUTED, pad=12)

    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    plt.setp(ax.get_xticklabels(), rotation=0, ha='center')

    ax.legend(loc='upper left', frameon=True, facecolor=CARD, edgecolor=BORDER, fontsize=9)

    fig.text(0.5, 0.5, 'ACUMEN', ha='center', va='center',
             fontsize=72, color=HEADER, alpha=0.06, fontweight='bold')

    fig.text(0.5, 0.02,
             'Sources: FRED + Yahoo Finance  |  Howell-style construction: Fed + ECB + BoJ + China FX + US bank credit, '
             'drained by oil/MOVE/DXY  |  ACUMEN',
             ha='center', fontsize=7, color=MUTED, style='italic')

    plt.tight_layout(rect=[0.01, 0.04, 0.99, 0.93])
    plt.savefig(output_path, dpi=160, facecolor=BG, bbox_inches='tight')
    print(f"\nSaved: {output_path}")
    return fig


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    m = build_liquidity_index()
    useq = build_usequities(m.index)
    plot_indicator(m['liquidity_yoy'], useq)
    bake_js(m, useq)
