"""
fetch_macro_cycle.py
Bakes the FRED observations behind the Macro Cycle Dashboard into
indicators/macro/macro_cycle_data.json.

The dashboard fetches FRED in the browser through free CORS proxies (FRED sends
no CORS headers). When those proxies are down the page has nothing to score
with, so it now loads this file first and only upgrades to live values when a
proxy answers. Each entry mirrors one fetchFRED() call in the page — same
series, limit and observation_end — so the page reads it exactly as it would
a live response.

Run:  FRED_API_KEY=... python fetch_macro_cycle.py
Reads the key from the environment only (GitHub Actions secret, or the
workflow's fallback); without one it leaves the existing file in place.
"""

import json
import os
import sys
from datetime import date, datetime, timezone

import requests

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   'indicators', 'macro', 'macro_cycle_data.json')
FRED_KEY = os.environ.get('FRED_API_KEY', '')


def year_ago():
    t = date.today()
    try:
        return t.replace(year=t.year - 1).isoformat()
    except ValueError:                       # 29 Feb
        return t.replace(year=t.year - 1, day=28).isoformat()


# key -> (series_id, limit, observation_end) — matches the page's Promise.all
CALLS = {
    'BAMLH0A0HYM2': ('BAMLH0A0HYM2', 5, None),
    'DRTSCILM':     ('DRTSCILM',     5, None),
    'T10Y2Y':       ('T10Y2Y',       5, None),
    'DFII10':       ('DFII10',       5, None),
    'FEDFUNDS':     ('FEDFUNDS',     3, None),
    'FEDFUNDS_1y':  ('FEDFUNDS',     3, 'YEAR_AGO'),
    'DTWEXBGS':     ('DTWEXBGS',     5, None),
    'DTWEXBGS_1y':  ('DTWEXBGS',     5, 'YEAR_AGO'),
}


def fetch(series_id, limit, observation_end):
    p = {'series_id': series_id, 'api_key': FRED_KEY, 'file_type': 'json',
         'sort_order': 'desc', 'limit': limit}
    if observation_end:
        p['observation_end'] = observation_end
    r = requests.get('https://api.stlouisfed.org/fred/series/observations',
                     params=p, timeout=30)
    r.raise_for_status()
    return [{'date': o['date'], 'value': o['value']} for o in r.json()['observations']]


def main():
    if not FRED_KEY:
        print('FRED_API_KEY not set — keeping existing macro_cycle_data.json.')
        return 0
    try:
        old = json.load(open(OUT, encoding='utf-8'))['obs']
    except (OSError, ValueError, KeyError):
        old = {}

    ya = year_ago()
    obs, failed = {}, []
    for key, (sid, limit, end) in CALLS.items():
        try:
            obs[key] = fetch(sid, limit, ya if end == 'YEAR_AGO' else None)
            print(f'  {key:13s} {len(obs[key])} obs, latest {obs[key][0]["date"]}')
        except Exception as e:
            failed.append(key)
            if key in old:
                obs[key] = old[key]          # keep last good copy of this series
            print(f'  {key:13s} FAILED ({e}){" — kept previous" if key in old else ""}')

    if not obs:
        print('No series fetched — leaving file untouched.')
        return 1
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'as_of': date.today().isoformat(),
                   'updated_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'obs': obs}, f, indent=1)
    print(f'Wrote {os.path.relpath(OUT)} ({len(obs)} series, {len(failed)} failed)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
