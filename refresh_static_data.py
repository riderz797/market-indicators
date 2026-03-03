"""
Refresh static data for all indicator pages that use the hybrid approach.
Run this script anytime to update embedded historical data to current prices.

Usage: python refresh_static_data.py
"""
import json, urllib.request, re, os
from datetime import datetime, timedelta

FRED_KEY = '824b29c5afa52f3fc7c6e7dc4925aebb'
BASE = os.path.dirname(os.path.abspath(__file__))

def fetch_fred(series_id, start='1980-01-01'):
    url = f'https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_KEY}&file_type=json&observation_start={start}'
    resp = urllib.request.urlopen(url, timeout=30)
    data = json.loads(resp.read())
    dates = [o['date'] for o in data['observations'] if o['value'] != '.']
    values = [float(o['value']) for o in data['observations'] if o['value'] != '.']
    return dates, values

def resample_friday(dates, values):
    weekly = {}
    for d_str, v in zip(dates, values):
        d = datetime.strptime(d_str, '%Y-%m-%d')
        diff = (4 - d.weekday()) % 7
        fri = d + timedelta(days=diff)
        weekly[fri.strftime('%Y-%m-%d')] = v
    items = sorted(weekly.items())
    return [k for k,v in items], [v for k,v in items]

def resample_monday(dates, values):
    weekly = {}
    for d_str, v in zip(dates, values):
        d = datetime.strptime(d_str, '%Y-%m-%d')
        diff = (0 - d.weekday()) % 7
        if diff == 0 and d.weekday() != 0:
            diff = 7
        mon = d + timedelta(days=diff)
        weekly[mon.strftime('%Y-%m-%d')] = v
    items = sorted(weekly.items())
    return [k for k,v in items], [v for k,v in items]

def rd(vals, dec=2):
    return [round(v, dec) for v in vals]

def inject_static(html_path, static_data):
    static_js = json.dumps(static_data, separators=(',', ':'))
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    # Find STATIC_DATA assignment by position (regex can't handle the massive JSON)
    marker = 'const STATIC_DATA = {'
    start = content.find(marker)
    if start == -1:
        print(f'  WARNING: STATIC_DATA not found in {html_path}')
        return
    # Find the matching closing brace by counting braces
    depth = 0
    i = start + len('const STATIC_DATA = ')
    while i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1  # position after closing }
                break
        i += 1
    # Skip the trailing semicolon
    if content[end:end+1] == ';':
        end += 1
    new_assignment = f'const STATIC_DATA = {static_js};'
    content = content[:start] + new_assignment + content[end:]
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'  Injected into {os.path.basename(html_path)} ({len(static_js)//1024}KB static data)')


def main():
    import yfinance as yf

    today = datetime.now().strftime('%Y-%m-%d')
    print(f'Refreshing static data as of {today}\n')

    # ── Fetch shared raw data ──
    print('Fetching FRED M2SL...')
    m2_d, m2_v = fetch_fred('M2SL', '2000-01-01')
    print(f'  {len(m2_d)} pts to {m2_d[-1]}')

    print('Fetching FRED DTWEXBGS (DXY)...')
    dxy_d, dxy_v = fetch_fred('DTWEXBGS', '2000-01-01')
    print(f'  {len(dxy_d)} pts to {dxy_d[-1]}')

    print('Fetching Yahoo BTC-USD...')
    btc_df = yf.download('BTC-USD', start='2013-01-01', interval='1d', progress=False)
    btc_d = [d.strftime('%Y-%m-%d') for d in btc_df.index]
    btc_v = [float(v) for v in btc_df['Close'].values.flatten()]
    print(f'  {len(btc_d)} pts to {btc_d[-1]} (${btc_v[-1]:,.0f})')

    print('Fetching Yahoo DX-Y.NYB...')
    dxy_yahoo_df = yf.download('DX-Y.NYB', start='2000-01-01', interval='1d', progress=False)
    dxy_yahoo_d = [d.strftime('%Y-%m-%d') for d in dxy_yahoo_df.index]
    dxy_yahoo_v = [float(v) for v in dxy_yahoo_df['Close'].values.flatten()]
    print(f'  {len(dxy_yahoo_d)} pts to {dxy_yahoo_d[-1]}')

    # ── 1. BTC Liquidity Backtest (Friday-resampled, uses Yahoo DXY) ──
    print('\n=== BTC Liquidity Backtest ===')
    btc_fri_d, btc_fri_v = resample_friday(btc_d, btc_v)
    m2_fri_d, m2_fri_v = resample_friday(m2_d, m2_v)
    dxy_fri_d, dxy_fri_v = resample_friday(dxy_yahoo_d, dxy_yahoo_v)
    liq_static = {
        'generated': today,
        'btc': {'dates': btc_fri_d, 'values': rd(btc_fri_v)},
        'm2': {'dates': m2_fri_d, 'values': rd(m2_fri_v, 1)},
        'dxy': {'dates': dxy_fri_d, 'values': rd(dxy_fri_v, 4)},
    }
    inject_static(os.path.join(BASE, 'indicators/btc/btc_liquidity_backtest.html'), liq_static)

    # ── 2. BTC Mean Reversion (Monday-resampled, uses FRED DXY) ──
    print('\n=== BTC Mean Reversion ===')
    btc_mon_d, btc_mon_v = resample_monday(btc_d, btc_v)
    m2_mon_d, m2_mon_v = resample_monday(m2_d, m2_v)
    dxy_mon_d, dxy_mon_v = resample_monday(dxy_d, dxy_v)
    mr_static = {
        'generated': today,
        'btc': {'dates': btc_mon_d, 'values': rd(btc_mon_v)},
        'm2': {'dates': m2_mon_d, 'values': rd(m2_mon_v, 1)},
        'dxy': {'dates': dxy_mon_d, 'values': rd(dxy_mon_v, 4)},
    }
    inject_static(os.path.join(BASE, 'indicators/btc/btc_mean_reversion.html'), mr_static)

    # ── 3. Financial Conditions Index (Friday-resampled, 14 series) ──
    print('\n=== Financial Conditions Index ===')
    fci_fred_ids = ['WALCL', 'DGS10', 'DGS2', 'SP500', 'DJIA', 'T10YIE',
                    'RRPONTSYD', 'SOFR', 'IORB', 'BAMLH0A0HYM2', 'VIXCLS', 'DTWEXBGS']
    fci_static = {'generated': today}

    for sid in fci_fred_ids:
        try:
            raw_d, raw_v = fetch_fred(sid, '1980-01-01')
            d, v = resample_friday(raw_d, raw_v)
            if sid == 'WALCL':
                fci_static[sid] = {'dates': d, 'values': rd(v, 0)}
            elif sid in ('SP500', 'DJIA', 'RRPONTSYD'):
                fci_static[sid] = {'dates': d, 'values': rd(v, 2)}
            else:
                fci_static[sid] = {'dates': d, 'values': rd(v, 4)}
            print(f'  {sid}: {len(d)} weeks')
        except Exception as e:
            print(f'  {sid}: FAILED ({e})')

    # Gold via yfinance
    print('  Fetching Gold (GC=F)...')
    gold_df = yf.download('GC=F', start='1990-01-01', interval='1d', progress=False)
    gold_d = [d.strftime('%Y-%m-%d') for d in gold_df.index]
    gold_v = [float(v) for v in gold_df['Close'].values.flatten()]
    g_d, g_v = resample_friday(gold_d, gold_v)
    fci_static['GOLD'] = {'dates': g_d, 'values': rd(g_v, 2)}
    print(f'  GOLD: {len(g_d)} weeks')

    # BTC (reuse from above)
    fci_static['BTC'] = {'dates': btc_fri_d, 'values': rd(btc_fri_v)}

    # TGA
    print('  Fetching TGA...')
    try:
        tga_url = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance?filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Opening%20Balance&sort=-record_date&page[size]=10000'
        resp = urllib.request.urlopen(tga_url, timeout=30)
        tga_data = json.loads(resp.read())
        tga_d = [row['record_date'] for row in tga_data['data']]
        tga_v = [float(row['open_today_bal']) / 1000 for row in tga_data['data']]
        tga_d.reverse(); tga_v.reverse()
        td, tv = resample_friday(tga_d, tga_v)
        fci_static['TGA'] = {'dates': td, 'values': rd(tv, 0)}
        print(f'  TGA: {len(td)} weeks')
    except Exception as e:
        print(f'  TGA: FAILED ({e})')

    inject_static(os.path.join(BASE, 'indicators/fci/financial_conditions_index.html'), fci_static)

    print(f'\nDone! Run "git add -A && git commit && git push" to deploy.')


if __name__ == '__main__':
    main()
