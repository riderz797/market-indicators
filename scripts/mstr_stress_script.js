// ===== STATIC DATA (auto-generated — do not edit manually) =====
const STATIC_DATA = __STATIC_DATA__;

/* ─── THEME ──────────────────────────────────────────────────── */
const GOLD   = '#F5C542';
const WHITE  = '#FFFFFF';
const GRID   = '#333333';

/* ─── TRACE COLORS ───────────────────────────────────────────── */
const SIGNAL_CLR = '#4FC3F7';
const NAV_CLR    = GOLD;
const MOVE_CLR   = '#EF9A9A';
const HY_CLR     = '#81C784';
const BPS_CLR    = '#CE93D8';

/* ─── DATE FILTER ────────────────────────────────────────────── */
const START_DATE = '2024-08-16';

/* ─── STATE ──────────────────────────────────────────────────── */
let showMove = false;
let showHY   = false;
let showBPS  = false;

function toggleTrace(key) {
  if (key === 'move') showMove = !showMove;
  if (key === 'hy')   showHY   = !showHY;
  if (key === 'bps')  showBPS  = !showBPS;
  document.querySelectorAll('.comp-btn').forEach(btn => {
    const k = btn.dataset.key;
    if (k === 'move') btn.classList.toggle('active', showMove);
    if (k === 'hy')   btn.classList.toggle('active', showHY);
    if (k === 'bps')  btn.classList.toggle('active', showBPS);
  });
  renderChart();
}

function renderChart() {
  const raw = STATIC_DATA;
  const startIdx = raw.dates.findIndex(dt => dt >= START_DATE);
  const sl = (arr) => arr.slice(startIdx);
  const d = {
    dates: sl(raw.dates), stress_index: sl(raw.stress_index),
    move_z: sl(raw.move_z), hy_oas_z: sl(raw.hy_oas_z),
    nav_premium: sl(raw.nav_premium),
    move_raw: sl(raw.move_raw), hy_oas_raw: sl(raw.hy_oas_raw),
    btc_ps_mom_z: sl(raw.btc_ps_mom_z),
  };
  const traces = [];

  /* 1 — NAV Premium (right y-axis, gold area) */
  traces.push({
    x: d.dates, y: d.nav_premium,
    name: 'NAV Premium',
    yaxis: 'y2',
    type: 'scatter', mode: 'lines',
    fill: 'tozeroy',
    fillcolor: 'rgba(245,197,66,0.08)',
    line: { color: NAV_CLR, width: 2 },
    hovertemplate: '%{x|%b %d, %Y}<br>NAV Premium: %{y:.1f}%<extra></extra>',
  });

  /* 2 — Signal (left y-axis, cyan) — already "right way up" */
  traces.push({
    x: d.dates,
    y: d.stress_index,
    name: 'Signal',
    yaxis: 'y',
    type: 'scatter', mode: 'lines',
    line: { color: SIGNAL_CLR, width: 2.5 },
    hovertemplate: '%{x|%b %d, %Y}<br>Signal: %{y:.2f}<extra></extra>',
  });

  /* 3 — Optional: MOVE z-score (inverted so up = easing) */
  if (showMove) {
    traces.push({
      x: d.dates,
      y: d.move_z.map(v => v === null ? null : -v),
      name: 'MOVE Z (inv)',
      yaxis: 'y',
      type: 'scatter', mode: 'lines',
      line: { color: MOVE_CLR, width: 1.5, dash: 'dot' },
      customdata: d.move_z,
      hovertemplate: '%{x|%b %d, %Y}<br>MOVE Z: %{customdata:.2f}<extra></extra>',
    });
  }

  /* 4 — Optional: HY OAS z-score (inverted so up = easing) */
  if (showHY) {
    traces.push({
      x: d.dates,
      y: d.hy_oas_z.map(v => v === null ? null : -v),
      name: 'HY OAS Z (inv)',
      yaxis: 'y',
      type: 'scatter', mode: 'lines',
      line: { color: HY_CLR, width: 1.5, dash: 'dot' },
      customdata: d.hy_oas_z,
      hovertemplate: '%{x|%b %d, %Y}<br>HY OAS Z: %{customdata:.2f}<extra></extra>',
    });
  }

  /* 5 — Optional: BTC/share momentum z-score */
  if (showBPS) {
    traces.push({
      x: d.dates,
      y: d.btc_ps_mom_z,
      name: 'BTC/Share Mom Z',
      yaxis: 'y',
      type: 'scatter', mode: 'lines',
      line: { color: BPS_CLR, width: 1.5, dash: 'dot' },
      hovertemplate: '%{x|%b %d, %Y}<br>BTC/Share Mom Z: %{y:.2f}<extra></extra>',
    });
  }

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor:  'transparent',
    font: { family: "'JetBrains Mono', monospace", color: WHITE, size: 11 },
    margin: { t: 30, r: 72, b: 50, l: 72 },
    legend: {
      orientation: 'h', x: 0.5, xanchor: 'center', y: 1.06,
      font: { size: 10 }, bgcolor: 'transparent',
    },
    xaxis: {
      gridcolor: GRID, tickcolor: GRID, linecolor: GRID,
      tickfont: { size: 10 },
    },
    yaxis: {
      title: { text: 'Signal', font: { size: 10, color: SIGNAL_CLR } },
      gridcolor: GRID, tickcolor: GRID, linecolor: GRID,
      tickfont: { size: 10, color: SIGNAL_CLR },
      zeroline: true, zerolinecolor: '#555', zerolinewidth: 1,
    },
    yaxis2: {
      title: { text: 'NAV Premium (%)', font: { size: 10, color: NAV_CLR } },
      overlaying: 'y', side: 'right',
      gridcolor: 'transparent', tickcolor: GRID, linecolor: GRID,
      tickfont: { size: 10, color: NAV_CLR },
      ticksuffix: '%',
      zeroline: true, zerolinecolor: 'rgba(245,197,66,0.3)',
    },
    annotations: [
      {
        x: 0.01, y: 0.98, xref: 'paper', yref: 'paper',
        text: '<b>\u25B2</b> Easing',
        showarrow: false,
        font: { size: 11, color: '#66BB6A', family: "'JetBrains Mono', monospace" },
        xanchor: 'left', yanchor: 'top',
      },
      {
        x: 0.01, y: 0.92, xref: 'paper', yref: 'paper',
        text: '<b>\u25BC</b> Tightening',
        showarrow: false,
        font: { size: 11, color: '#EF5350', family: "'JetBrains Mono', monospace" },
        xanchor: 'left', yanchor: 'top',
      },
    ],
    hovermode: 'x unified',
    hoverlabel: {
      bgcolor: '#2D2D2D', bordercolor: '#555',
      font: { family: "'JetBrains Mono', monospace", size: 11 },
    },
  };

  Plotly.newPlot('chart', traces, layout, {
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  });
}

/* ─── INIT ───────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('status-bar');
  if (el) { el.textContent = 'Data through ' + STATIC_DATA.generated; el.className = ''; }
  renderChart();
});
