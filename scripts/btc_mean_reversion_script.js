// ===== STATIC DATA (auto-generated — do not edit manually) =====
const STATIC_DATA = __STATIC_DATA__;

const FRED_API_KEY = '824b29c5afa52f3fc7c6e7dc4925aebb';
const LAG_WEEKS = 13;

function setLoading(on) { if (on) setStatus('Loading...', 'info'); }
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
            if (!resp.ok) continue;
            const data = await resp.json();
            if (!data.observations) continue;
            const dates = [], values = [];
            for (const obs of data.observations) { if (obs.value !== '.') { dates.push(obs.date); values.push(parseFloat(obs.value)); } }
            if (dates.length > 0) { console.log(`[FRED ${seriesId}] OK via ${label} (${dates.length} pts)`); return { dates, values }; }
        } catch (e) { continue; }
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
            for (const k of data) { dates.push(new Date(k[0]).toISOString().slice(0, 10)); values.push(parseFloat(k[4])); }
            if (dates.length > 0) { console.log(`[Binance] OK via ${label} (${dates.length} pts)`); return { dates, values }; }
        } catch (e) { continue; }
    }
    return null;
}

function resampleWeekly(dates, values) {
    const weekly = new Map();
    for (let i = 0; i < dates.length; i++) {
        const d = new Date(dates[i]);
        const diff = (1 - d.getDay() + 7) % 7;
        const mon = new Date(d); mon.setDate(d.getDate() + diff);
        weekly.set(mon.toISOString().slice(0, 10), values[i]);
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

function linReg(x, y) {
    const n = x.length; let sx=0,sy=0,sxy=0,sx2=0;
    for (let i=0;i<n;i++){sx+=x[i];sy+=y[i];sxy+=x[i]*y[i];sx2+=x[i]*x[i];}
    const slope = (n*sxy - sx*sy) / (n*sx2 - sx*sx);
    return { slope, intercept: (sy - slope*sx) / n };
}

function shiftDates(dates, weeks) {
    return dates.map(d => { const dt = new Date(d); dt.setDate(dt.getDate() + weeks * 7); return dt.toISOString().slice(0, 10); });
}

async function updateData() {
    setLoading(true);
    try {
        const staticBtc = { dates: [...STATIC_DATA.btc.dates], values: [...STATIC_DATA.btc.values] };
        const staticM2  = { dates: [...STATIC_DATA.m2.dates],  values: [...STATIC_DATA.m2.values] };
        const staticDxy = { dates: [...STATIC_DATA.dxy.dates], values: [...STATIC_DATA.dxy.values] };

        setStatus('Fetching recent data...', 'info');
        const lastM2 = staticM2.dates[staticM2.dates.length - 1];
        const [liveM2, liveDxy, liveBtc] = await Promise.all([
            fetchFRED('M2SL', lastM2),
            fetchFRED('DTWEXBGS', staticDxy.dates[staticDxy.dates.length - 1]),
            fetchYahoo('BTC-USD', '3mo', '1wk'),
        ]);
        let liveBtcFinal = liveBtc || await fetchBinanceBTC();

        const m2W  = mergeWeekly(staticM2,  liveM2 ? resampleWeekly(liveM2.dates, liveM2.values) : null);
        const dxyW = mergeWeekly(staticDxy, liveDxy ? resampleWeekly(liveDxy.dates, liveDxy.values) : null);
        const btcW = mergeWeekly(staticBtc, liveBtcFinal ? resampleWeekly(liveBtcFinal.dates, liveBtcFinal.values) : null);

        setStatus('Computing model...', 'info');
        const m2Filled = forwardFillToIndex(m2W.dates, m2W.values, dxyW.dates);
        const glDates = [], glValues = [];
        for (let i = 0; i < dxyW.dates.length; i++) {
            if (m2Filled[i] != null && dxyW.values[i] != null) {
                glDates.push(dxyW.dates[i]); glValues.push(m2Filled[i] * (100 / dxyW.values[i]));
            }
        }

        const firstBtcDate = btcW.dates[0];
        const glShifted = shiftDates(glDates, LAG_WEEKS);
        const btcMap = new Map(btcW.dates.map((d,i) => [d, btcW.values[i]]));
        const regX = [], regY = [], regDates = [], regBtc = [], regLiq = [];

        for (let i = 0; i < glShifted.length; i++) {
            if (glShifted[i] < firstBtcDate) continue;
            const bv = btcMap.get(glShifted[i]);
            if (bv && bv > 0 && glValues[i] > 0) {
                regX.push(Math.log(glValues[i])); regY.push(Math.log(bv));
                regDates.push(glShifted[i]); regBtc.push(bv); regLiq.push(glValues[i]);
            }
        }

        const { slope, intercept } = linReg(regX, regY);
        const modelPrices = regLiq.map(l => Math.exp(slope * Math.log(l) + intercept));
        const logResiduals = regBtc.map((b, i) => Math.log(b) - Math.log(modelPrices[i]));
        const stdLogResid = Math.sqrt(logResiduals.reduce((s, r) => s + r*r, 0) / logResiduals.length
            - Math.pow(logResiduals.reduce((s, r) => s + r, 0) / logResiduals.length, 2));
        const sigmaValues = logResiduals.map(r => r / stdLogResid);

        const bands = {};
        for (const s of [0.5, 1, 1.5]) {
            bands[`+${s}`] = modelPrices.map(m => Math.exp(Math.log(m) + s * stdLogResid));
            bands[`-${s}`] = modelPrices.map(m => Math.exp(Math.log(m) - s * stdLogResid));
        }

        const currentBtc = regBtc[regBtc.length - 1];
        const currentModel = modelPrices[modelPrices.length - 1];
        const currentSigma = sigmaValues[sigmaValues.length - 1];

        const chartDiv = document.querySelector('.plotly-graph-div');
        const traces = chartDiv.data;
        for (let i = 0; i < traces.length; i++) {
            const name = traces[i].name;
            if (!name) continue;
            if (name === 'Bitcoin (USD)') { traces[i].x = regDates; traces[i].y = regBtc; }
            else if (name === 'Model Price') { traces[i].x = regDates; traces[i].y = modelPrices; }
            else if (name === 'Deviation (sigma)') { traces[i].x = regDates; traces[i].y = sigmaValues; }
            else if (name.includes('sigma')) {
                const match = name.match(/([+-]?[\d.]+)sigma/);
                if (match && bands[match[1]]) { traces[i].x = regDates; traces[i].y = bands[match[1]]; }
            }
        }

        const layout = chartDiv.layout;
        layout.title.text = `Bitcoin Mean Reversion Analysis<br><sub>Current: ${currentSigma >= 0 ? '+' : ''}${currentSigma.toFixed(2)}sigma | Model: $${Math.round(currentModel).toLocaleString()} | Actual: $${Math.round(currentBtc).toLocaleString()}</sub>`;
        Plotly.react(chartDiv, traces, layout);

        const live = [liveM2 && 'M2', liveDxy && 'DXY', liveBtcFinal && 'BTC'].filter(Boolean);
        setStatus(live.length > 0 ? `Updated ${new Date().toLocaleString()} | ${currentSigma.toFixed(2)}sigma | Live: ${live.join(', ')}` : `Static data | ${currentSigma.toFixed(2)}sigma`, 'success');
    } catch (err) { setStatus('Error: ' + err.message, 'error'); console.error(err); }
    finally { setLoading(false); }
}
document.addEventListener('DOMContentLoaded', updateData);
