"""
Full rebuild: fetch fresh static data, inject hybrid scripts into all 3 indicator pages.
Replaces the entire <script> block in each file.
"""
import json, urllib.request, os
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

def replace_script_block(html_path, new_script):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the <script> block that starts with FRED_API_KEY
    marker = '<script>\nconst FRED_API_KEY'
    start = content.find(marker)
    if start == -1:
        print(f'  ERROR: Script marker not found in {html_path}')
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


# ============================================================
# Fetch all data
# ============================================================
print(f'Fetching data as of {datetime.now().strftime("%Y-%m-%d")}...\n')

import yfinance as yf

print('FRED M2SL...')
m2_d, m2_v = fetch_fred('M2SL', '2000-01-01')
print(f'  {len(m2_d)} pts to {m2_d[-1]}')

print('FRED DTWEXBGS...')
fred_dxy_d, fred_dxy_v = fetch_fred('DTWEXBGS', '2000-01-01')
print(f'  {len(fred_dxy_d)} pts to {fred_dxy_d[-1]}')

print('Yahoo BTC-USD...')
btc_df = yf.download('BTC-USD', start='2013-01-01', interval='1d', progress=False)
btc_d = [d.strftime('%Y-%m-%d') for d in btc_df.index]
btc_v = [float(v) for v in btc_df['Close'].values.flatten()]
print(f'  {len(btc_d)} pts to {btc_d[-1]} (${btc_v[-1]:,.0f})')

print('Yahoo DX-Y.NYB...')
dxy_df = yf.download('DX-Y.NYB', start='2000-01-01', interval='1d', progress=False)
yahoo_dxy_d = [d.strftime('%Y-%m-%d') for d in dxy_df.index]
yahoo_dxy_v = [float(v) for v in dxy_df['Close'].values.flatten()]
print(f'  {len(yahoo_dxy_d)} pts to {yahoo_dxy_d[-1]}')

# FCI extra series
print('\nFCI FRED series...')
fci_fred_ids = ['WALCL', 'DGS10', 'DGS2', 'SP500', 'DJIA', 'T10YIE',
                'RRPONTSYD', 'SOFR', 'IORB', 'BAMLH0A0HYM2', 'VIXCLS']
fci_raw = {}
for sid in fci_fred_ids:
    try:
        d, v = fetch_fred(sid, '1980-01-01')
        fci_raw[sid] = (d, v)
        print(f'  {sid}: {len(d)} pts')
    except Exception as e:
        print(f'  {sid}: FAILED ({e})')

print('Yahoo Gold GC=F...')
gold_df = yf.download('GC=F', start='1990-01-01', interval='1d', progress=False)
gold_d = [d.strftime('%Y-%m-%d') for d in gold_df.index]
gold_v = [float(v) for v in gold_df['Close'].values.flatten()]
print(f'  {len(gold_d)} pts')

print('TGA...')
try:
    tga_url = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance?filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Opening%20Balance&sort=-record_date&page[size]=10000'
    resp = urllib.request.urlopen(tga_url, timeout=30)
    tga_data = json.loads(resp.read())
    tga_d_raw = [row['record_date'] for row in tga_data['data']]
    tga_v_raw = [float(row['open_today_bal']) / 1000 for row in tga_data['data']]
    tga_d_raw.reverse(); tga_v_raw.reverse()
    print(f'  {len(tga_d_raw)} pts')
except Exception as e:
    tga_d_raw, tga_v_raw = [], []
    print(f'  FAILED ({e})')

today = datetime.now().strftime('%Y-%m-%d')

# ============================================================
# 1. BTC Liquidity Backtest
# ============================================================
print('\n=== BTC Liquidity Backtest ===')
btc_fri_d, btc_fri_v = resample_friday(btc_d, btc_v)
m2_fri_d, m2_fri_v = resample_friday(m2_d, m2_v)
dxy_fri_d, dxy_fri_v = resample_friday(yahoo_dxy_d, yahoo_dxy_v)

liq_static = json.dumps({
    'generated': today,
    'btc': {'dates': btc_fri_d, 'values': rd(btc_fri_v)},
    'm2': {'dates': m2_fri_d, 'values': rd(m2_fri_v, 1)},
    'dxy': {'dates': dxy_fri_d, 'values': rd(dxy_fri_v, 4)},
}, separators=(',', ':'))

liq_script = '<script>\n' + open(os.path.join(BASE, 'scripts/btc_liquidity_script.js')).read().replace('__STATIC_DATA__', liq_static) + '\n</script>'
replace_script_block(os.path.join(BASE, 'indicators/btc/btc_liquidity_backtest.html'), liq_script)

# ============================================================
# 2. BTC Mean Reversion
# ============================================================
print('\n=== BTC Mean Reversion ===')
btc_mon_d, btc_mon_v = resample_monday(btc_d, btc_v)
m2_mon_d, m2_mon_v = resample_monday(m2_d, m2_v)
dxy_mon_d, dxy_mon_v = resample_monday(fred_dxy_d, fred_dxy_v)

mr_static = json.dumps({
    'generated': today,
    'btc': {'dates': btc_mon_d, 'values': rd(btc_mon_v)},
    'm2': {'dates': m2_mon_d, 'values': rd(m2_mon_v, 1)},
    'dxy': {'dates': dxy_mon_d, 'values': rd(dxy_mon_v, 4)},
}, separators=(',', ':'))

mr_script = '<script>\n' + open(os.path.join(BASE, 'scripts/btc_mean_reversion_script.js')).read().replace('__STATIC_DATA__', mr_static) + '\n</script>'
replace_script_block(os.path.join(BASE, 'indicators/btc/btc_mean_reversion.html'), mr_script)

# ============================================================
# 3. Financial Conditions Index
# ============================================================
print('\n=== Financial Conditions Index ===')
fci_static = {'generated': today}
for sid in fci_fred_ids + ['DTWEXBGS']:
    if sid == 'DTWEXBGS':
        raw_d, raw_v = fred_dxy_d, fred_dxy_v
    elif sid in fci_raw:
        raw_d, raw_v = fci_raw[sid]
    else:
        continue
    d, v = resample_friday(raw_d, raw_v)
    if sid == 'WALCL':
        fci_static[sid] = {'dates': d, 'values': rd(v, 0)}
    elif sid in ('SP500', 'DJIA', 'RRPONTSYD'):
        fci_static[sid] = {'dates': d, 'values': rd(v, 2)}
    else:
        fci_static[sid] = {'dates': d, 'values': rd(v, 4)}

g_d, g_v = resample_friday(gold_d, gold_v)
fci_static['GOLD'] = {'dates': g_d, 'values': rd(g_v, 2)}
fci_static['BTC'] = {'dates': btc_fri_d, 'values': rd(btc_fri_v)}
if tga_d_raw:
    td, tv = resample_friday(tga_d_raw, tga_v_raw)
    fci_static['TGA'] = {'dates': td, 'values': rd(tv, 0)}

fci_json = json.dumps(fci_static, separators=(',', ':'))

fci_script = '<script>\n' + open(os.path.join(BASE, 'scripts/fci_script.js')).read().replace('__STATIC_DATA__', fci_json) + '\n</script>'
replace_script_block(os.path.join(BASE, 'indicators/fci/financial_conditions_index.html'), fci_script)

print('\nDone!')
