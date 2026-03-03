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

async function fetchBinanceBTC() {
    const baseUrl = 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1w&limit=12';
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

async function updateData() {
    setLoading(true);
    try {
        const staticBtc = { dates: [...STATIC_DATA.btc.dates], values: [...STATIC_DATA.btc.values] };
        const staticM2  = { dates: [...STATIC_DATA.m2.dates],  values: [...STATIC_DATA.m2.values] };
        const staticDxy = { dates: [...STATIC_DATA.dxy.dates], values: [...STATIC_DATA.dxy.values] };
        console.log(`[Static] BTC: ${staticBtc.dates.length} | M2: ${staticM2.dates.length} | DXY: ${staticDxy.dates.length}`);

        setStatus('Fetching recent data...', 'info');
        const lastM2 = staticM2.dates[staticM2.dates.length - 1];
        const [liveM2, liveDxy, liveBtc] = await Promise.all([
            fetchFRED('M2SL', lastM2), fetchYahoo('DX-Y.NYB', '3mo', '1wk'), fetchYahoo('BTC-USD', '3mo', '1wk'),
        ]);
        let liveBtcFinal = liveBtc || await fetchBinanceBTC();

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
        const chartDiv = document.querySelector('.plotly-graph-div');
        const traces = chartDiv.data;
        for (let i = 0; i < traces.length; i++) {
            if (traces[i].name && traces[i].name.includes('Bitcoin')) { traces[i].x = btcW.dates; traces[i].y = btcW.values; }
            else if (traces[i].name && traces[i].name.includes('Model')) { traces[i].x = modelDates; traces[i].y = modelValues; }
            else if (traces[i].name && traces[i].name.includes('Liquidity')) { traces[i].x = liqDates; traces[i].y = liqValues; }
        }

        const layout = chartDiv.layout;
        layout.title.text = `Bitcoin vs Global Liquidity Index<br><sup>Liquidity leads BTC by ~${DISPLAY_LAG} weeks | r = ${bestCorr.toFixed(3)} | Model projects $${Math.round(projectedBTC).toLocaleString()} BTC</sup>`;

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

        Plotly.react(chartDiv, traces, layout);

        const live = [liveM2 && 'M2', liveDxy && 'DXY', liveBtcFinal && 'BTC'].filter(Boolean);
        setStatus(live.length > 0 ? `Updated ${new Date().toLocaleString()} | r=${bestCorr.toFixed(3)} | Live: ${live.join(', ')}` : `Static data | r=${bestCorr.toFixed(3)}`, 'success');
    } catch (err) { setStatus('Error: ' + err.message, 'error'); console.error(err); }
    finally { setLoading(false); }
}
document.addEventListener('DOMContentLoaded', updateData);
