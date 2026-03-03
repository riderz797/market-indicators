// ===== STATIC DATA (auto-generated — do not edit manually) =====
const STATIC_DATA = __STATIC_DATA__;

const FRED_API_KEY = '824b29c5afa52f3fc7c6e7dc4925aebb';
const COMPONENT_WEIGHTS = {
    fed_balance_sheet: 1.8, TGA: 1.8, RRP: 1.8,
    hy_spread: 1.5, real_yield: 1.5,
    vix: 1.2, yield_curve: 1.2,
    DXY: 1.0, risk_gold: 1.0,
    liquidity_spread: 0.8
};
const SIGNS = { DXY: 1, risk_gold: -1, liquidity_spread: 1, real_yield: 1, TGA: 1, yield_curve: -1, RRP: -1, fed_balance_sheet: -1, hy_spread: 1, vix: 1 };
const LABELS = { DXY: 'US Dollar (DXY)', risk_gold: 'Risk/Gold Ratio', liquidity_spread: 'SOFR-IORB Spread', real_yield: 'Real Yield (10Y-Inflation)', TGA: 'Treasury General Account', yield_curve: 'Yield Curve (10Y-2Y)', RRP: 'Reverse Repo (RRP)', fed_balance_sheet: 'Fed Balance Sheet', hy_spread: 'HY Credit Spread', vix: 'VIX' };
const SMOOTH = { '3M': 1, '1Y': 2, '5Y': 4 };

function setLoading(on) { if (on) setStatus('Loading...', 'info'); }
function setStatus(msg, type) {
    const el = document.getElementById('update-status');
    if (!el) return;
    el.textContent = msg; el.className = 'visible ' + type;
    el.style.display = 'block';
    if (type === 'success') setTimeout(() => { el.style.display = 'none'; }, 5000);
}

async function fetchFRED(seriesId, startDate) {
    const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${seriesId}&api_key=${FRED_API_KEY}&file_type=json&observation_start=${startDate || '1980-01-01'}`;
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

async function fetchTGA() {
    try {
        const url = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance?filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Opening%20Balance&sort=-record_date&page[size]=100';
        const resp = await fetch(url);
        if (!resp.ok) return null;
        const data = await resp.json();
        const dates = [], values = [];
        for (const row of data.data) { dates.push(row.record_date); values.push(parseFloat(row.open_today_bal) / 1000); }
        dates.reverse(); values.reverse();
        console.log(`[TGA] OK (${dates.length} pts)`);
        return { dates, values };
    } catch (e) { return null; }
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
    if (!staticSeries && !liveSeries) return null;
    const map = new Map();
    if (staticSeries) for (let i = 0; i < staticSeries.dates.length; i++) map.set(staticSeries.dates[i], staticSeries.values[i]);
    if (liveSeries) for (let i = 0; i < liveSeries.dates.length; i++) map.set(liveSeries.dates[i], liveSeries.values[i]);
    const sorted = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return { dates: sorted.map(s => s[0]), values: sorted.map(s => s[1]) };
}

function alignToIndex(srcDates, srcValues, targetDates) {
    const map = new Map(srcDates.map((d, i) => [d, srcValues[i]]));
    const result = []; let last = null;
    for (const td of targetDates) { if (map.has(td)) last = map.get(td); result.push(last); }
    return result;
}

function rollingZScores(values, window, minPeriods) {
    const z = new Array(values.length).fill(null);
    for (let i = minPeriods - 1; i < values.length; i++) {
        const start = Math.max(0, i - window + 1);
        const slice = [];
        for (let j = start; j <= i; j++) { if (values[j] != null) slice.push(values[j]); }
        if (slice.length < minPeriods) continue;
        const mean = slice.reduce((a, b) => a + b, 0) / slice.length;
        const std = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / slice.length);
        z[i] = std === 0 ? 0 : (values[i] - mean) / std;
    }
    return z;
}

function rollingAvg(values, window) {
    if (window <= 1) return values;
    const result = [];
    for (let i = 0; i < values.length; i++) {
        let sum = 0, count = 0;
        for (let j = Math.max(0, i - window + 1); j <= i; j++) { if (values[j] != null) { sum += values[j]; count++; } }
        result.push(count > 0 ? sum / count : null);
    }
    return result;
}

async function updateData() {
    setLoading(true);
    try {
        const staticMap = {};
        const seriesMapping = {
            'WALCL': 'fed_balance_sheet', 'DGS10': 'us10y', 'DGS2': 'us2y',
            'SP500': 'spx', 'DJIA': 'dji', 'T10YIE': 'inflation',
            'RRPONTSYD': 'rrp', 'SOFR': 'sofr', 'IORB': 'iorb',
            'BAMLH0A0HYM2': 'hy_spread', 'VIXCLS': 'vix',
            'GOLD': 'gold', 'DTWEXBGS': 'dxy', 'BTC': 'btc', 'TGA': 'tga'
        };
        for (const [key, data] of Object.entries(STATIC_DATA)) {
            if (key === 'generated') continue;
            staticMap[key] = { dates: [...data.dates], values: [...data.values] };
        }
        console.log('[Static] Loaded ' + Object.keys(staticMap).length + ' series');

        setStatus('Fetching recent data...', 'info');
        const recentStart = new Date();
        recentStart.setMonth(recentStart.getMonth() - 3);
        const startStr = recentStart.toISOString().slice(0, 10);

        const fredIds = ['WALCL','DGS10','DGS2','SP500','DJIA','T10YIE','RRPONTSYD','SOFR','IORB','BAMLH0A0HYM2','VIXCLS','DTWEXBGS'];
        const fredResults = await Promise.allSettled(fredIds.map(id => fetchFRED(id, startStr)));
        const [btcRes, tgaRes] = await Promise.allSettled([fetchBinanceBTC(), fetchTGA()]);

        const weekly = {};
        fredIds.forEach((id, i) => {
            const live = fredResults[i].status === 'fulfilled' ? fredResults[i].value : null;
            const liveW = live ? resampleWeekly(live.dates, live.values) : null;
            const merged = mergeWeekly(staticMap[id] || null, liveW);
            if (!merged) return;
            const name = seriesMapping[id];
            weekly[name] = id === 'WALCL' ? { dates: merged.dates, values: merged.values.map(v => v / 1000) } : merged;
        });

        if (staticMap.GOLD) weekly.gold = { dates: [...staticMap.GOLD.dates], values: [...staticMap.GOLD.values] };

        const liveBtc = btcRes.status === 'fulfilled' ? btcRes.value : null;
        const liveBtcW = liveBtc ? resampleWeekly(liveBtc.dates, liveBtc.values) : null;
        const mergedBtc = mergeWeekly(staticMap.BTC || null, liveBtcW);
        if (mergedBtc) weekly.btc = mergedBtc;

        const liveTga = tgaRes.status === 'fulfilled' ? tgaRes.value : null;
        const liveTgaW = liveTga ? resampleWeekly(liveTga.dates, liveTga.values) : null;
        const mergedTga = mergeWeekly(staticMap.TGA || null, liveTgaW);
        if (mergedTga) weekly.tga = mergedTga;

        setStatus('Computing z-score index...', 'info');
        const masterDates = weekly.dxy ? weekly.dxy.dates : (weekly.us10y ? weekly.us10y.dates : []);
        const aligned = {};
        for (const [key, w] of Object.entries(weekly)) aligned[key] = alignToIndex(w.dates, w.values, masterDates);

        const n = masterDates.length;
        const series = {};
        if (aligned.dxy) series.DXY = aligned.dxy;
        if (aligned.hy_spread) series.hy_spread = aligned.hy_spread;
        if (aligned.vix) series.vix = aligned.vix;
        if (aligned.fed_balance_sheet) series.fed_balance_sheet = aligned.fed_balance_sheet;
        if (aligned.tga) series.TGA = aligned.tga;

        if (aligned.us10y && aligned.inflation) series.real_yield = aligned.us10y.map((v, i) => v != null && aligned.inflation[i] != null ? v - aligned.inflation[i] : null);
        if (aligned.us10y && aligned.us2y) series.yield_curve = aligned.us10y.map((v, i) => v != null && aligned.us2y[i] != null ? v - aligned.us2y[i] : null);
        if (aligned.sofr && aligned.iorb) series.liquidity_spread = aligned.sofr.map((v, i) => v != null && aligned.iorb[i] != null ? v - aligned.iorb[i] : null);
        if (aligned.rrp) series.RRP = aligned.rrp.map((v, i) => i > 0 && v != null && aligned.rrp[i-1] != null ? v - aligned.rrp[i-1] : null);

        const ratios = {};
        if (aligned.btc && aligned.gold) ratios['BTC/Gold'] = aligned.btc.map((v, i) => v && aligned.gold[i] ? v / aligned.gold[i] : null);
        if (aligned.spx && aligned.gold) ratios['SPX/Gold'] = aligned.spx.map((v, i) => v && aligned.gold[i] ? v / aligned.gold[i] : null);
        if (aligned.dji && aligned.gold) ratios['DJI/Gold'] = aligned.dji.map((v, i) => v && aligned.gold[i] ? v / aligned.gold[i] : null);

        const zScores = {};
        for (const [key, vals] of Object.entries(series)) zScores[key] = rollingZScores(vals, 260, 52);
        const ratioZ = {};
        for (const [key, vals] of Object.entries(ratios)) ratioZ[key] = rollingZScores(vals, 260, 52);

        zScores.risk_gold = new Array(n).fill(null);
        for (let i = 0; i < n; i++) {
            const vals = [];
            for (const key of ['BTC/Gold', 'SPX/Gold', 'DJI/Gold']) { if (ratioZ[key] && ratioZ[key][i] != null) vals.push(ratioZ[key][i]); }
            if (vals.length > 0) zScores.risk_gold[i] = vals.reduce((a,b) => a+b, 0) / vals.length;
        }

        const totalWeight = Object.values(COMPONENT_WEIGHTS).reduce((a,b) => a+b, 0);
        const indexValues = new Array(n).fill(null);
        const contributions = {};
        for (const comp of Object.keys(COMPONENT_WEIGHTS)) contributions[comp] = new Array(n).fill(null);

        for (let i = 0; i < n; i++) {
            let weightedSum = 0, count = 0;
            for (const comp of Object.keys(COMPONENT_WEIGHTS)) {
                if (zScores[comp] && zScores[comp][i] != null) {
                    const signed = zScores[comp][i] * (SIGNS[comp] || 1);
                    const weighted = signed * COMPONENT_WEIGHTS[comp];
                    contributions[comp][i] = (weighted * -1) / totalWeight;
                    weightedSum += weighted; count++;
                }
            }
            if (count > 0) indexValues[i] = (weightedSum / totalWeight) * -1;
        }

        const periods = { '3M': 13, '1Y': 52, '5Y': 260 };
        const periodTraces = {};
        for (const [pName, weeks] of Object.entries(periods)) {
            const start = Math.max(0, n - weeks);
            const pDates = masterDates.slice(start);
            const pValues = rollingAvg(indexValues.slice(start), SMOOTH[pName]);
            periodTraces[pName] = { dates: pDates, values: pValues, pos: pValues.map(v => v != null && v > 0 ? v : 0), neg: pValues.map(v => v != null && v < 0 ? v : 0) };
        }

        const chartDiv = document.querySelector('.plotly-graph-div');
        const traces = chartDiv.data;
        const periodNames = ['3M', '1Y', '5Y'];
        for (let p = 0; p < 3; p++) {
            const pd = periodTraces[periodNames[p]], base = p * 3;
            traces[base].x = pd.dates; traces[base].y = pd.pos;
            traces[base + 1].x = pd.dates; traces[base + 1].y = pd.neg;
            traces[base + 2].x = pd.dates; traces[base + 2].y = pd.values;
        }

        const latestContribs = {}, prevContribs = {};
        for (const comp of Object.keys(COMPONENT_WEIGHTS)) { latestContribs[comp] = contributions[comp][n - 1]; prevContribs[comp] = contributions[comp][n - 2]; }
        const sortedComps = Object.keys(latestContribs).sort((a, b) => (latestContribs[a] || 0) - (latestContribs[b] || 0));
        traces[9].cells.values = [
            sortedComps.map(c => LABELS[c] || c),
            sortedComps.map(c => latestContribs[c] != null ? (latestContribs[c] >= 0 ? '+' : '') + latestContribs[c].toFixed(3) : 'N/A'),
            sortedComps.map(c => { const diff = (latestContribs[c] || 0) - (prevContribs[c] || 0); return (diff >= 0 ? '+' : '') + diff.toFixed(3); })
        ];
        traces[9].cells.fill.color = [
            sortedComps.map(c => { const v = latestContribs[c] || 0; return v > 0.02 ? 'rgba(46,125,50,0.3)' : v < -0.02 ? 'rgba(198,40,40,0.3)' : 'rgba(200,200,200,0.3)'; }),
            sortedComps.map(c => { const v = latestContribs[c] || 0; return v > 0.02 ? 'rgba(46,125,50,0.3)' : v < -0.02 ? 'rgba(198,40,40,0.3)' : 'rgba(200,200,200,0.3)'; }),
            sortedComps.map(c => { const v = latestContribs[c] || 0; return v > 0.02 ? 'rgba(46,125,50,0.3)' : v < -0.02 ? 'rgba(198,40,40,0.3)' : 'rgba(200,200,200,0.3)'; })
        ];

        const current = indexValues[n - 1], prev = indexValues[n - 2], dateStr = masterDates[n - 1];
        const layout = chartDiv.layout;
        layout.title.text = `Financial Conditions Index<br><sup>As of ${dateStr} | Current: ${current >= 0 ? '+' : ''}${current.toFixed(2)}\u03c3 | WoW: ${(current - prev) >= 0 ? '+' : ''}${(current - prev).toFixed(2)}\u03c3 | Green = Easing, Red = Tightening</sup>`;
        Plotly.react(chartDiv, traces, layout);

        const liveCount = fredResults.filter(r => r.status === 'fulfilled' && r.value).length;
        setStatus(`Updated ${new Date().toLocaleString()} | ${current >= 0 ? '+' : ''}${current.toFixed(2)}\u03c3 | ${liveCount} live series`, 'success');
    } catch (err) { setStatus('Error: ' + err.message, 'error'); console.error(err); }
    finally { setLoading(false); }
}
document.addEventListener('DOMContentLoaded', updateData);
