"""
Rebuild all 3 indicator pages with fresh data + JS templates.
Fetches historical data via FRED & yfinance, injects into HTML files.

Usage: python rebuild_all.py
"""
import json, urllib.request, os
from datetime import datetime, timedelta

FRED_KEY = '824b29c5afa52f3fc7c6e7dc4925aebb'
BASE = os.path.dirname(os.path.abspath(__file__))

# Rounding precision per FRED series
SERIES_PRECISION = {
    'WALCL': 0,
    'SP500': 2, 'DJIA': 2, 'RRPONTSYD': 2,
}
DEFAULT_PRECISION = 4


def fetch_fred(series_id, start='1980-01-01'):
    url = (f'https://api.stlouisfed.org/fred/series/observations'
           f'?series_id={series_id}&api_key={FRED_KEY}'
           f'&file_type=json&observation_start={start}')
    data = json.loads(urllib.request.urlopen(url, timeout=30).read())
    obs = [(o['date'], float(o['value'])) for o in data['observations'] if o['value'] != '.']
    return [o[0] for o in obs], [o[1] for o in obs]


def fetch_yfinance(ticker, start):
    import yfinance as yf
    df = yf.download(ticker, start=start, interval='1d', progress=False)
    dates = [d.strftime('%Y-%m-%d') for d in df.index]
    values = [float(v) for v in df['Close'].values.flatten()]
    return dates, values


def fetch_tga():
    url = ('https://api.fiscaldata.treasury.gov/services/api/fiscal_service'
           '/v1/accounting/dts/operating_cash_balance'
           '?filter=account_type:eq:Treasury%20General%20Account%20(TGA)'
           '%20Opening%20Balance&sort=-record_date&page[size]=10000')
    data = json.loads(urllib.request.urlopen(url, timeout=30).read())
    rows = data['data']
    dates = [r['record_date'] for r in reversed(rows)]
    values = [float(r['open_today_bal']) / 1000 for r in reversed(rows)]
    return dates, values


def resample_weekly(dates, values, target_day):
    """Resample daily data to weekly buckets. target_day: 0=Monday, 4=Friday."""
    weekly = {}
    for d_str, v in zip(dates, values):
        d = datetime.strptime(d_str, '%Y-%m-%d')
        diff = (target_day - d.weekday()) % 7
        if target_day == 0 and diff == 0 and d.weekday() != 0:
            diff = 7
        bucket = d + timedelta(days=diff)
        weekly[bucket.strftime('%Y-%m-%d')] = v
    items = sorted(weekly.items())
    return [k for k, _ in items], [v for _, v in items]


def rd(vals, dec=2):
    return [round(v, dec) for v in vals]


def replace_script_block(html_path, new_script):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    marker = '<script>\nconst FRED_API_KEY'
    start = content.find(marker)
    if start == -1:
        # Fallback: try the STATIC_DATA marker
        marker = '<script>\n// ===== STATIC DATA'
        start = content.find(marker)
    if start == -1:
        print(f'  ERROR: script marker not found in {html_path}')
        return False
    end = content.find('</script>', start)
    if end == -1:
        print(f'  ERROR: </script> not found in {html_path}')
        return False
    end += len('</script>')
    old_size = len(content)
    content = content[:start] + new_script + content[end:]
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'  {os.path.basename(html_path)}: {old_size:,} -> {len(content):,} ({len(content)-old_size:+,})')
    return True


def build_script(js_template_name, static_data):
    js_path = os.path.join(BASE, 'scripts', js_template_name)
    js_code = open(js_path, encoding='utf-8').read()
    static_json = json.dumps(static_data, separators=(',', ':'))
    return '<script>\n' + js_code.replace('__STATIC_DATA__', static_json) + '\n</script>'


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print(f'Rebuilding indicator pages as of {today}\n')

    # ── Fetch shared data ──
    print('FRED M2SL...')
    m2_d, m2_v = fetch_fred('M2SL', '2000-01-01')
    print(f'  {len(m2_d)} pts to {m2_d[-1]}')

    print('FRED DTWEXBGS (DXY)...')
    fred_dxy_d, fred_dxy_v = fetch_fred('DTWEXBGS', '2000-01-01')
    print(f'  {len(fred_dxy_d)} pts to {fred_dxy_d[-1]}')

    print('Yahoo BTC-USD...')
    btc_d, btc_v = fetch_yfinance('BTC-USD', '2013-01-01')
    print(f'  {len(btc_d)} pts to {btc_d[-1]} (${btc_v[-1]:,.0f})')

    print('Yahoo DX-Y.NYB...')
    yahoo_dxy_d, yahoo_dxy_v = fetch_yfinance('DX-Y.NYB', '2000-01-01')
    print(f'  {len(yahoo_dxy_d)} pts to {yahoo_dxy_d[-1]}')

    # ── 1. BTC Liquidity Backtest (Friday-resampled, Yahoo DXY) ──
    print('\n=== BTC Liquidity Backtest ===')
    btc_fri_d, btc_fri_v = resample_weekly(btc_d, btc_v, 4)
    m2_fri_d, m2_fri_v = resample_weekly(m2_d, m2_v, 4)
    dxy_fri_d, dxy_fri_v = resample_weekly(yahoo_dxy_d, yahoo_dxy_v, 4)

    liq_script = build_script('btc_liquidity_script.js', {
        'generated': today,
        'btc': {'dates': btc_fri_d, 'values': rd(btc_fri_v)},
        'm2':  {'dates': m2_fri_d,  'values': rd(m2_fri_v, 1)},
        'dxy': {'dates': dxy_fri_d, 'values': rd(dxy_fri_v, 4)},
    })
    replace_script_block(
        os.path.join(BASE, 'indicators/btc/btc_liquidity_backtest.html'), liq_script)

    # ── 2. BTC Mean Reversion (Monday-resampled, FRED DXY) ──
    print('\n=== BTC Mean Reversion ===')
    btc_mon_d, btc_mon_v = resample_weekly(btc_d, btc_v, 0)
    m2_mon_d, m2_mon_v = resample_weekly(m2_d, m2_v, 0)
    dxy_mon_d, dxy_mon_v = resample_weekly(fred_dxy_d, fred_dxy_v, 0)

    mr_script = build_script('btc_mean_reversion_script.js', {
        'generated': today,
        'btc': {'dates': btc_mon_d, 'values': rd(btc_mon_v)},
        'm2':  {'dates': m2_mon_d,  'values': rd(m2_mon_v, 1)},
        'dxy': {'dates': dxy_mon_d, 'values': rd(dxy_mon_v, 4)},
    })
    replace_script_block(
        os.path.join(BASE, 'indicators/btc/btc_mean_reversion.html'), mr_script)

    # ── 3. Financial Conditions Index (Friday-resampled, 14 series) ──
    print('\n=== Financial Conditions Index ===')
    fci_fred_ids = ['WALCL', 'DGS10', 'DGS2', 'SP500', 'DJIA', 'T10YIE',
                    'RRPONTSYD', 'SOFR', 'IORB', 'BAMLH0A0HYM2', 'VIXCLS', 'DTWEXBGS']
    fci_static = {'generated': today}

    for sid in fci_fred_ids:
        try:
            if sid == 'DTWEXBGS':
                raw_d, raw_v = fred_dxy_d, fred_dxy_v
            else:
                raw_d, raw_v = fetch_fred(sid, '1980-01-01')
            d, v = resample_weekly(raw_d, raw_v, 4)
            prec = SERIES_PRECISION.get(sid, DEFAULT_PRECISION)
            fci_static[sid] = {'dates': d, 'values': rd(v, prec)}
            print(f'  {sid}: {len(d)} weeks')
        except Exception as e:
            print(f'  {sid}: FAILED ({e})')

    print('  Gold (GC=F)...')
    gold_d, gold_v = fetch_yfinance('GC=F', '1990-01-01')
    g_d, g_v = resample_weekly(gold_d, gold_v, 4)
    fci_static['GOLD'] = {'dates': g_d, 'values': rd(g_v, 2)}
    print(f'  GOLD: {len(g_d)} weeks')

    fci_static['BTC'] = {'dates': btc_fri_d, 'values': rd(btc_fri_v)}

    print('  TGA...')
    try:
        tga_d, tga_v = fetch_tga()
        td, tv = resample_weekly(tga_d, tga_v, 4)
        fci_static['TGA'] = {'dates': td, 'values': rd(tv, 0)}
        print(f'  TGA: {len(td)} weeks')
    except Exception as e:
        print(f'  TGA: FAILED ({e})')

    fci_script = build_script('fci_script.js', fci_static)
    replace_script_block(
        os.path.join(BASE, 'indicators/fci/financial_conditions_index.html'), fci_script)

    # ── 4. MSTR Credit-Vol Regime Indicator ──────────────────────────────
    print('\n=== MSTR Credit-Vol Regime ===')

    # Strategy BTC holdings — cumulative total after each purchase
    # Source: strategy.com/purchases via bitbo.io
    MSTR_HOLDINGS = [
        ('2020-08-11', 21454),  ('2020-09-14', 38250),  ('2020-12-04', 40824),
        ('2020-12-21', 70470),  ('2021-01-22', 70784),  ('2021-02-02', 71079),
        ('2021-02-24', 90531),  ('2021-03-01', 90859),  ('2021-03-05', 91064),
        ('2021-03-12', 91326),  ('2021-04-05', 91579),  ('2021-05-13', 91850),
        ('2021-05-18', 92079),  ('2021-06-21', 105085), ('2021-09-13', 114042),
        ('2021-11-28', 121044), ('2021-12-08', 122478), ('2021-12-30', 124391),
        ('2022-01-31', 125051), ('2022-04-05', 129218), ('2022-06-28', 129699),
        ('2022-09-20', 130000), ('2022-12-22', 131690), ('2022-12-24', 132500),
        ('2023-03-27', 138955), ('2023-04-05', 140000), ('2023-06-27', 152333),
        ('2023-07-31', 152800), ('2023-09-24', 158245), ('2023-11-30', 174530),
        ('2023-12-27', 189150), ('2024-02-06', 190000), ('2024-02-26', 193000),
        ('2024-03-11', 205000), ('2024-03-19', 214246), ('2024-05-01', 214400),
        ('2024-06-20', 226331), ('2024-08-01', 226500), ('2024-09-13', 244800),
        ('2024-09-20', 252220), ('2024-11-11', 279420), ('2024-11-18', 331200),
        ('2024-11-25', 386700), ('2024-12-02', 402100), ('2024-12-09', 423650),
        ('2024-12-16', 439000), ('2024-12-23', 444262), ('2024-12-30', 446400),
        ('2025-01-06', 447470), ('2025-01-13', 450000), ('2025-01-21', 461000),
        ('2025-01-27', 471107), ('2025-02-10', 478740), ('2025-02-24', 499096),
        ('2025-03-17', 499226), ('2025-03-24', 506137), ('2025-03-31', 528185),
        ('2025-04-14', 531644), ('2025-04-21', 538200), ('2025-04-28', 553555),
        ('2025-05-05', 555450), ('2025-05-12', 568840), ('2025-05-19', 576230),
        ('2025-05-26', 580250), ('2025-06-02', 580955), ('2025-06-16', 592100),
        ('2025-06-23', 592345), ('2025-06-30', 597325), ('2025-07-14', 601550),
        ('2025-07-21', 607770), ('2025-07-29', 628791), ('2025-08-11', 629096),
        ('2025-08-18', 629376), ('2025-08-25', 632457), ('2025-09-02', 636505),
        ('2025-09-08', 638460), ('2025-09-15', 638985), ('2025-09-22', 639835),
        ('2025-09-29', 640031), ('2025-10-13', 640250), ('2025-10-20', 640418),
        ('2025-10-27', 640808), ('2025-11-03', 641205), ('2025-11-10', 641692),
        ('2025-11-17', 649870), ('2025-12-01', 650000), ('2025-12-08', 660624),
        ('2025-12-15', 671268), ('2025-12-29', 672497), ('2025-12-31', 672500),
        ('2026-01-05', 673783), ('2026-01-12', 687410), ('2026-01-20', 709715),
        ('2026-01-26', 712647), ('2026-02-02', 713502), ('2026-02-09', 714644),
        ('2026-02-17', 717131), ('2026-02-23', 717722), ('2026-03-02', 720737),
        ('2026-03-09', 738731), ('2026-03-16', 761068),
    ]

    # Shares outstanding — quarterly approximations from SEC filings
    MSTR_SHARES_FALLBACK = [
        ('2020-08-01',  9_940_000), ('2021-01-01', 10_100_000),
        ('2021-04-01', 10_300_000), ('2021-07-01', 11_170_000),
        ('2021-10-01', 11_250_000), ('2022-01-01', 11_300_000),
        ('2022-07-01', 11_390_000), ('2023-01-01', 11_535_000),
        ('2023-04-01', 12_300_000), ('2023-07-01', 13_340_000),
        ('2023-10-01', 14_250_000), ('2024-01-01', 15_100_000),
        ('2024-04-01', 16_400_000), ('2024-07-01', 19_600_000),
        ('2024-10-01', 20_000_000), ('2025-01-01', 24_500_000),
        ('2025-04-01', 30_000_000), ('2025-07-01', 34_000_000),
        ('2025-10-01', 36_000_000), ('2026-01-01', 39_000_000),
    ]

    def step_lookup(table, date_str):
        """Return the most recent value from a (date, value) table."""
        result = table[0][1] if table else 0
        for d, v in table:
            if d <= date_str:
                result = v
            else:
                break
        return result

    try:
        # Fetch MOVE Index
        print('  Yahoo ^MOVE...')
        move_d, move_v = fetch_yfinance('^MOVE', '2019-01-01')
        print(f'  MOVE: {len(move_d)} pts to {move_d[-1]}')

        # HY OAS from FRED
        print('  FRED BAMLH0A0HYM2...')
        hy_d, hy_v = fetch_fred('BAMLH0A0HYM2', '2019-01-01')
        print(f'  HY OAS: {len(hy_d)} pts to {hy_d[-1]}')

        # MSTR price
        print('  Yahoo MSTR...')
        mstr_d, mstr_v = fetch_yfinance('MSTR', '2020-01-01')
        print(f'  MSTR: {len(mstr_d)} pts to {mstr_d[-1]} (${mstr_v[-1]:,.0f})')

        # Shares outstanding — try yfinance, fall back to hardcoded
        import yfinance as yf
        import math
        shares_data = MSTR_SHARES_FALLBACK
        try:
            sf = yf.Ticker('MSTR').get_shares_full(start='2020-01-01')
            if sf is not None and len(sf) > 0:
                shares_data = sorted(
                    [(d.strftime('%Y-%m-%d'), int(v)) for d, v in sf.items()
                     if not math.isnan(v)],
                    key=lambda x: x[0])
                print(f'  Shares: {len(shares_data)} data points (yfinance)')
            else:
                print(f'  Shares: using fallback ({len(MSTR_SHARES_FALLBACK)} quarterly pts)')
        except Exception as e:
            print(f'  Shares: get_shares_full failed ({e}), using fallback')

        # Resample to Friday
        move_fri_d, move_fri_v  = resample_weekly(move_d, move_v, 4)
        hy_fri_d, hy_fri_v      = resample_weekly(hy_d, hy_v, 4)
        mstr_fri_d, mstr_fri_v  = resample_weekly(mstr_d, mstr_v, 4)
        # btc_fri_d / btc_fri_v already computed above

        # Align to common Friday dates (where all 4 series exist)
        common = sorted(
            set(move_fri_d) & set(hy_fri_d) & set(mstr_fri_d) & set(btc_fri_d))

        move_map = dict(zip(move_fri_d, move_fri_v))
        hy_map   = dict(zip(hy_fri_d, hy_fri_v))
        mstr_map = dict(zip(mstr_fri_d, mstr_fri_v))
        btc_map  = dict(zip(btc_fri_d, btc_fri_v))

        # Build aligned vectors starting from first BTC purchase
        dates_a, move_a, hy_a, nav_a, btc_ps_a = [], [], [], [], []
        for d in common:
            if d < '2020-08-11':
                continue
            hold = step_lookup(MSTR_HOLDINGS, d)
            if hold == 0:
                continue
            shares = step_lookup(shares_data, d)
            btc_p  = btc_map[d]
            mstr_p = mstr_map[d]
            nav    = hold * btc_p
            mkt    = mstr_p * shares
            prem   = (mkt / nav - 1) * 100 if nav > 0 else None
            bps    = hold / shares if shares > 0 else None
            dates_a.append(d)
            move_a.append(move_map[d])
            hy_a.append(hy_map[d])
            nav_a.append(prem)
            btc_ps_a.append(bps)

        # Rolling 52-week z-score
        W = 52
        def rolling_z(vals):
            z = []
            for i in range(len(vals)):
                if i < W - 1 or vals[i] is None:
                    z.append(None); continue
                win = [v for v in vals[max(0, i - W + 1):i + 1] if v is not None]
                if len(win) < W // 2:
                    z.append(None); continue
                mu = sum(win) / len(win)
                sd = (sum((v - mu) ** 2 for v in win) / len(win)) ** 0.5
                z.append(0.0 if sd == 0 else (vals[i] - mu) / sd)
            return z

        # BTC-per-share momentum (4-week % change)
        MOM_W = 4
        bps_mom = []
        for i in range(len(btc_ps_a)):
            if (i < MOM_W or btc_ps_a[i] is None
                    or btc_ps_a[i - MOM_W] is None
                    or btc_ps_a[i - MOM_W] == 0):
                bps_mom.append(None)
            else:
                bps_mom.append(
                    (btc_ps_a[i] / btc_ps_a[i - MOM_W] - 1) * 100)

        mz = rolling_z(move_a)
        hz = rolling_z(hy_a)
        bps_mz = rolling_z(bps_mom)

        # Composite: 0.5×(-MOVE Z) + 0.2×(-HY Z) + 0.3×(BTC/share momentum Z)
        stress = [
            None if (m is None or h is None or b is None)
            else 0.5 * (-m) + 0.2 * (-h) + 0.3 * b
            for m, h, b in zip(mz, hz, bps_mz)]

        # Trim to valid rows only
        fd, fs, fmz, fhz, fn, fmr, fhr, fbps, fconf = \
            [], [], [], [], [], [], [], [], []
        for i in range(len(dates_a)):
            if stress[i] is not None and nav_a[i] is not None:
                fd.append(dates_a[i])
                fs.append(round(stress[i], 3))
                fmz.append(round(mz[i], 3))
                fhz.append(round(hz[i], 3))
                fn.append(round(nav_a[i], 1))
                fmr.append(round(move_a[i], 2))
                fhr.append(round(hy_a[i], 4))
                fbps.append(round(bps_mz[i], 3))
                # Confidence: all 3 components agree directionally?
                m, h, b = mz[i], hz[i], bps_mz[i]
                bull = (m < 0 and h < 0 and b > 0)  # easing MOVE, tight spreads, growing BTC/share
                bear = (m > 0 and h > 0 and b < 0)  # all unfavorable
                fconf.append(1 if bull else (-1 if bear else 0))

        print(f'  Output: {len(fd)} weeks  {fd[0]} -> {fd[-1]}')

        mstr_script = build_script('mstr_stress_script.js', {
            'generated': today,
            'dates': fd, 'stress_index': fs,
            'move_z': fmz, 'hy_oas_z': fhz,
            'nav_premium': fn,
            'move_raw': fmr, 'hy_oas_raw': fhr,
            'btc_ps_mom_z': fbps, 'confidence': fconf,
        })
        replace_script_block(
            os.path.join(BASE, 'indicators/btc/mstr_stress_indicator.html'),
            mstr_script)

    except Exception as e:
        print(f'  MSTR indicator FAILED: {e}')

    # ── 5. Acumen Global Liquidity Indicator ─────────────────────────────────
    print('\n=== Acumen Global Liquidity Indicator ===')
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'acumen_liq', os.path.join(BASE, 'acumen_liquidity_indicator.py'))
        acumen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(acumen)

        m    = acumen.build_liquidity_index()
        useq = acumen.build_usequities(m.index)
        payload = acumen.bake_js(m, useq, write_file=False)

        liq_script = build_script('acumen_liquidity_script.js', payload)
        replace_script_block(
            os.path.join(BASE, 'indicators/macro/acumen_liquidity.html'),
            liq_script)
        meta = payload['meta']
        print(f"  Liquidity: last equity {meta['last_equity_date']} · "
              f"projection to {meta['proj_end_date']} · "
              f"r={meta['corr_full']}")
    except Exception as e:
        import traceback
        print(f'  Acumen Liquidity FAILED: {e}')
        traceback.print_exc()

    # ── Capital Flows ──────────────────────────────────────────────────────
    print('\n-- Capital Flows --')
    try:
        import importlib.util, sys
        cf_path = os.path.join(BASE, 'fetch_capital_flows.py')
        spec = importlib.util.spec_from_file_location('fetch_capital_flows', cf_path)
        cf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cf)
        cf.main()
    except Exception as e:
        import traceback
        print(f'  Capital Flows FAILED: {e}')
        traceback.print_exc()

    print(f'\nDone! BTC at ${btc_v[-1]:,.0f}')


if __name__ == '__main__':
    main()
