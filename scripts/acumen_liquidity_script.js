// ===== STATIC DATA (injected by rebuild_all.py — do not edit manually) =====
const ACUMEN_LIQUIDITY = __STATIC_DATA__;
// ===== END STATIC DATA =====

const GOLD   = '#F5C542';
const WHITE  = '#FFFFFF';
const GRAY   = '#AAAAAA';
const PANEL  = '#1E1E1E';
const GRID   = '#2A2A2A';
const GREEN  = '#4ade80';
const RED    = '#f87171';

const TIER_COLOR = {
  exceptional: '#4ade80',
  strong:      '#86efac',
  buy:         '#bbf7d0',
  flat:        '#888888',
  miss:        '#f87171',
  pending:     '#F5C542',
};
const TIER_LABEL = {
  exceptional: 'EXCEPTIONAL',
  strong:      'STRONG BUY',
  buy:         'BUY',
  flat:        'FLAT',
  miss:        'MISS',
  pending:     'PENDING',
};

function setStatus(msg, type = 'info') {
  const el = document.getElementById('status-bar');
  el.textContent = msg;
  el.className = type;
}

function renderSignals(meta) {
  const lqiZ = meta.latest_lqi_z;
  const projZ = meta.latest_proj_z;

  const lqiEl = document.getElementById('sig-lqi-z');
  lqiEl.textContent = (lqiZ >= 0 ? '+' : '') + lqiZ.toFixed(2) + ' \u03c3';
  lqiEl.className = 'signal-value ' + (lqiZ > 0.5 ? 'positive' : lqiZ < -0.5 ? 'negative' : 'neutral');
  document.getElementById('sig-lqi-sub').textContent =
    'Raw YoY: ' + (meta.latest_lqi_raw_pct >= 0 ? '+' : '') + meta.latest_lqi_raw_pct.toFixed(1) + '%';

  const projEl = document.getElementById('sig-proj-z');
  projEl.textContent = (projZ >= 0 ? '+' : '') + projZ.toFixed(2) + ' \u03c3';
  projEl.className = 'signal-value ' + (projZ > 0.5 ? 'positive' : projZ < -0.5 ? 'negative' : 'neutral');
  document.getElementById('sig-proj-sub').textContent = 'Signal extends to ' + meta.proj_end_date;

  document.getElementById('sig-corr-full').textContent = meta.corr_full.toFixed(2);
  document.getElementById('sig-corr-post').textContent = meta.corr_post20.toFixed(2);
}

function renderComponents(components) {
  const total = Object.values(components).reduce((a, b) => a + Math.abs(b), 0);
  const container = document.getElementById('comp-bars');
  container.innerHTML = '';
  for (const [name, val] of Object.entries(components)) {
    const pct = total > 0 ? Math.abs(val) / total * 100 : 0;
    const row = document.createElement('div');
    row.className = 'component-bar-row';
    row.innerHTML = `
      <span class="comp-label">${name}</span>
      <div class="bar-bg"><div class="bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
      <span class="comp-val">$${val.toLocaleString(undefined, {maximumFractionDigits:0})}B</span>
    `;
    container.appendChild(row);
  }
}

function renderChart(data) {
  const meta    = data.meta;
  const lqiZ    = data.lqi_z;
  const useqZ   = data.useq_z;
  const lqiProj = data.lqi_proj;
  const signals = data.buy_signals || [];

  const lastEqDate = meta.last_equity_date;

  // Split projection into historical overlap (solid) and future (dashed)
  const histDates = [], histVals = [];
  const futDates  = [], futVals  = [];
  lqiProj.dates.forEach((d, i) => {
    const v = lqiProj.values[i];
    if (v === null) return;
    if (d <= lastEqDate) { histDates.push(d); histVals.push(v); }
    else                 { futDates.push(d);  futVals.push(v);  }
  });

  const traceEquity = {
    x: useqZ.dates, y: useqZ.values,
    type: 'scatter', mode: 'lines',
    name: 'US Equities YoY% (z-score)',
    line: { color: WHITE, width: 1.8 },
    hovertemplate: '%{x}<br>Equities z: <b>%{y:.2f}\u03c3</b><extra></extra>',
  };
  const traceHist = {
    x: histDates, y: histVals,
    type: 'scatter', mode: 'lines',
    name: `Acumen Liquidity (z-score, +${meta.lead_days}d projected)`,
    line: { color: GOLD, width: 2.2 },
    hovertemplate: '%{x}<br>Liquidity z: <b>%{y:.2f}\u03c3</b><extra></extra>',
  };
  const traceFuture = {
    x: futDates, y: futVals,
    type: 'scatter', mode: 'lines',
    name: `Liquidity projection (next ${meta.lead_days} days)`,
    line: { color: GOLD, width: 2.2, dash: 'dot' },
    opacity: 0.85,
    hovertemplate: '%{x}<br>Projected z: <b>%{y:.2f}\u03c3</b><extra></extra>',
  };

  const allY = [...useqZ.values, ...histVals, ...futVals].filter(v => v !== null);
  const yMin = Math.min(...allY) - 0.3;
  const yMax = Math.max(...allY) + 0.3;

  // Buy / Close markers — always on the white equity line only
  const buyDates = [], buyYs = [], buyColors = [], buyText = [];
  const exitDates = [], exitYs = [], exitText = [];

  signals.forEach(s => {
    const color = TIER_COLOR[s.tier] || GOLD;
    const label = TIER_LABEL[s.tier] || s.tier;
    const d6str  = s.fwd_6mo_dz  != null ? (s.fwd_6mo_dz  >= 0 ? '+' : '') + s.fwd_6mo_dz.toFixed(2)  + '\u03c3' : 'TBD';
    const d12str = s.fwd_12mo_dz != null ? (s.fwd_12mo_dz >= 0 ? '+' : '') + s.fwd_12mo_dz.toFixed(2) + '\u03c3' : 'TBD';
    const peakStr = s.peak_liq_z != null ? (s.peak_liq_z >= 0 ? '+' : '') + s.peak_liq_z.toFixed(2) + '\u03c3' : '?';

    if (!s.entry_is_future && s.entry_eq_z != null) {
      buyDates.push(s.entry_date);
      buyYs.push(s.entry_eq_z);
      buyColors.push(color);
      buyText.push(`<b>BUY \u2014 ${label}</b><br>Entry: ${s.entry_date}<br>Liq trough: ${(s.trough_liq_z >= 0 ? '+' : '') + s.trough_liq_z.toFixed(2)}\u03c3 \u2192 peak: ${peakStr}<br>6-mo: ${d6str} | 12-mo: ${d12str}`);
    }
    if (s.close_date && !s.close_is_future && s.close_eq_z != null) {
      exitDates.push(s.close_date);
      exitYs.push(s.close_eq_z);
      exitText.push(`<b>CLOSE \u2014 ${label}</b><br>Exit: ${s.close_date}<br>Peak: ${peakStr} \u2192 dropped 0.5\u03c3 from peak`);
    }
  });

  const traceBuy = {
    x: buyDates, y: buyYs,
    type: 'scatter', mode: 'markers', name: 'BUY',
    marker: { symbol: 'triangle-up', size: 14, color: buyColors, line: { color: '#121212', width: 1.5 } },
    text: buyText, hovertemplate: '%{text}<extra></extra>',
  };
  const traceExit = {
    x: exitDates, y: exitYs,
    type: 'scatter', mode: 'markers', name: 'CLOSE',
    marker: { symbol: 'triangle-down', size: 14, color: RED, line: { color: '#121212', width: 1.5 } },
    text: exitText, hovertemplate: '%{text}<extra></extra>',
  };
  const traceShade = {
    x: [lastEqDate, lastEqDate, meta.proj_end_date, meta.proj_end_date],
    y: [yMin, yMax, yMax, yMin],
    type: 'scatter', mode: 'none', fill: 'toself',
    fillcolor: 'rgba(245,197,66,0.05)', line: { width: 0 },
    showlegend: false, hoverinfo: 'skip',
  };

  const layout = {
    paper_bgcolor: PANEL,
    plot_bgcolor:  PANEL,
    margin: { t: 44, r: 160, b: 48, l: 62 },
    font: { family: "'JetBrains Mono', monospace", color: GRAY, size: 11 },
    title: {
      text: `Acumen Global Liquidity Index vs US Equities  |  r = ${meta.corr_full} full sample, ${meta.corr_post20} post-2020  |  ${meta.lead_days}-day lead`,
      font: { size: 13, color: WHITE },
      x: 0.5, xanchor: 'center', y: 0.98,
    },
    xaxis: {
      type: 'date', gridcolor: GRID, gridwidth: 1,
      tickcolor: GRAY, linecolor: GRID, tickfont: { size: 10 },
      showspikes: true, spikecolor: GRAY, spikethickness: 1,
    },
    yaxis: {
      title: { text: 'Z-score (\u03c3 from 2015 mean)', font: { size: 10 }, standoff: 8 },
      gridcolor: GRID, gridwidth: 1, tickcolor: GRAY, linecolor: GRID,
      zeroline: true, zerolinecolor: '#444444', zerolinewidth: 1,
      tickfont: { size: 10 },
      showspikes: true, spikecolor: GRAY, spikethickness: 1,
    },
    legend: {
      orientation: 'v', x: 1.01, xanchor: 'left', y: 1.0, yanchor: 'top',
      bgcolor: 'rgba(30,30,30,0.85)', bordercolor: '#333333', borderwidth: 1,
      font: { size: 10 },
    },
    shapes: [
      { type: 'line', x0: lastEqDate, x1: lastEqDate, y0: yMin, y1: yMax,
        line: { color: '#555555', width: 1, dash: 'dot' } },
    ],
    annotations: [
      { x: lastEqDate, y: yMax * 0.92, text: 'today', showarrow: false,
        font: { size: 9, color: '#888888' }, xanchor: 'left', yanchor: 'top' },
    ],
    hovermode: 'x unified',
    hoverlabel: {
      bgcolor: '#242424', bordercolor: '#444444',
      font: { family: "'JetBrains Mono', monospace", size: 11 },
    },
  };

  const config = {
    responsive: true, displayModeBar: true,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
    displaylogo: false,
  };

  Plotly.newPlot('chart', [traceShade, traceEquity, traceHist, traceFuture, traceBuy, traceExit], layout, config);

  // Range toggles — rescale Y to visible data on each click
  const allSeries = [
    { dates: useqZ.dates,   vals: useqZ.values   },
    { dates: lqiZ.dates,    vals: lqiZ.values    },
    { dates: lqiProj.dates, vals: lqiProj.values },
  ];

  function getYRangeForWindow(xStart, xEnd) {
    let lo = Infinity, hi = -Infinity;
    allSeries.forEach(({ dates, vals }) => {
      dates.forEach((d, i) => {
        if (d >= xStart && d <= xEnd && vals[i] != null) {
          if (vals[i] < lo) lo = vals[i];
          if (vals[i] > hi) hi = vals[i];
        }
      });
    });
    if (!isFinite(lo)) return [yMin, yMax];
    const pad = (hi - lo) * 0.12;
    return [lo - pad, hi + pad];
  }

  function applyRange(rangeKey) {
    const projEnd = meta.proj_end_date;
    const now = new Date(meta.last_equity_date);
    let xStart;
    if (rangeKey === '1y') {
      const d = new Date(now); d.setFullYear(d.getFullYear() - 1);
      xStart = d.toISOString().slice(0, 10);
    } else if (rangeKey === '3y') {
      const d = new Date(now); d.setFullYear(d.getFullYear() - 3);
      xStart = d.toISOString().slice(0, 10);
    } else if (rangeKey === '5y') {
      const d = new Date(now); d.setFullYear(d.getFullYear() - 5);
      xStart = d.toISOString().slice(0, 10);
    } else {
      xStart = '2015-01-01';
    }
    const [yLo, yHi] = getYRangeForWindow(xStart, projEnd);
    Plotly.relayout('chart', { 'xaxis.range': [xStart, projEnd], 'yaxis.range': [yLo, yHi] });
  }

  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyRange(btn.dataset.range);
    });
  });
}

// ── Main ──────────────────────────────────────────────────────────────────────
function init() {
  renderSignals(ACUMEN_LIQUIDITY.meta);
  renderComponents(ACUMEN_LIQUIDITY.meta.components_b);
  renderChart(ACUMEN_LIQUIDITY);
  const { last_equity_date, proj_end_date } = ACUMEN_LIQUIDITY.meta;
  setStatus(`Updated through ${last_equity_date} \u00b7 Projection to ${proj_end_date}`, 'info');
}

document.addEventListener('DOMContentLoaded', init);
