"""
Assembles btc_seasonality.html by inserting baked data into the HTML template.

Usage: python build_seasonality_btc.py
"""

def main():
    with open("btc_baked.js", "r") as f:
        baked_js = f.read().strip()

    html = r'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bitcoin Yearly Seasonality &#8212; Acumen</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: #121212;
      color: #FFFFFF;
      font-family: 'JetBrains Mono', 'Cascadia Code', monospace;
      min-height: 100vh;
    }

    .back-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 14px;
      color: #CCCCCC;
      text-decoration: none;
      font-size: 12px;
      letter-spacing: 0.5px;
      position: fixed;
      top: 12px;
      left: 16px;
      z-index: 100;
      border: 1px solid #555555;
      border-radius: 6px;
      background: #3A3A3A;
      transition: color 0.2s, border-color 0.2s;
    }
    .back-link:hover { color: #F5C542; border-color: #F5C542; }

    .page {
      max-width: 1400px;
      margin: 0 auto;
      padding: 60px 24px 48px;
    }

    .header { margin-bottom: 20px; padding-top: 12px; }

    .header-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 6px;
    }

    .badge {
      display: inline-block;
      padding: 3px 10px;
      background: #3A3A3A;
      color: #F5C542;
      border: 1px solid #F5C542;
      border-radius: 4px;
      font-size: 10px;
      letter-spacing: 1.5px;
      font-weight: 700;
      vertical-align: middle;
      margin-left: 12px;
    }

    h1 { font-size: 22px; font-weight: 700; color: #FFFFFF; letter-spacing: 0.3px; }

    .subtitle {
      font-size: 11px;
      color: #C0C0C0;
      letter-spacing: 0.3px;
      margin-top: 6px;
      line-height: 1.6;
    }

    #status-bar { font-size: 11px; color: #C0C0C0; text-align: right; letter-spacing: 0.5px; }

    /* Controls */
    .controls-bar {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 16px;
      padding: 12px 16px;
      background: #1E1E1E;
      border: 1px solid #444;
      border-radius: 8px;
    }

    .controls-label {
      font-size: 10px;
      color: #888;
      letter-spacing: 1px;
      text-transform: uppercase;
      white-space: nowrap;
    }

    #year-search {
      background: #2D2D2D;
      border: 1px solid #555;
      border-radius: 6px;
      color: #FFFFFF;
      padding: 8px 14px;
      font-size: 12px;
      width: 280px;
      font-family: inherit;
    }
    #year-search:focus { border-color: #F5C542; outline: none; }
    #year-search::placeholder { color: #666; }

    .controls-sep {
      width: 1px;
      height: 28px;
      background: #444;
    }

    .avg-btn {
      padding: 7px 16px;
      border-radius: 20px;
      border: 1px solid #444;
      background: transparent;
      color: #AAAAAA;
      font-size: 11px;
      cursor: pointer;
      font-family: inherit;
      transition: all 0.2s;
      white-space: nowrap;
    }
    .avg-btn:hover { border-color: #888; color: #FFFFFF; }
    .avg-btn.active { border-color: #F5C542; background: rgba(245,197,66,0.10); color: #FFFFFF; }

    /* Cycle toggle */
    .cycle-toggle {
      display: inline-flex;
      border: 1px solid #555;
      border-radius: 20px;
      overflow: hidden;
    }
    .cycle-toggle-btn {
      padding: 7px 14px;
      border: none;
      background: transparent;
      color: #AAAAAA;
      font-size: 11px;
      cursor: pointer;
      font-family: inherit;
      transition: all 0.2s;
      white-space: nowrap;
    }
    .cycle-toggle-btn:first-child { border-right: 1px solid #555; }
    .cycle-toggle-btn.active {
      background: rgba(245,197,66,0.15);
      color: #FFFFFF;
    }
    .cycle-toggle-btn:hover { color: #FFFFFF; }

    /* Pattern callout */
    .pattern-callout {
      background: #1E1E1E;
      border: 1px solid #444;
      border-radius: 8px;
      padding: 16px 20px;
      margin-bottom: 16px;
      display: none;
    }
    .pattern-callout.visible { display: block; }
    .pattern-callout h3 {
      font-size: 11px;
      color: #F5C542;
      margin-bottom: 10px;
      letter-spacing: 1.5px;
      font-weight: 700;
    }
    .pattern-callout .meta {
      font-size: 10px;
      color: #777;
      margin-bottom: 12px;
    }
    .matches-row {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
    }
    .match-item {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      padding: 6px 12px;
      background: #242424;
      border: 1px solid #444;
      border-radius: 6px;
    }
    .match-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      flex-shrink: 0;
    }
    .match-year { color: #FFFFFF; font-weight: 700; }
    .match-corr { color: #F5C542; font-weight: 700; }
    .match-cycle { color: #777; font-size: 10px; }

    /* Chart */
    .chart-container {
      position: relative;
      background: #1E1E1E;
      border: 1px solid #444;
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 20px;
    }
    #chart { height: 620px; }

    .watermark {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      opacity: 0.06;
      pointer-events: none;
      z-index: 1;
    }

    /* Info cards */
    .meta-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }
    @media (max-width: 700px) {
      .meta-grid { grid-template-columns: 1fr; }
    }
    .meta-card {
      background: #1E1E1E;
      border: 1px solid #444;
      border-radius: 8px;
      padding: 16px 20px;
    }
    .meta-card h3 {
      font-size: 11px;
      color: #F5C542;
      letter-spacing: 1.5px;
      margin-bottom: 10px;
      font-weight: 700;
    }
    .meta-card p, .meta-card li {
      font-size: 11px;
      color: #AAAAAA;
      line-height: 1.7;
    }
    .meta-card ul {
      list-style: none;
      padding: 0;
    }
    .meta-card li::before {
      content: "\2022";
      color: #F5C542;
      margin-right: 8px;
    }

    /* Update button */
    .update-wrap {
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 100;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
    }
    #update-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 20px;
      background: #3A3A3A;
      color: #FFFFFF;
      border: 1px solid #555;
      border-radius: 8px;
      font-family: inherit;
      font-size: 12px;
      cursor: pointer;
      letter-spacing: 0.5px;
      transition: border-color 0.2s, background 0.2s;
    }
    #update-btn:hover { border-color: #F5C542; background: #444; }
    #update-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .spinner {
      display: none;
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255,255,255,0.3);
      border-top-color: white;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    #update-btn.loading .spinner { display: inline-block; }
    #update-btn.loading .btn-text { display: none; }
    #update-btn.loading .loading-text { display: inline; }
    .loading-text { display: none; }
    @keyframes spin { to { transform: rotate(360deg); } }
    #update-status {
      font-size: 11px;
      padding: 6px 12px;
      border-radius: 6px;
      display: none;
      max-width: 280px;
      text-align: right;
    }
    #update-status.visible { display: block; }
    #update-status.info { background: #1E1E1E; color: #C0C0C0; border: 1px solid #444; }
    #update-status.success { background: #1a2e1a; color: #81C784; border: 1px solid #2e5a2e; }
    #update-status.error { background: #2e1a1a; color: #EF5350; border: 1px solid #5a2e2e; }

    /* Footer */
    .footer-note {
      font-size: 10px;
      color: #555;
      letter-spacing: 0.5px;
      text-align: center;
      padding: 16px 0;
    }
  </style>
</head>
<body>
  <a href="../../index.html" class="back-link">&#8592; Dashboard</a>

  <div class="page">
    <div class="header">
      <div class="header-top">
        <div>
          <h1>Bitcoin Yearly Seasonality<span class="badge">BTC</span></h1>
          <p class="subtitle">Year-over-year overlay of Bitcoin daily returns (2014 &#8211; present). Each line is one calendar year, aligned by day of year. Supports both election cycle and halving cycle analysis.</p>
        </div>
        <div id="status-bar"></div>
      </div>
    </div>

    <!-- Controls -->
    <div class="controls-bar">
      <span class="controls-label">Years</span>
      <input type="text" id="year-search" placeholder="Filter: 2020, 2017, 2018-2022 &#8230;">
      <button class="avg-btn" id="show-all-btn" onclick="toggleShowAllYears()">Show All Years</button>
      <div class="controls-sep"></div>
      <span class="controls-label">Averages</span>
      <button class="avg-btn active" data-avg="all" onclick="toggleAvg('all', this)">All Time Avg</button>
      <div class="controls-sep"></div>
      <span class="controls-label">Cycle</span>
      <div class="cycle-toggle">
        <button class="cycle-toggle-btn" id="cycle-election" onclick="setCycleMode('election')">Election</button>
        <button class="cycle-toggle-btn active" id="cycle-halving" onclick="setCycleMode('halving')">Halving</button>
      </div>
      <button class="avg-btn" data-avg="yr1" id="cyc-btn-1" onclick="toggleAvg('yr1', this)">1 Halving</button>
      <button class="avg-btn" data-avg="yr2" id="cyc-btn-2" onclick="toggleAvg('yr2', this)">2 Post-Halving</button>
      <button class="avg-btn" data-avg="yr3" id="cyc-btn-3" onclick="toggleAvg('yr3', this)">3 Mid-Cycle</button>
      <button class="avg-btn" data-avg="yr4" id="cyc-btn-4" onclick="toggleAvg('yr4', this)">4 Pre-Halving</button>
    </div>

    <!-- Pattern Recognition -->
    <div class="pattern-callout" id="pattern-callout">
      <h3>PATTERN RECOGNITION</h3>
      <div class="meta" id="pattern-meta"></div>
      <div class="matches-row" id="pattern-matches"></div>
      <button class="avg-btn" id="show-matches-btn" style="margin-top:12px;" onclick="toggleMatchesOnChart()">Show on Chart</button>
    </div>

    <!-- Chart -->
    <div class="chart-container">
      <div id="chart"></div>
      <div class="watermark">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 220 200" width="220" height="200">
          <polygon points="50,0 150,0 200,87 150,174 50,174 0,87"
            fill="none" stroke="white" stroke-width="10" stroke-linejoin="round"/>
          <text x="100" y="128" text-anchor="middle"
            font-size="84" font-family="'Segoe UI', system-ui, sans-serif"
            font-weight="500" fill="white">A</text>
        </svg>
      </div>
    </div>

    <!-- Info cards -->
    <div class="meta-grid">
      <div class="meta-card">
        <h3>HOW TO READ</h3>
        <ul>
          <li>Each line represents one calendar year&#8217;s Bitcoin price path</li>
          <li>X-axis is the day of year (1&#8211;365, Bitcoin trades every day)</li>
          <li>Y-axis is the percent change from January 1st</li>
          <li>The current year is shown as a bold white line</li>
          <li>Dashed lines are the 5 most similar historical years</li>
          <li>Averages are era-weighted: Pre-institutional &#8217;14&#8211;&#8217;16 (50%), Institutional &#8217;17+ (100%)</li>
          <li>Use the search box to isolate specific years or ranges</li>
          <li>Toggle between Election cycle and Halving cycle modes</li>
        </ul>
      </div>
      <div class="meta-card">
        <h3>CYCLE KEY</h3>
        <div id="cycle-key-content">
          <div id="halving-key">
            <p style="font-size:10px;color:#888;margin-bottom:8px;letter-spacing:1px;">HALVING CYCLE (default)</p>
            <ul>
              <li><span style="color:#FF7043">&#9679;</span> 1 Halving Year (e.g. 2024, 2020, 2016)</li>
              <li><span style="color:#66BB6A">&#9679;</span> 2 Post-Halving (e.g. 2025, 2021, 2017)</li>
              <li><span style="color:#42A5F5">&#9679;</span> 3 Mid-Cycle (e.g. 2026, 2022, 2018)</li>
              <li><span style="color:#AB47BC">&#9679;</span> 4 Pre-Halving (e.g. 2027, 2023, 2019)</li>
            </ul>
            <p style="margin-top:8px;font-size:10px;color:#666;">Halvings: Nov 2012, Jul 2016, May 2020, Apr 2024. Supply cut drives 4-year cycle.</p>
          </div>
          <div id="election-key" style="margin-top:14px;">
            <p style="font-size:10px;color:#888;margin-bottom:8px;letter-spacing:1px;">ELECTION CYCLE</p>
            <ul>
              <li><span style="color:#4FC3F7">&#9679;</span> 1 Post-Election (e.g. 2025, 2021, 2017)</li>
              <li><span style="color:#81C784">&#9679;</span> 2 Midterm (e.g. 2026, 2022, 2018)</li>
              <li><span style="color:#CE93D8">&#9679;</span> 3 Pre-Election (e.g. 2027, 2023, 2019)</li>
              <li><span style="color:#FF8A65">&#9679;</span> 4 Election (e.g. 2028, 2024, 2020)</li>
            </ul>
            <p style="margin-top:8px;font-size:10px;color:#666;">Based on U.S. presidential cycle. Liquidity and risk appetite vary by cycle phase.</p>
          </div>
        </div>
      </div>
    </div>

    <div class="footer-note">
      Acumen Research &#8212; Data: Yahoo Finance (BTC-USD) &#8212; Updated on demand
    </div>
  </div>

  <!-- Update button -->
  <div class="update-wrap">
    <div id="update-status"></div>
    <button id="update-btn" onclick="updateData()">
      <span class="spinner"></span>
      <span class="btn-text">Update Data</span>
      <span class="loading-text">Updating&#8230;</span>
    </button>
  </div>

  <script>
    // ================================================================
    // BAKED STATIC DATA
    // ================================================================
    // @@BAKED_DATA_START@@
    ''' + baked_js + r'''
    // @@BAKED_DATA_END@@

    // ================================================================
    // STATE
    // ================================================================
    const CURRENT_YEAR = new Date().getFullYear();
    let yearPct = {};           // year -> [pctChange from day 0]
    let yearDates = {};         // year -> [date strings]
    let visibleYears = new Set();
    let searchedYears = new Set();  // years explicitly typed in search (render brighter)
    let avgToggles = { all: true, yr1: false, yr2: false, yr3: false, yr4: false };
    let topMatches = [];
    let showMatches = false;
    let showAllYears = false;
    let cycleMode = 'halving'; // 'halving' or 'election'

    const MATCH_COLORS = ['#EF5350', '#42A5F5', '#66BB6A', '#FFA726', '#AB47BC'];

    // Election cycle colors & names
    const ELEC_COLORS = ['#4FC3F7', '#81C784', '#CE93D8', '#FF8A65'];
    const ELEC_NAMES  = ['1 Post-Election Avg', '2 Midterm Avg', '3 Pre-Election Avg', '4 Election Avg'];
    const ELEC_BTN_LABELS = ['1 Post-Election', '2 Midterm', '3 Pre-Election', '4 Election'];

    // Halving cycle colors & names
    const HALV_COLORS = ['#FF7043', '#66BB6A', '#42A5F5', '#AB47BC'];
    const HALV_NAMES  = ['1 Halving Avg', '2 Post-Halving Avg', '3 Mid-Cycle Avg', '4 Pre-Halving Avg'];
    const HALV_BTN_LABELS = ['1 Halving', '2 Post-Halving', '3 Mid-Cycle', '4 Pre-Halving'];

    // ================================================================
    // HELPERS
    // ================================================================
    function toPctChange(closes) {
      const base = closes[0];
      return closes.map(c => ((c - base) / base) * 100);
    }

    // Election cycle: (year - 2025) % 4 -> 0=Post-Election, 1=Midterm, 2=Pre-Election, 3=Election
    function electionCycle(year) {
      return (((year - 2025) % 4) + 4) % 4;
    }

    function electionLabel(year) {
      return ['Post-Election', 'Midterm', 'Pre-Election', 'Election'][electionCycle(year)];
    }

    // Halving cycle: (year - 2024) % 4 -> 0=Halving, 1=Post-Halving, 2=Mid-Cycle, 3=Pre-Halving
    function halvingCycle(year) {
      return (((year - 2024) % 4) + 4) % 4;
    }

    function halvingLabel(year) {
      return ['Halving', 'Post-Halving', 'Mid-Cycle', 'Pre-Halving'][halvingCycle(year)];
    }

    // Active cycle based on current mode
    function activeCycle(year) {
      return cycleMode === 'halving' ? halvingCycle(year) : electionCycle(year);
    }

    function activeLabel(year) {
      return cycleMode === 'halving' ? halvingLabel(year) : electionLabel(year);
    }

    function yearColor(year) {
      const idx = year - 2014;
      const hue = (idx * 137.508) % 360;
      return `hsl(${hue}, 55%, 55%)`;
    }

    function fmtDate(ds) {
      if (!ds) return '';
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      const m = parseInt(ds.slice(5,7)) - 1;
      const d = parseInt(ds.slice(8,10));
      return months[m] + ' ' + d;
    }

    // Era-based weighting for Bitcoin
    // Pre-institutional (2014-2016): 50% — thin liquidity, no CME futures, retail-only
    // Institutional era (2017+): 100% — CME futures, growing institutional adoption
    function eraWeight(year) {
      const y = parseInt(year);
      if (y <= 2016) return 0.50;
      return 1.00;
    }

    function computeAverage(yearKeys) {
      const maxLen = Math.max(...yearKeys.map(y => (yearPct[y] || []).length));
      const avg = [];
      for (let d = 0; d < maxLen; d++) {
        let wSum = 0, wTotal = 0;
        for (const y of yearKeys) {
          const arr = yearPct[y];
          if (arr && d < arr.length) {
            const w = eraWeight(y);
            wSum += arr[d] * w;
            wTotal += w;
          }
        }
        avg.push(wTotal > 0 ? wSum / wTotal : null);
      }
      return avg;
    }

    function pearson(x, y) {
      const n = Math.min(x.length, y.length);
      if (n < 10) return 0;
      let mx = 0, my = 0;
      for (let i = 0; i < n; i++) { mx += x[i]; my += y[i]; }
      mx /= n; my /= n;
      let num = 0, dx = 0, dy = 0;
      for (let i = 0; i < n; i++) {
        const xi = x[i] - mx, yi = y[i] - my;
        num += xi * yi;
        dx += xi * xi;
        dy += yi * yi;
      }
      dx = Math.sqrt(dx);
      dy = Math.sqrt(dy);
      return (dx === 0 || dy === 0) ? 0 : num / (dx * dy);
    }

    function toDailyReturns(pct) {
      const dr = [0];
      for (let i = 1; i < pct.length; i++) {
        dr.push(pct[i] - pct[i - 1]);
      }
      return dr;
    }

    function euclideanSimilarity(x, y) {
      const n = Math.min(x.length, y.length);
      if (n < 2) return 0;
      let sumSq = 0;
      for (let i = 0; i < n; i++) {
        const diff = x[i] - y[i];
        sumSq += diff * diff;
      }
      const rmse = Math.sqrt(sumSq / n);
      // Bitcoin has much larger moves than equities — scale divisor up
      return 1 / (1 + rmse / 20);
    }

    // ================================================================
    // PATTERN RECOGNITION — COMPOSITE SCORING
    // ================================================================
    function runPatternRecognition() {
      const curPct = yearPct[String(CURRENT_YEAR)];
      if (!curPct || curPct.length < 10) {
        topMatches = [];
        return;
      }
      const curLen = curPct.length;
      const curDaily = toDailyReturns(curPct);
      const candidates = [];

      for (const [yr, pct] of Object.entries(yearPct)) {
        if (parseInt(yr) === CURRENT_YEAR) continue;
        if (pct.length < curLen) continue;

        const histSlice = pct.slice(0, curLen);
        const histDaily = toDailyReturns(histSlice);

        const rDaily = pearson(curDaily, histDaily);
        const eSim = euclideanSimilarity(curPct, histSlice);
        const rCum = pearson(curPct, histSlice);

        const rDailyNorm = (rDaily + 1) / 2;
        const rCumNorm = (rCum + 1) / 2;
        const composite = 0.40 * rDailyNorm + 0.35 * eSim + 0.25 * rCumNorm;

        candidates.push({ year: yr, composite, rDaily, eSim, rCum, fullPath: pct });
      }

      candidates.sort((a, b) => b.composite - a.composite);
      topMatches = candidates.slice(0, 5);
    }

    function updatePatternCallout() {
      const el = document.getElementById('pattern-callout');
      const metaEl = document.getElementById('pattern-meta');
      const matchEl = document.getElementById('pattern-matches');

      if (topMatches.length === 0) {
        el.classList.remove('visible');
        return;
      }
      el.classList.add('visible');

      const days = (yearPct[String(CURRENT_YEAR)] || []).length;
      metaEl.textContent = `${CURRENT_YEAR} most closely resembles these years (based on ${days} days). Composite score blends daily-return correlation (40%), path proximity (35%), and cumulative-return correlation (25%).`;

      let html = '';
      for (let i = 0; i < topMatches.length; i++) {
        const m = topMatches[i];
        const cycle = activeLabel(parseInt(m.year));
        const pct = Math.round(m.composite * 100);
        html += `<div class="match-item">
          <span class="match-dot" style="background:${MATCH_COLORS[i]}"></span>
          <span class="match-year">${m.year}</span>
          <span class="match-corr">${pct}%</span>
          <span style="color:#888;font-size:10px;" title="Daily r=${m.rDaily.toFixed(2)} | Path=${(m.eSim*100).toFixed(0)}% | Trend r=${m.rCum.toFixed(2)}">D:${m.rDaily.toFixed(2)} P:${(m.eSim*100).toFixed(0)}% T:${m.rCum.toFixed(2)}</span>
          <span class="match-cycle">${cycle}</span>
        </div>`;
      }
      matchEl.innerHTML = html;
    }

    // ================================================================
    // CYCLE MODE TOGGLE
    // ================================================================
    function setCycleMode(mode) {
      cycleMode = mode;

      // Update toggle buttons
      document.getElementById('cycle-election').classList.toggle('active', mode === 'election');
      document.getElementById('cycle-halving').classList.toggle('active', mode === 'halving');

      // Update cycle button labels
      const labels = mode === 'halving' ? HALV_BTN_LABELS : ELEC_BTN_LABELS;
      for (let i = 0; i < 4; i++) {
        document.getElementById(`cyc-btn-${i + 1}`).textContent = labels[i];
      }

      // Rebuild chart with new cycle classification
      rebuildChart();
    }

    // ================================================================
    // YEAR SEARCH
    // ================================================================
    let searchTimeout = null;
    function applyYearSearch() {
      const raw = document.getElementById('year-search').value.trim();
      searchedYears = new Set();
      if (!raw) {
        visibleYears = new Set();
        if (yearPct[String(CURRENT_YEAR)]) visibleYears.add(String(CURRENT_YEAR));
      } else {
        visibleYears = new Set();
        const tokens = raw.split(/[,\s]+/).filter(Boolean);
        for (const tok of tokens) {
          const rangeMatch = tok.match(/^(\d{4})-(\d{4})$/);
          if (rangeMatch) {
            const start = parseInt(rangeMatch[1]), end = parseInt(rangeMatch[2]);
            for (let y = start; y <= end; y++) {
              if (yearPct[String(y)]) { visibleYears.add(String(y)); searchedYears.add(String(y)); }
            }
          } else if (/^\d{4}$/.test(tok) && yearPct[tok]) {
            visibleYears.add(tok); searchedYears.add(tok);
          }
        }
        if (yearPct[String(CURRENT_YEAR)]) visibleYears.add(String(CURRENT_YEAR));
      }
      rebuildChart();
    }
    document.getElementById('year-search').addEventListener('input', function() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(applyYearSearch, 300);
    });
    document.getElementById('year-search').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { clearTimeout(searchTimeout); applyYearSearch(); }
    });

    // ================================================================
    // AVERAGE TOGGLES
    // ================================================================
    function toggleAvg(key, btn) {
      avgToggles[key] = !avgToggles[key];
      btn.classList.toggle('active', avgToggles[key]);
      rebuildChart();
    }

    function toggleShowAllYears() {
      showAllYears = !showAllYears;
      const btn = document.getElementById('show-all-btn');
      btn.classList.toggle('active', showAllYears);
      btn.textContent = showAllYears ? 'Hide All Years' : 'Show All Years';
      searchedYears = new Set();
      if (showAllYears) {
        visibleYears = new Set(Object.keys(yearPct));
        document.getElementById('year-search').value = '';
      } else {
        visibleYears = new Set();
        if (yearPct[String(CURRENT_YEAR)]) visibleYears.add(String(CURRENT_YEAR));
      }
      rebuildChart();
    }

    function toggleMatchesOnChart() {
      showMatches = !showMatches;
      const btn = document.getElementById('show-matches-btn');
      btn.classList.toggle('active', showMatches);
      btn.textContent = showMatches ? 'Hide from Chart' : 'Show on Chart';
      rebuildChart();
    }

    // ================================================================
    // CHART BUILD
    // ================================================================
    const layout = {
      paper_bgcolor: '#1E1E1E',
      plot_bgcolor: '#1E1E1E',
      font: { family: 'JetBrains Mono, monospace', color: '#C0C0C0', size: 10 },
      margin: { t: 36, r: 60, b: 56, l: 72 },
      xaxis: {
        title: { text: 'Day of Year', font: { size: 10, color: '#888' } },
        gridcolor: '#333',
        linecolor: '#555',
        tickcolor: '#555',
        tickfont: { size: 10, color: '#888' },
        tickvals: MONTH_TICK_VALS,
        ticktext: MONTH_TICK_LABELS,
        zeroline: false,
      },
      yaxis: {
        title: { text: 'Year-to-Date Return (%)', font: { size: 10, color: '#888' } },
        gridcolor: '#333',
        linecolor: '#555',
        tickcolor: '#555',
        tickfont: { size: 10, color: '#888' },
        ticksuffix: '%',
        zeroline: true,
        zerolinecolor: '#666',
        zerolinewidth: 1,
      },
      showlegend: true,
      legend: {
        x: 0.01, y: 0.99, xanchor: 'left', yanchor: 'top',
        bgcolor: 'rgba(30,30,30,0.92)',
        bordercolor: '#555', borderwidth: 1,
        font: { size: 10, color: '#C0C0C0' },
      },
      hovermode: 'closest',
      modebar: { bgcolor: '#1E1E1E', color: '#777', activecolor: '#F5C542' },
    };

    const plotConfig = {
      responsive: true,
      displayModeBar: true,
      modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
      displaylogo: false,
      toImageButtonOptions: {
        format: 'png', filename: 'btc_seasonality',
        width: 1400, height: 700, scale: 2,
      },
    };

    function buildHoverDates(year, length) {
      const dates = yearDates[String(year)];
      const refDates = yearDates[String(BAKED_THROUGH)];
      const result = [];
      for (let i = 0; i < length; i++) {
        if (dates && dates[i]) {
          result.push(fmtDate(dates[i]));
        } else if (refDates && refDates[i]) {
          result.push(fmtDate(refDates[i]));
        } else {
          result.push(`Day ${i + 1}`);
        }
      }
      return result;
    }

    function rebuildChart() {
      const traces = [];
      const sortedYears = [...visibleYears].sort();
      const matchYearSet = new Set(showMatches ? topMatches.map(m => m.year) : []);

      // Active cycle colors and names
      const cycColors = cycleMode === 'halving' ? HALV_COLORS : ELEC_COLORS;
      const cycNames = cycleMode === 'halving' ? HALV_NAMES : ELEC_NAMES;
      const cycleFn = cycleMode === 'halving' ? halvingCycle : electionCycle;

      // A. Background year lines
      for (const yr of sortedYears) {
        const pct = yearPct[yr];
        if (!pct) continue;
        if (parseInt(yr) === CURRENT_YEAR) continue;
        if (matchYearSet.has(yr)) continue;

        const hoverDates = buildHoverDates(parseInt(yr), pct.length);
        const isSearched = searchedYears.has(yr);
        traces.push({
          type: 'scattergl', mode: 'lines',
          x: pct.map((_, i) => i + 1),
          y: pct,
          customdata: hoverDates,
          name: yr,
          line: { color: yearColor(parseInt(yr)), width: isSearched ? 2 : 1 },
          opacity: isSearched ? 0.55 : 0.25,
          hovertemplate: '<b>%{customdata}</b> | <b>' + yr + '</b><br>Day %{x} | %{y:.1f}%<extra></extra>',
          showlegend: isSearched,
        });
      }

      // B. Top match analog years (dashed)
      if (showMatches) {
        for (let i = 0; i < topMatches.length; i++) {
          const m = topMatches[i];
          const pct = yearPct[m.year];
          if (!pct) continue;
          const hoverDates = buildHoverDates(parseInt(m.year), pct.length);
          traces.push({
            type: 'scattergl', mode: 'lines',
            x: pct.map((_, j) => j + 1),
            y: pct,
            customdata: hoverDates,
            name: `${m.year} (${Math.round(m.composite*100)}%)`,
            line: { color: MATCH_COLORS[i], width: 2, dash: 'dash' },
            opacity: 0.85,
            hovertemplate: '<b>%{customdata}</b> | <b>' + m.year + '</b><br>Day %{x} | %{y:.1f}%<extra></extra>',
          });
        }
      }

      // C. Current year (bold white)
      const curPct = yearPct[String(CURRENT_YEAR)];
      if (curPct) {
        const hoverDates = buildHoverDates(CURRENT_YEAR, curPct.length);
        traces.push({
          type: 'scattergl', mode: 'lines',
          x: curPct.map((_, i) => i + 1),
          y: curPct,
          customdata: hoverDates,
          name: String(CURRENT_YEAR),
          line: { color: '#FFFFFF', width: 3.5 },
          hovertemplate: '<b>%{customdata}</b> | <b>' + CURRENT_YEAR + '</b><br>Day %{x} | %{y:.1f}%<extra></extra>',
        });
      }

      // D. Average overlays
      const allKeys = Object.keys(yearPct).filter(y => parseInt(y) !== CURRENT_YEAR);
      const refDates = yearDates[String(BAKED_THROUGH)] || [];

      if (avgToggles.all) {
        const avg = computeAverage(allKeys);
        const hoverDates = avg.map((_, i) => refDates[i] ? fmtDate(refDates[i]) : `Day ${i+1}`);
        traces.push({
          type: 'scattergl', mode: 'lines',
          x: avg.map((_, i) => i + 1), y: avg,
          customdata: hoverDates,
          name: 'All Time Avg',
          line: { color: '#F5C542', width: 3 },
          hovertemplate: '<b>%{customdata}</b> | <b>All Time Avg</b><br>Day %{x} | %{y:.1f}%<extra></extra>',
        });
      }

      // Cycle averages (uses active cycle mode)
      const cycBuckets = [[], [], [], []];
      for (const y of allKeys) {
        cycBuckets[cycleFn(parseInt(y))].push(y);
      }
      const CYC_TOGGLE_KEYS = ['yr1', 'yr2', 'yr3', 'yr4'];
      for (let i = 0; i < 4; i++) {
        if (avgToggles[CYC_TOGGLE_KEYS[i]]) {
          const avg = computeAverage(cycBuckets[i]);
          const hoverDates = avg.map((_, j) => refDates[j] ? fmtDate(refDates[j]) : `Day ${j+1}`);
          traces.push({
            type: 'scattergl', mode: 'lines',
            x: avg.map((_, j) => j + 1), y: avg,
            customdata: hoverDates,
            name: cycNames[i],
            line: { color: cycColors[i], width: 2.5 },
            hovertemplate: '<b>%{customdata}</b> | <b>' + cycNames[i] + '</b><br>Day %{x} | %{y:.1f}%<extra></extra>',
          });
        }
      }

      // Compute dynamic axis ranges — only scale to prominent traces
      // (current year, averages, match lines). Background year lines at
      // low opacity are excluded so outliers like 2017 (+1300%) don't
      // blow out the y-axis and flatten everything else.
      let maxDay = 0, minY = Infinity, maxY = -Infinity;
      for (const t of traces) {
        if (!t.x || !t.y) continue;
        const isBackground = t.showlegend === false;
        for (let i = 0; i < t.x.length; i++) {
          if (t.x[i] > maxDay) maxDay = t.x[i];
          if (!isBackground && t.y[i] != null && t.y[i] < minY) minY = t.y[i];
          if (!isBackground && t.y[i] != null && t.y[i] > maxY) maxY = t.y[i];
        }
      }
      // Fallback if only background lines are visible (no prominent traces)
      if (minY === Infinity || maxY === -Infinity) {
        for (const t of traces) {
          if (!t.x || !t.y) continue;
          for (let i = 0; i < t.x.length; i++) {
            if (t.y[i] != null && t.y[i] < minY) minY = t.y[i];
            if (t.y[i] != null && t.y[i] > maxY) maxY = t.y[i];
          }
        }
      }
      const xPad = Math.max(5, Math.round(maxDay * 0.05));
      const yRange = maxY - minY || 1;
      const yPad = yRange * 0.1;

      const xMax = Math.min(maxDay + xPad, 367);
      const filteredTickVals = MONTH_TICK_VALS.filter(v => v <= xMax);
      const filteredTickLabels = filteredTickVals.map(v => MONTH_TICK_LABELS[MONTH_TICK_VALS.indexOf(v)]);

      const dynamicLayout = JSON.parse(JSON.stringify(layout));
      dynamicLayout.xaxis.range = [0, xMax];
      dynamicLayout.xaxis.tickvals = filteredTickVals;
      dynamicLayout.xaxis.ticktext = filteredTickLabels;
      dynamicLayout.yaxis.range = [minY - yPad, maxY + yPad];
      dynamicLayout.yaxis.autorange = false;

      Plotly.react('chart', traces, dynamicLayout, plotConfig);
      updatePatternCallout();
    }

    // ================================================================
    // YAHOO FINANCE FETCH (BTC-USD)
    // ================================================================
    async function fetchYahooBTC(period1, period2) {
      const baseUrl = `https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?period1=${period1}&period2=${period2}&interval=1d`;
      const proxies = [
        `https://corsproxy.io/?${encodeURIComponent(baseUrl)}`,
        `https://api.allorigins.win/raw?url=${encodeURIComponent(baseUrl)}`,
      ];
      for (const proxyUrl of proxies) {
        try {
          const resp = await fetch(proxyUrl);
          if (!resp.ok) continue;
          const json = await resp.json();
          return json.chart.result[0];
        } catch (e) { continue; }
      }
      return null;
    }

    function parseYahooByYear(result) {
      const timestamps = result.timestamp;
      const closes = result.indicators.quote[0].close;
      const byYear = {};
      for (let i = 0; i < timestamps.length; i++) {
        if (closes[i] == null) continue;
        const d = new Date(timestamps[i] * 1000);
        const yr = String(d.getFullYear());
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        if (!byYear[yr]) byYear[yr] = { dates: [], closes: [] };
        byYear[yr].dates.push(`${yr}-${mm}-${dd}`);
        byYear[yr].closes.push(closes[i]);
      }
      return byYear;
    }

    // ================================================================
    // AUTO-EXTENSION: fetch missing years between baked data and now
    // ================================================================
    async function fetchMissingYears() {
      const missingYears = [];
      for (let y = BAKED_THROUGH + 1; y <= CURRENT_YEAR; y++) {
        if (!yearPct[String(y)]) missingYears.push(y);
      }
      if (missingYears.length === 0) return 0;

      const startDate = new Date(missingYears[0], 0, 1);
      const period1 = Math.floor(startDate.getTime() / 1000);
      const period2 = Math.floor(Date.now() / 1000);

      // Try up to 3 attempts with 2s delay between retries
      let result = null;
      for (let attempt = 0; attempt < 3; attempt++) {
        result = await fetchYahooBTC(period1, period2);
        if (result) break;
        if (attempt < 2) await new Promise(r => setTimeout(r, 2000));
      }
      if (!result) return 0;

      const byYear = parseYahooByYear(result);
      let filled = 0;
      for (const [yr, data] of Object.entries(byYear)) {
        if (data.closes.length > 0) {
          yearDates[yr] = data.dates;
          yearPct[yr] = toPctChange(data.closes);
          filled++;
        }
      }
      if (yearPct[String(CURRENT_YEAR)]) {
        visibleYears.add(String(CURRENT_YEAR));
      }
      return filled;
    }

    // ================================================================
    // UPDATE BUTTON
    // ================================================================
    function setStatus(msg, type) {
      const el = document.getElementById('update-status');
      el.textContent = msg;
      el.className = 'visible ' + type;
      if (type === 'success' || type === 'info') {
        setTimeout(() => { el.className = ''; }, 5000);
      }
    }

    function setLoading(on) {
      const btn = document.getElementById('update-btn');
      if (on) btn.classList.add('loading'); else btn.classList.remove('loading');
      btn.disabled = on;
    }

    async function updateData() {
      setLoading(true);
      setStatus('Fetching live data\u2026', 'info');
      try {
        const filled = await fetchMissingYears();
        if (filled > 0) {
          runPatternRecognition();
          rebuildChart();
          const days = (yearPct[String(CURRENT_YEAR)] || []).length;
          setStatus(`Updated: ${filled} year(s) fetched, ${CURRENT_YEAR} has ${days} days`, 'success');
        } else {
          setStatus('No new data available', 'info');
        }
      } catch (e) {
        console.warn('Update failed:', e);
        setStatus('Update failed \u2014 using baked data', 'error');
      }
      setLoading(false);
    }

    // ================================================================
    // INIT
    // ================================================================
    (async function init() {
      // Load static data
      for (const [yr, data] of Object.entries(STATIC_YEARS)) {
        yearPct[yr] = toPctChange(data.c);
        yearDates[yr] = data.d;
      }

      // Default: no background years
      visibleYears = new Set();

      // Auto-enable current halving cycle average
      const curCycle = halvingCycle(CURRENT_YEAR);
      const cycleKey = ['yr1', 'yr2', 'yr3', 'yr4'][curCycle];
      avgToggles[cycleKey] = true;
      document.getElementById(`cyc-btn-${curCycle + 1}`).classList.add('active');

      // Render chart with baked data immediately
      rebuildChart();

      // Auto-extend: fetch missing years + current year
      document.getElementById('status-bar').textContent = 'Fetching live data\u2026';
      try {
        const filled = await fetchMissingYears();
        if (filled > 0) {
          runPatternRecognition();
          rebuildChart();
          const days = (yearPct[String(CURRENT_YEAR)] || []).length;
          document.getElementById('status-bar').textContent = `${CURRENT_YEAR}: ${days} days (live)`;
        } else {
          document.getElementById('status-bar').textContent = 'Live fetch unavailable \u2014 baked data only';
        }
      } catch (e) {
        console.warn('Auto-extension failed:', e);
        document.getElementById('status-bar').textContent = 'Live fetch failed \u2014 baked data only';
      }
    })();
  </script>
</body>
</html>'''

    import os
    os.makedirs("indicators/btc", exist_ok=True)

    with open("indicators/btc/btc_seasonality.html", "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize("indicators/btc/btc_seasonality.html")
    print(f"Built indicators/btc/btc_seasonality.html ({size:,} bytes / {size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
