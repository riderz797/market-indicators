"""
fetch_capital_flows.py
Incrementally updates the Capital Flows indicator.

Reads existing baked data from capital_flows.html, finds the last baked week,
fetches only new weekly OHLCV for all 22 tickers via yfinance, merges, and
re-injects. Run weekly after markets close.

Run:  python fetch_capital_flows.py
Requires: yfinance, pandas  (pip install yfinance pandas)
"""

import json
import os
import re
from datetime import datetime, timedelta

import yfinance as yf

# ── CONFIG ─────────────────────────────────────────────────────────────────────
HTML_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "indicators", "equities", "capital_flows.html"
)

TICKERS = [
    "BTC", "MSTR", "STRC", "ASST", "SATA",
    "DBC", "XLE", "GLD", "DBA",
    "XLP", "VYM", "XLV", "MOAT",
    "QQQ", "XLY", "XLF", "IWM", "IGV", "SPY",
    "SHV", "TLT", "IEF",
]

# yfinance symbol overrides
YF_SYMBOL = {t: t for t in TICKERS}
YF_SYMBOL["BTC"] = "BTC-USD"

HISTORY_YEARS = 2   # how far back to go on first run


# ── READ EXISTING BAKED DATA ───────────────────────────────────────────────────
def read_baked_data(html):
    """Extract CAPITAL_FLOWS JSON from the HTML baked block."""
    m = re.search(
        r"// @@BAKED_DATA_START@@\s*\nconst CAPITAL_FLOWS\s*=\s*([\s\S]*?);\s*\nconst CAPITAL_FLOWS_BAKED",
        html
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ── FETCH WEEKLY OHLCV FROM YFINANCE ──────────────────────────────────────────
def fetch_ticker(symbol, yf_symbol, start_date):
    """Returns list of {date, volume, open, close} dicts sorted by date."""
    try:
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(start=start_date, interval="1wk")
        if hist.empty:
            print(f"  WARNING: No data returned for {symbol} ({yf_symbol})")
            return []
        rows = []
        for ts, row in hist.iterrows():
            vol = row.get("Volume", 0)
            o   = row.get("Open",  None)
            c   = row.get("Close", None)
            if vol is None or o is None or c is None:
                continue
            rows.append({
                "date":   ts.strftime("%Y-%m-%d"),
                "volume": int(vol),
                "open":   round(float(o), 6),
                "close":  round(float(c), 6),
            })
        return rows
    except Exception as e:
        print(f"  WARNING: Failed to fetch {symbol} ({yf_symbol}): {e}")
        return []


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    existing = read_baked_data(html)

    if existing and existing.get("data"):
        baked_through = existing.get("baked_through", "")
        print(f"Existing baked data found. Last baked through: {baked_through}")
        # Overlap by 1 week to catch revisions
        last_dt    = datetime.strptime(baked_through, "%Y-%m-%d")
        fetch_from = (last_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        print("No existing baked data — fetching from scratch.")
        fetch_from = (datetime.now() - timedelta(days=365 * HISTORY_YEARS)).strftime("%Y-%m-%d")
        existing   = {"tickers": TICKERS, "data": {t: {"dates": [], "volumes": [], "opens": [], "closes": []} for t in TICKERS}}

    print(f"Fetching weekly data from {fetch_from} onward for {len(TICKERS)} tickers...\n")

    existing_data = existing.get("data", {})
    latest_date   = ""
    total_new     = 0

    # Only bake weeks that started at least 2 days ago.  On Monday morning the
    # current week's bar (labeled with today's date) has barely begun — crypto
    # shows one holiday day of volume, US equity tickers show nothing.  Excluding
    # it keeps all 22 tickers in sync and prevents a misleading partial bar.
    week_cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    for ticker in TICKERS:
        yf_sym    = YF_SYMBOL[ticker]
        new_rows  = fetch_ticker(ticker, yf_sym, fetch_from)
        new_rows  = [r for r in new_rows if r["date"] <= week_cutoff]

        existing_entry = existing_data.get(ticker, {"dates": [], "volumes": [], "opens": [], "closes": []})

        # Build a date-keyed map of existing bars, dropping any past the cutoff
        # (e.g. a partial Monday bar baked by an earlier holiday run).
        by_date = {}
        for dt, v, o, c in zip(
            existing_entry.get("dates", []),
            existing_entry.get("volumes", []),
            existing_entry.get("opens", []),
            existing_entry.get("closes", []),
        ):
            if dt <= week_cutoff:
                by_date[dt] = (v, o, c)

        before = set(by_date)

        # Overlay freshly fetched bars. Fresh values WIN on overlapping dates so
        # the 1-week revision overlap actually applies and any stale partial bar
        # from a mid-week run gets corrected on the next run.
        for row in new_rows:
            by_date[row["date"]] = (row["volume"], row["open"], row["close"])

        added = len(set(by_date) - before)

        # Rebuild sorted-by-date arrays.
        sorted_dates = sorted(by_date)
        existing_entry["dates"]   = sorted_dates
        existing_entry["volumes"] = [by_date[d][0] for d in sorted_dates]
        existing_entry["opens"]   = [by_date[d][1] for d in sorted_dates]
        existing_entry["closes"]  = [by_date[d][2] for d in sorted_dates]

        existing_data[ticker] = existing_entry
        total_new += added
        if sorted_dates and sorted_dates[-1] > latest_date:
            latest_date = sorted_dates[-1]
        if added:
            print(f"  {ticker:6s}: +{added} new week(s)  (total {len(sorted_dates)} weeks)")
        else:
            print(f"  {ticker:6s}: current ({len(sorted_dates)} weeks)")

    # Derive baked_through from actual data (covers the purge case where
    # no new rows were added but stale future bars were removed).
    all_dates = [
        d
        for entry in existing_data.values()
        for d in entry.get("dates", [])
    ]
    latest_date = max(all_dates) if all_dates else existing.get("baked_through", "")

    today = datetime.now().strftime("%Y-%m-%d")
    payload = {
        "tickers":       TICKERS,
        "data":          existing_data,
        "baked_through": latest_date,
        "baked_on":      today,
    }

    baked_block = (
        f"const CAPITAL_FLOWS = {json.dumps(payload, separators=(',', ':'))};\n"
        f"const CAPITAL_FLOWS_BAKED = true; // injected by fetch_capital_flows.py on {today}"
    )

    pattern = r"(// @@BAKED_DATA_START@@\n)([\s\S]*?)(\nconst CAPITAL_FLOWS_BAKED[\s\S]*?)(// @@BAKED_DATA_END@@)"
    replacement = r"\g<1>" + baked_block + r"\n// @@BAKED_DATA_END@@"
    new_html, n = re.subn(pattern, replacement, html)

    if n == 0:
        print("\nERROR: Could not find baked data markers in HTML.")
        raise RuntimeError("Could not find @@BAKED_DATA_START@@ / @@BAKED_DATA_END@@ markers in capital_flows.html")

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"\nBaked {total_new} new data point(s) into {HTML_PATH}")
    print(f"Data through: {latest_date}  |  Baked on: {today}")
    print("Done.")


if __name__ == "__main__":
    main()
