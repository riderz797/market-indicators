// ===== STATIC DATA (auto-generated — do not edit manually) =====
const STATIC_DATA = __STATIC_DATA__;

const FRED_API_KEY = '824b29c5afa52f3fc7c6e7dc4925aebb';
const DISPLAY_LAG = 13; // weeks

function setLoading(on) {
    if (on) setStatus('Loading...', 'info');
}
function setStatus(msg, type) {
    const el = document.getElementById('update-status');
    if (!el) return;
    el.textContent = msg; el.className = 'visible ' + type;
    el.style.display = 'block';
    if (type === 'success') setTimeout(() => { el.style.display = 'none'; }, 5000);
}

async function fetchFRED(seriesId, startDate) {
    const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${seriesId}&api_key=${FRED_API_KEY}&file_type=json&observation_start=${startDate || '2000-01-01'}`;
    const ts = Date.now();
    const attempts = [
        { label: 'codetabs',   url: `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(url)}&_t=${ts}` },
        { label: 'allorigins', url: `https://api.allorigins.win/raw?_t=${ts}&url=${encodeURIComponent(url)}` },
        { label: 'direct',     url: url },
    ];
    for (const { label, url: attempt } of attempts) {
        try {
            const resp = await fetch(attempt);
            if (!resp.ok) { console.warn(`[FRED ${seriesId}] ${label}: HTTP ${resp.status}`); continue; }
            const data = await resp.json();
            if (!data.observations) continue;
            const dates = [], values = [];
            for (const obs of data.observations) {
                if (obs.value !== '.') { dates.push(obs.date); values.push(parseFloat(obs.value)); }
            }
            if (dates.length > 0) { console.log(`[FRED ${seriesId}] OK via ${label} (${dates.length} pts)`); return { dates, values }; }
        } catch (e) { console.warn(`[FRED ${seriesId}] ${label}: ${e.message}`); continue; }
    }
    return null;
}

async function fetchYahoo(ticker, range, interval) {
    const baseUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=${range}&interval=${interval || '1d'}`;
    const ts = Date.now();
    const proxies = [
        { label: 'allorigins', url: `https://api.allorigins.win/raw?_t=${ts}&url=${encodeURIComponent(baseUrl)}` },
        { label: 'codetabs',   url: `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(baseUrl)}&_t=${ts}` },
    ];
    for (const { label, url: proxyUrl } of proxies) {
        try {
            const resp = await fetch(proxyUrl);
            if (!resp.ok) continue;
            const json = await resp.json();
            const result = json.chart.result[0];
            const dates = [], values = [];
            for (let i = 0; i < result.timestamp.length; i++) {
                if (result.indicators.quote[0].close[i] != null) {
                    dates.push(new Date(result.timestamp[i] * 1000).toISOString().slice(0, 10));
                    values.push(result.indicators.quote[0].close[i]);
                }
            }
            console.log(`[Yahoo ${ticker}] OK via ${label} (${dates.length} pts)`);
            return { dates, values };
        } catch (e) { continue; }
    }
    return null;
}

async function fetchCoinGeckoBTC() {
    try {
        const resp = await fetch('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=90&interval=daily');
        if (!resp.ok) { console.warn(`[CoinGecko] HTTP ${resp.status}`); return null; }
        const data = await resp.json();
        if (!data.prices || data.prices.length === 0) return null;
        const dates = [], values = [];
        for (const [ts, price] of data.prices) {
            dates.push(new Date(ts).toISOString().slice(0, 10));
            values.push(price);
        }
        console.log(`[CoinGecko BTC] OK (${dates.length} pts, latest $${Math.round(values[values.length-1]).toLocaleString()})`);
        return { dates, values };
    } catch (e) { console.warn(`[CoinGecko] ${e.message}`); return null; }
}

async function fetchBinanceBTC() {
    const baseUrl = 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=90';
    const ts = Date.now();
    const attempts = [
        { label: 'codetabs',   url: `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(baseUrl)}&_t=${ts}` },
        { label: 'allorigins', url: `https://api.allorigins.win/raw?_t=${ts}&url=${encodeURIComponent(baseUrl)}` },
        { label: 'direct',     url: baseUrl },
    ];
    for (const { label, url } of attempts) {
        try {
            const resp = await fetch(url);
            if (!resp.ok) continue;
            const data = await resp.json();
            if (!Array.isArray(data) || data.length === 0) continue;
            const dates = [], values = [];
            for (const k of data) {
                dates.push(new Date(k[0]).toISOString().slice(0, 10));
                values.push(parseFloat(k[4]));
            }
            if (dates.length > 0) { console.log(`[Binance] OK via ${label} (${dates.length} pts)`); return { dates, values }; }
        } catch (e) { continue; }
    }
    return null;
}

function resampleWeekly(dates, values) {
    const weekly = new Map();
    for (let i = 0; i < dates.length; i++) {
        const d = new Date(dates[i]);
        const diff = (5 - d.getDay() + 7) % 7;
        const fri = new Date(d); fri.setDate(d.getDate() + diff);
        weekly.set(fri.toISOString().slice(0, 10), values[i]);
    }
    const sorted = [...weekly.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return { dates: sorted.map(s => s[0]), values: sorted.map(s => s[1]) };
}

function mergeWeekly(staticSeries, liveSeries) {
    const map = new Map();
    for (let i = 0; i < staticSeries.dates.length; i++) map.set(staticSeries.dates[i], staticSeries.values[i]);
    if (liveSeries) for (let i = 0; i < liveSeries.dates.length; i++) map.set(liveSeries.dates[i], liveSeries.values[i]);
    const sorted = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return { dates: sorted.map(s => s[0]), values: sorted.map(s => s[1]) };
}

function forwardFillToIndex(srcDates, srcValues, targetDates) {
    const result = []; let si = 0;
    for (const td of targetDates) {
        while (si < srcDates.length - 1 && srcDates[si + 1] <= td) si++;
        result.push(srcDates[si] <= td ? srcValues[si] : null);
    }
    return result;
}

function pearsonCorr(x, y) {
    const n = x.length; let sx=0,sy=0,sxy=0,sx2=0,sy2=0;
    for (let i=0;i<n;i++){sx+=x[i];sy+=y[i];sxy+=x[i]*y[i];sx2+=x[i]*x[i];sy2+=y[i]*y[i];}
    const num = n*sxy - sx*sy, den = Math.sqrt((n*sx2-sx*sx)*(n*sy2-sy*sy));
    return den === 0 ? 0 : num/den;
}

function linReg(x, y) {
    const n = x.length; let sx=0,sy=0,sxy=0,sx2=0;
    for (let i=0;i<n;i++){sx+=x[i];sy+=y[i];sxy+=x[i]*y[i];sx2+=x[i]*x[i];}
    return { slope: (n*sxy - sx*sy) / (n*sx2 - sx*sx), intercept: (sy - ((n*sxy - sx*sy) / (n*sx2 - sx*sx))*sx) / n };
}

function shiftDatesForward(dates, weeks) {
    return dates.map(d => { const dt = new Date(d); dt.setDate(dt.getDate() + weeks * 7); return dt.toISOString().slice(0, 10); });
}

// ── Call-option signal (from backtest_btc_liquidity.py, walk-forward 2017-2026) ──
const SIGNAL_Q4_ROC = 0.0373;   // top-quartile 13-week liquidity growth threshold
const SIGNAL_TIERS = {
    strong: { label: 'STRONG', color: '#1a7f37',
        desc: 'Liquidity thrust — top-quartile momentum',
        n: 119, win: '72%', avg: '+41%', callp: '62%' },
    active: { label: 'ACTIVE', color: '#9a6700',
        desc: 'Cheap vs model + liquidity rising',
        n: 111, win: '63%', avg: '+36%', callp: '57%' },
    moderate: { label: 'MODERATE', color: '#57606a',
        desc: 'Liquidity rising, no valuation edge',
        n: 265, win: '58%', avg: '+27%', callp: '50%' },
    avoid: { label: 'AVOID', color: '#cf222e',
        desc: 'BTC 10–30% above model — negative expectancy',
        n: 28, win: '32%', avg: '−11%', callp: '29%' },
    stand: { label: 'STAND ASIDE', color: '#57606a',
        desc: 'Liquidity contracting — no tested edge',
        n: 184, win: '47%', avg: '+2%', callp: '32%' },
};

function computeSignalTier(gap, roc) {
    if (roc != null && roc >= SIGNAL_Q4_ROC) return 'strong';
    if (gap != null && roc != null && gap < -0.20 && roc > 0) return 'active';
    if (roc != null && roc > 0) return 'moderate';
    if (gap != null && gap >= 0.10 && gap < 0.30) return 'avoid';
    return 'stand';
}

function rocSparklineSVG(series, width, height) {
    // series: last ~52 weekly values of 13-wk liquidity growth (fractions)
    if (!series || series.length < 4) return '';
    const lo = Math.min(...series, -0.005), hi = Math.max(...series, SIGNAL_Q4_ROC + 0.005);
    const pad = (hi - lo) * 0.12;
    const x = i => (i / (series.length - 1)) * (width - 8) + 2;
    const y = v => height - 3 - ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (height - 6);
    let path = '';
    for (let i = 0; i < series.length; i++) {
        path += (i ? ' L' : 'M') + x(i).toFixed(1) + ' ' + y(series[i]).toFixed(1);
    }
    const last = series[series.length - 1];
    return '<svg width="' + width + '" height="' + height + '" style="display:block">' +
        '<line x1="2" x2="' + (width - 2) + '" y1="' + y(0).toFixed(1) + '" y2="' + y(0).toFixed(1) +
            '" stroke="#8b949e" stroke-width="1" stroke-dasharray="3 3"/>' +
        '<line x1="2" x2="' + (width - 2) + '" y1="' + y(SIGNAL_Q4_ROC).toFixed(1) + '" y2="' + y(SIGNAL_Q4_ROC).toFixed(1) +
            '" stroke="#1a7f37" stroke-width="1" stroke-dasharray="2 4" opacity="0.55"/>' +
        '<text x="' + (width - 4) + '" y="' + (y(SIGNAL_Q4_ROC) - 3).toFixed(1) +
            '" text-anchor="end" font-size="9" fill="#1a7f37" opacity="0.8">thrust +3.7%</text>' +
        '<text x="' + (width - 4) + '" y="' + (y(0) + 11).toFixed(1) +
            '" text-anchor="end" font-size="9" fill="#8b949e">0</text>' +
        '<path d="' + path + '" fill="none" stroke="#24292f" stroke-width="1.6" stroke-linejoin="round"/>' +
        '<circle cx="' + x(series.length - 1).toFixed(1) + '" cy="' + y(last).toFixed(1) +
            '" r="3.2" fill="' + (last > 0 ? '#1a7f37' : '#cf222e') + '" stroke="#fff" stroke-width="1"/>' +
        '</svg>';
}

function renderSignalCard(chartDiv, gap, roc, overlay, rocSeries) {
    const old = document.getElementById('call-signal-card');
    if (old) old.remove();
    const tierKey = computeSignalTier(gap, roc);
    const t = SIGNAL_TIERS[tierKey];
    const fmtPct = (v, dec) => v == null ? 'n/a' : (v > 0 ? '+' : '−') + Math.abs(v * 100).toFixed(dec) + '%';

    let watch = '';
    if (tierKey === 'stand' && gap != null && gap < -0.20) {
        watch = 'Trigger: growth crossing above 0 upgrades this to ACTIVE ' +
                '(BTC higher 3 mo later 63% of the time, avg +36%).';
    } else if (tierKey === 'active' && roc != null && roc < SIGNAL_Q4_ROC) {
        watch = 'Growth is positive but below the +3.7% thrust level — ' +
                'weaker tier; prefer 3–6 month expiries.';
    } else if (tierKey === 'strong') {
        watch = 'Strongest tested signal; edge peaks at 2–3 months. ' +
                'Rare condition — size to lose the full premium.';
    }

    const row = (label, val) =>
        '<div style="display:flex;justify-content:space-between;margin-top:2px">' +
        '<span style="color:#57606a">' + label + '</span><b>' + val + '</b></div>';

    const card = document.createElement('div');
    card.id = 'call-signal-card';
    card.style.cssText = (overlay
        ? 'position:absolute;right:10px;top:90px;width:238px;z-index:3;'
        : 'position:relative;max-width:420px;margin:12px auto;') +
        'background:#fff;border:1px solid #d0d7de;border-left:4px solid ' + t.color + ';' +
        'border-radius:8px;padding:12px 14px;font-family:Arial,sans-serif;font-size:12px;' +
        'color:#24292f;line-height:1.5;box-shadow:0 2px 8px rgba(0,0,0,0.08);text-align:left;';
    card.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">' +
          '<span style="font-size:11px;letter-spacing:.6px;color:#57606a;font-weight:bold">CALL-OPTION SIGNAL</span>' +
          '<span style="background:' + t.color + ';color:#fff;border-radius:10px;padding:1px 9px;' +
                'font-size:11px;font-weight:bold">' + t.label + '</span></div>' +
        '<div style="color:#57606a;margin-bottom:8px">' + t.desc + '</div>' +
        '<div style="border-top:1px solid #eee;padding-top:7px">' +
          row('Gap vs model', fmtPct(gap, 0)) +
          row('Liquidity growth (13-wk)', fmtPct(roc, 1)) +
          rocSparklineSVG(rocSeries, 210, 46) +
          '<div style="color:#8b949e;font-size:10.5px">liquidity index now vs 13 weeks ago · last 12 months</div>' +
        '</div>' +
        '<div style="border-top:1px solid #eee;margin-top:7px;padding-top:7px">' +
          '<div style="color:#57606a;margin-bottom:2px">In ' + t.n + ' similar weeks since 2017:</div>' +
          row('BTC higher 3 mo later', t.win) +
          row('Average 3-mo move', t.avg) +
          row('ATM call profitable', t.callp) +
        '</div>' +
        (watch ? '<div style="border-top:1px solid #eee;margin-top:7px;padding-top:7px;color:#9a6700">' +
                 watch + '</div>' : '') +
        '<div style="margin-top:7px;color:#8b949e;font-size:10.5px">Walk-forward backtest 2017–2026 · ' +
          'analogs, not forecasts · not financial advice</div>';

    if (overlay) {
        chartDiv.style.position = 'relative';
        chartDiv.appendChild(card);
    } else {
        chartDiv.parentNode.insertBefore(card, chartDiv.nextSibling);
    }
}

async function updateData() {
    setLoading(true);
    try {
        const staticBtc = { dates: [...STATIC_DATA.btc.dates], values: [...STATIC_DATA.btc.values] };
        const staticM2  = { dates: [...STATIC_DATA.m2.dates],  values: [...STATIC_DATA.m2.values] };
        const staticDxy = { dates: [...STATIC_DATA.dxy.dates], values: [...STATIC_DATA.dxy.values] };
        console.log(`[Static] BTC: ${staticBtc.dates.length} | M2: ${staticM2.dates.length} | DXY: ${staticDxy.dates.length}`);

        setStatus('Fetching recent data...', 'info');
        const lastM2 = staticM2.dates[staticM2.dates.length - 1];
        const [liveM2, liveDxy, liveBtcCG] = await Promise.all([
            fetchFRED('M2SL', lastM2), fetchYahoo('DX-Y.NYB', '3mo', '1wk'), fetchCoinGeckoBTC(),
        ]);
        let liveBtcFinal = liveBtcCG || await fetchYahoo('BTC-USD', '3mo', '1d') || await fetchBinanceBTC();

        const m2W  = mergeWeekly(staticM2,  liveM2 ? resampleWeekly(liveM2.dates, liveM2.values) : null);
        const dxyW = mergeWeekly(staticDxy, liveDxy ? resampleWeekly(liveDxy.dates, liveDxy.values) : null);
        const btcW = mergeWeekly(staticBtc, liveBtcFinal ? resampleWeekly(liveBtcFinal.dates, liveBtcFinal.values) : null);
        console.log(`[Merged] BTC: ${btcW.dates.length} | DXY: ${dxyW.dates.length}`);

        setStatus('Computing model...', 'info');
        const m2Filled = forwardFillToIndex(m2W.dates, m2W.values, dxyW.dates);
        const glDates = [], glValues = [];
        for (let i = 0; i < dxyW.dates.length; i++) {
            if (m2Filled[i] != null && dxyW.values[i] != null) {
                glDates.push(dxyW.dates[i]); glValues.push(m2Filled[i] * (100 / dxyW.values[i]));
            }
        }

        const btcMap = new Map(btcW.dates.map((d,i) => [d, btcW.values[i]]));
        let bestLag = 1, bestCorr = -1;
        for (let lag = 1; lag <= 30; lag++) {
            const shifted = shiftDatesForward(glDates, lag);
            const xs = [], ys = [];
            for (let i = 0; i < shifted.length; i++) {
                const bv = btcMap.get(shifted[i]);
                if (bv && bv > 0 && glValues[i] > 0) { xs.push(Math.log(glValues[i])); ys.push(Math.log(bv)); }
            }
            if (xs.length >= 52) { const r = pearsonCorr(xs, ys); if (r > bestCorr) { bestCorr = r; bestLag = lag; } }
        }

        const shiftedReg = shiftDatesForward(glDates, bestLag);
        const regX = [], regY = [];
        for (let i = 0; i < shiftedReg.length; i++) {
            const bv = btcMap.get(shiftedReg[i]);
            if (bv && bv > 0 && glValues[i] > 0) { regX.push(Math.log(glValues[i])); regY.push(Math.log(bv)); }
        }
        const { slope, intercept } = linReg(regX, regY);

        const firstBtcDate = btcW.dates[0];
        const glShiftedDates = shiftDatesForward(glDates, DISPLAY_LAG);
        const modelDates = [], modelValues = [], liqDates = [], liqValues = [];
        for (let i = 0; i < glShiftedDates.length; i++) {
            if (glShiftedDates[i] < firstBtcDate) continue;
            liqDates.push(glShiftedDates[i]); liqValues.push(glValues[i]);
            modelDates.push(glShiftedDates[i]); modelValues.push(Math.exp(slope * Math.log(glValues[i]) + intercept));
        }

        const projectedBTC = modelValues[modelValues.length - 1];

        // signal inputs: gap vs model at the latest BTC date, 13w liquidity growth
        const lastBtcDate = btcW.dates[btcW.dates.length - 1];
        let modelAtToday = null;
        for (let i = modelDates.length - 1; i >= 0; i--) {
            if (modelDates[i] <= lastBtcDate) { modelAtToday = modelValues[i]; break; }
        }
        const sigGap = modelAtToday
            ? Math.log(btcW.values[btcW.values.length - 1] / modelAtToday) : null;
        const sigRoc = glValues.length > 13
            ? glValues[glValues.length - 1] / glValues[glValues.length - 14] - 1 : null;
        const sigRocSeries = [];   // 13-wk growth, last ~52 weeks, for the card sparkline
        for (let i = Math.max(13, glValues.length - 52); i < glValues.length; i++) {
            sigRocSeries.push(glValues[i] / glValues[i - 13] - 1);
        }

        const chartDiv = document.querySelector('.plotly-graph-div');
        const traces = chartDiv.data;
        for (let i = 0; i < traces.length; i++) {
            if (traces[i].name && traces[i].name.includes('Bitcoin')) { traces[i].x = btcW.dates; traces[i].y = btcW.values; }
            else if (traces[i].name && traces[i].name.includes('Model')) { traces[i].x = modelDates; traces[i].y = modelValues; }
            else if (traces[i].name && traces[i].name.includes('Liquidity')) { traces[i].x = liqDates; traces[i].y = liqValues; }
        }

        const layout = chartDiv.layout;
        layout.title.text = `Bitcoin vs DXY Weighted Money Supply<br><sup>Liquidity leads BTC by ~${DISPLAY_LAG} weeks | r = ${bestCorr.toFixed(3)} | Model projects $${Math.round(projectedBTC).toLocaleString()} BTC</sup>`;

        const today = btcW.dates[btcW.dates.length - 1];
        const projEnd = liqDates[liqDates.length - 1];
        if (layout.shapes) {
            for (const shape of layout.shapes) {
                if (shape.fillcolor && shape.fillcolor.includes('229,57,53')) { shape.x0 = today; shape.x1 = projEnd; }
                if (shape.line && shape.line.dash === 'dot') { shape.x0 = today; shape.x1 = today; }
            }
        }

        // Compute explicit y-ranges for range buttons
        function computeYRange(startDate, endDate) {
            let btcMin = Infinity, btcMax = -Infinity, liqMin = Infinity, liqMax = -Infinity;
            for (let i = 0; i < btcW.dates.length; i++) {
                if (btcW.dates[i] >= startDate && btcW.dates[i] <= endDate && btcW.values[i] > 0) {
                    btcMin = Math.min(btcMin, btcW.values[i]); btcMax = Math.max(btcMax, btcW.values[i]);
                }
            }
            for (let i = 0; i < modelDates.length; i++) {
                if (modelDates[i] >= startDate && modelDates[i] <= endDate && modelValues[i] > 0) {
                    btcMin = Math.min(btcMin, modelValues[i]); btcMax = Math.max(btcMax, modelValues[i]);
                }
            }
            for (let i = 0; i < liqDates.length; i++) {
                if (liqDates[i] >= startDate && liqDates[i] <= endDate) {
                    liqMin = Math.min(liqMin, liqValues[i]); liqMax = Math.max(liqMax, liqValues[i]);
                }
            }
            const pad = 0.1;
            if (btcMin < Infinity) {
                const lr = Math.log10(btcMax) - Math.log10(btcMin);
                btcMin = Math.pow(10, Math.log10(btcMin) - lr * pad);
                btcMax = Math.pow(10, Math.log10(btcMax) + lr * pad);
            }
            if (liqMin < Infinity) { const r = liqMax - liqMin; liqMin -= r * pad; liqMax += r * pad; }
            return { btcMin, btcMax, liqMin, liqMax };
        }

        if (layout.updatemenus) {
            for (const menu of layout.updatemenus) {
                if (menu.buttons) {
                    const lastDate = liqDates[liqDates.length - 1] || btcW.dates[btcW.dates.length - 1];
                    for (const btn of menu.buttons) {
                        const rangeMap = { '6M': 6, '1Y': 12, '5Y': 60 };
                        const months = rangeMap[btn.label];
                        if (months) {
                            const start = new Date(lastDate); start.setMonth(start.getMonth() - months);
                            const startStr = start.toISOString().slice(0, 10);
                            const yr = computeYRange(startStr, lastDate);
                            btn.args[0] = {
                                'xaxis.range': [start.toISOString(), lastDate + 'T00:00:00'],
                                'yaxis.range': [Math.log10(yr.btcMin), Math.log10(yr.btcMax)],
                                'yaxis2.range': [yr.liqMin, yr.liqMax]
                            };
                        } else if (btn.label === 'All') {
                            btn.args[0] = { 'xaxis.autorange': true, 'yaxis.autorange': true, 'yaxis2.autorange': true };
                        }
                    }
                }
            }
        }

        // shift the plot left to make room for the signal card on wide screens
        const wideChart = (chartDiv.offsetWidth || window.innerWidth) >= 900;
        if (wideChart) layout.margin = Object.assign({}, layout.margin || {}, { r: 330 });

        Plotly.react(chartDiv, traces, layout);

        renderSignalCard(chartDiv, sigGap, sigRoc, wideChart, sigRocSeries);

        // Watermark — HTML overlay so it always renders regardless of Plotly version
        (function addAcumenWatermark() {
            const existing = chartDiv.querySelector('.acumen-wm');
            if (existing) existing.remove();

            // Use Plotly's computed margins to center exactly on the plot area
            const fl = chartDiv._fullLayout;
            const ml = (fl && fl.margin) ? fl.margin.l : 80;
            const mt = (fl && fl.margin) ? fl.margin.t : 80;
            const mr = (fl && fl.margin) ? fl.margin.r : 80;
            const mb = (fl && fl.margin) ? fl.margin.b : 60;
            const cw = (fl && fl.width)  ? fl.width  : chartDiv.offsetWidth;
            const ch = (fl && fl.height) ? fl.height : chartDiv.offsetHeight;

            const cx = ml + (cw - ml - mr) / 2;
            const cy = mt + (ch - mt - mb) / 2;
            const sz = Math.min(cw - ml - mr, ch - mt - mb) * 0.18; // 18% of plot area

            const wm = document.createElement('div');
            wm.className = 'acumen-wm';
            wm.style.cssText = `position:absolute;left:${cx}px;top:${cy}px;` +
                `transform:translate(-50%,-50%);pointer-events:none;z-index:2;opacity:0.13;`;
            wm.innerHTML =
                `<svg xmlns="http://www.w3.org/2000/svg" width="${sz}" height="${sz}" viewBox="0 0 120 120">` +
                `<polygon points="112,60 86,15 34,15 8,60 34,105 86,105" ` +
                    `fill="none" stroke="#444" stroke-width="6.5" stroke-linejoin="round"/>` +
                `<text x="60" y="84" text-anchor="middle" ` +
                    `font-family="Arial Black,Arial,sans-serif" font-size="62" font-weight="900" fill="#444">A</text>` +
                `</svg>`;

            chartDiv.style.position = 'relative';
            chartDiv.appendChild(wm);
        })();

        const live = [liveM2 && 'M2', liveDxy && 'DXY', liveBtcFinal && 'BTC'].filter(Boolean);
        setStatus(live.length > 0 ? `Updated ${new Date().toLocaleString()} | r=${bestCorr.toFixed(3)} | Live: ${live.join(', ')}` : `Static data | r=${bestCorr.toFixed(3)}`, 'success');
    } catch (err) { setStatus('Error: ' + err.message, 'error'); console.error(err); }
    finally { setLoading(false); }
}
document.addEventListener('DOMContentLoaded', updateData);
