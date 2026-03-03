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

    print(f'\nDone! BTC at ${btc_v[-1]:,.0f}')


if __name__ == '__main__':
    main()
