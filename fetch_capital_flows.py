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

    for ticker in TICKERS:
        yf_sym    = YF_SYMBOL[ticker]
        new_rows  = fetch_ticker(ticker, yf_sym, fetch_from)

        existing_entry = existing_data.get(ticker, {"dates": [], "volumes": [], "opens": [], "closes": []})
        existing_dates = set(existing_entry.get("dates", []))

        added = 0
        for row in new_rows:
            if row["date"] in existing_dates:
                continue
            existing_entry["dates"].append(row["date"])
            existing_entry["volumes"].append(row["volume"])
            existing_entry["opens"].append(row["open"])
            existing_entry["closes"].append(row["close"])
            existing_dates.add(row["date"])
            added += 1
            if row["date"] > latest_date:
                latest_date = row["date"]

        # Keep sorted by date
        combined = sorted(
            zip(existing_entry["dates"], existing_entry["volumes"], existing_entry["opens"], existing_entry["closes"]),
            key=lambda x: x[0]
        )
        if combined:
            existing_entry["dates"]   = [r[0] for r in combined]
            existing_entry["volumes"] = [r[1] for r in combined]
            existing_entry["opens"]   = [r[2] for r in combined]
            existing_entry["closes"]  = [r[3] for r in combined]

        existing_data[ticker] = existing_entry
        total_new += added
        if added:
            print(f"  {ticker:6s}: +{added} new week(s)  (total {len(existing_entry['dates'])} weeks)")
        else:
            print(f"  {ticker:6s}: already current")

    if not latest_date and existing.get("baked_through"):
        latest_date = existing["baked_through"]

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
        raise SystemExit(1)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"\nBaked {total_new} new data point(s) into {HTML_PATH}")
    print(f"Data through: {latest_date}  |  Baked on: {today}")
    print("Done.")


if __name__ == "__main__":
    main()
