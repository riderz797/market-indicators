"""
Fetch Bitcoin (BTC-USD) daily history via yfinance and output JavaScript data
with both dates and close prices for each year (2014+).

Usage:  python bake_btc.py > btc_baked.js
"""
import json, sys
import yfinance as yf
from datetime import datetime, timezone

def main():
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(period="max", interval="1d")

    if df.empty:
        print("ERROR: No data returned", file=sys.stderr)
        sys.exit(1)

    print(f"Fetched {len(df)} daily rows, range {df.index[0].date()} to {df.index[-1].date()}", file=sys.stderr)

    # Group by year: { year: { dates: [...], closes: [...] } }
    years = {}
    for idx, row in df.iterrows():
        yr = str(idx.year)
        if int(yr) < 2014:
            continue
        date_str = idx.strftime("%Y-%m-%d")
        close = round(row["Close"], 2)
        if yr not in years:
            years[yr] = {"dates": [], "closes": []}
        years[yr]["dates"].append(date_str)
        years[yr]["closes"].append(close)

    current_year = str(datetime.now(timezone.utc).year)

    # Output JS with dates and closes
    print("const STATIC_YEARS = {")
    for yr in sorted(years.keys()):
        if yr >= current_year:
            continue
        d = years[yr]
        print(f'  "{yr}": {{d:{json.dumps(d["dates"])},c:{json.dumps(d["closes"])}}},')
    print("};")

    last_complete = max(y for y in years.keys() if y < current_year)
    print(f"const BAKED_THROUGH = {last_complete};")

    # Month-tick mapping from most recent complete year
    # Bitcoin trades 365 days/year, so month boundaries differ from equities
    ref = years[last_complete]
    month_starts = {}
    for i, ds in enumerate(ref["dates"]):
        m = int(ds[5:7])
        if m not in month_starts:
            month_starts[m] = i + 1  # 1-based day index
    tick_vals = [month_starts.get(m, 0) for m in range(1, 13)]
    tick_labels = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    print(f"const MONTH_TICK_VALS = {json.dumps(tick_vals)};")
    print(f'const MONTH_TICK_LABELS = {json.dumps(tick_labels)};')

    print(f"\nBaked {len([y for y in years if y < current_year])} complete years (2014-{last_complete})", file=sys.stderr)

if __name__ == "__main__":
    main()
