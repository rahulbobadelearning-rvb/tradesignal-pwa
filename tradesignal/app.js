'use strict';

/* ============================================================
   CONFIG
============================================================ */
const CORS_PROXIES = [
  'https://corsproxy.io/?',
  'https://api.allorigins.win/raw?url=',
];
const YF_BASE    = 'https://query1.finance.yahoo.com/v8/finance/chart/';
const YF_SEARCH  = 'https://query1.finance.yahoo.com/v1/finance/search';

/* ============================================================
   DATA FETCHING
============================================================ */
async function fetchJSON(url) {
  for (const proxy of CORS_PROXIES) {
    try {
      const res  = await fetch(proxy + encodeURIComponent(url));
      if (!res.ok) continue;
      const text = await res.text();
      return JSON.parse(text);
    } catch { /* try next proxy */ }
  }
  throw new Error('Could not reach market data. Check your connection and try again.');
}

async function fetchStockData(ticker) {
  const symbol = ticker.trim().toUpperCase();
  const url    = `${YF_BASE}${symbol}?interval=1d&range=6mo`;

  setLoadingMsg('Fetching price history…');
  const data = await fetchJSON(url);

  const result = data?.chart?.result?.[0];
  if (!result) throw new Error(`No data found for "${symbol}". Check the ticker symbol and try again.`);

  const meta    = result.meta || {};
  const ts      = result.timestamp || [];
  const q       = result.indicators?.quote?.[0] || {};

  const valid = ts
    .map((t, i) => ({ t, o: q.open?.[i], h: q.high?.[i], l: q.low?.[i], c: q.close?.[i], v: q.volume?.[i] }))
    .filter(d => d.c != null && !isNaN(d.c) && d.h != null && d.l != null);

  if (valid.length < 20) throw new Error(`Insufficient data for "${symbol}" (need ≥ 20 days).`);

  return {
    ticker:        symbol,
    name:          meta.shortName || meta.longName || symbol,
    currency:      meta.currency  || 'USD',
    currentPrice:  meta.regularMarketPrice || valid[valid.length - 1].c,
    previousClose: meta.previousClose || valid[valid.length - 2]?.c,
    week52High:    meta.fiftyTwoWeekHigh || meta['52WeekHigh'],
    week52Low:     meta.fiftyTwoWeekLow  || meta['52WeekLow'],
    opens:         valid.map(d => d.o),
    highs:         valid.map(d => d.h),
    lows:          valid.map(d => d.l),
    closes:        valid.map(d => d.c),
    volumes:       valid.map(d => d.v || 0),
    timestamps:    valid.map(d => d.t),
  };
}

/* ── Chart data (cached per period) ── */
const PERIOD_PARAMS = {
  '1D': 'interval=5m&range=1d',
  '1W': 'interval=60m&range=5d',
  '1M': 'interval=1d&range=1mo',
  '3M': 'interval=1d&range=3mo',
};

const chartCache = {};

async function fetchChartData(ticker, period) {
  const key = `${ticker}_${period}`;
  if (chartCache[key]) return chartCache[key];

  const url  = `${YF_BASE}${ticker}?${PERIOD_PARAMS[period]}`;
  const data = await fetchJSON(url);
  const result = data?.chart?.result?.[0];
  if (!result) return null;

  const ts = result.timestamp || [];
  const q  = result.indicators?.quote?.[0] || {};
  const valid = ts
    .map((t, i) => ({ t, o: q.open?.[i], h: q.high?.[i], l: q.low?.[i], c: q.close?.[i], v: q.volume?.[i] }))
    .filter(d => d.c != null && !isNaN(d.c));

  const cd = {
    opens:      valid.map(d => d.o || d.c),
    highs:      valid.map(d => d.h || d.c),
    lows:       valid.map(d => d.l || d.c),
    closes:     valid.map(d => d.c),
    timestamps: valid.map(d => d.t),
    volumes:    valid.map(d => d.v || 0),
  };
  chartCache[key] = cd;
  return cd;
}

/* ── Autocomplete search ── */
let suggestTimer = null;

async function fetchSuggestions(query) {
  const q = query.trim();
  if (q.length < 1) { hideSuggestions(); return; }

  const url = `${YF_SEARCH}?q=${encodeURIComponent(q)}&quotesCount=6&newsCount=0&enableFuzzyQuery=true&region=US`;
  try {
    const data = await fetchJSON(url);
    const quotes = (data.quotes || [])
      .filter(r => r.quoteType === 'EQUITY' || r.quoteType === 'ETF' || r.quoteType === 'INDEX')
      .slice(0, 5);
    showSuggestions(quotes);
  } catch { hideSuggestions(); }
}

function showSuggestions(quotes) {
  const el = document.getElementById('suggestions');
  if (!quotes.length) { hideSuggestions(); return; }
  el.innerHTML = quotes.map(q => `
    <div class="sug-item" onmousedown="selectSuggestion('${q.symbol}')">
      <span class="sug-sym">${q.symbol}</span>
      <span class="sug-name">${q.shortname || q.longname || ''}</span>
      <span class="sug-exch">${q.exchange || ''}</span>
    </div>`).join('');
  el.classList.remove('hidden');
}

function hideSuggestions() {
  document.getElementById('suggestions').classList.add('hidden');
}

window.selectSuggestion = function(symbol) {
  document.getElementById('ticker-input').value = symbol;
  hideSuggestions();
  analyze(symbol);
};

/* ============================================================
   MATH HELPERS
============================================================ */
function ema(data, period) {
  const k = 2 / (period + 1);
  const out = [];
  let prev = null;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1)      { out.push(null); }
    else if (i === period - 1){ prev = data.slice(0, period).reduce((a, b) => a + b, 0) / period; out.push(prev); }
    else                      { prev = data[i] * k + prev * (1 - k); out.push(prev); }
  }
  return out;
}

function smaLast(data, period) {
  if (data.length < period) return null;
  return data.slice(-period).reduce((a, b) => a + b, 0) / period;
}

function calcRSI(closes, period = 14) {
  if (closes.length < period + 1) return null;
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) avgGain += d; else avgLoss -= d;
  }
  avgGain /= period; avgLoss /= period;
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d,  0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
  }
  if (avgLoss === 0) return 100;
  return 100 - 100 / (1 + avgGain / avgLoss);
}

function calcMACD(closes) {
  const e12 = ema(closes, 12);
  const e26 = ema(closes, 26);
  const macdLine = e12.map((v, i) => v !== null && e26[i] !== null ? v - e26[i] : null);
  const validVals = macdLine.filter(v => v !== null);
  if (validVals.length < 9) return { value: null, signal: null, histogram: null, isBullish: null };
  const sigPartial = ema(validVals, 9);
  let j = 0;
  const sigLine = macdLine.map(v => v !== null ? sigPartial[j++] : null);
  const last = macdLine.length - 1;
  const mv = macdLine[last], sv = sigLine[last];
  return { value: mv, signal: sv,
    histogram: mv !== null && sv !== null ? mv - sv : null,
    isBullish: mv !== null && sv !== null ? mv > sv : null };
}

/* ============================================================
   SUPPORT & RESISTANCE
============================================================ */
function findSwings(highs, lows, n = 2) {
  const swingH = [], swingL = [];
  for (let i = n; i < highs.length - n; i++) {
    let isH = true, isL = true;
    for (let j = 1; j <= n; j++) {
      if (highs[i] <= highs[i-j] || highs[i] <= highs[i+j]) isH = false;
      if (lows[i]  >= lows[i-j]  || lows[i]  >= lows[i+j])  isL = false;
    }
    if (isH) swingH.push(highs[i]);
    if (isL) swingL.push(lows[i]);
  }
  return { swingH, swingL };
}

function clusterLevels(levels, pct = 0.005) {
  if (!levels.length) return [];
  const sorted = [...levels].sort((a, b) => a - b);
  const clusters = [[sorted[0]]];
  for (let i = 1; i < sorted.length; i++) {
    const g = clusters[clusters.length - 1];
    const avg = g.reduce((a, b) => a + b, 0) / g.length;
    if (Math.abs(sorted[i] - avg) / avg <= pct) g.push(sorted[i]);
    else clusters.push([sorted[i]]);
  }
  return clusters.map(c => ({ level: c.reduce((a, b) => a + b, 0) / c.length, strength: c.length }));
}

function weeklyPivot(high, low, close) {
  const P = (high + low + close) / 3;
  return { R2: P + (high - low), R1: 2*P - low, P, S1: 2*P - high, S2: P - (high - low) };
}

function findSR(stock) {
  const { highs, lows, closes, currentPrice } = stock;
  const n  = Math.min(60, highs.length);
  const rH = highs.slice(-n), rL = lows.slice(-n);
  const pivots = weeklyPivot(Math.max(...rH.slice(-5)), Math.min(...rL.slice(-5)), closes[closes.length-1]);
  const { swingH, swingL } = findSwings(rH, rL);
  const cH = clusterLevels(swingH), cL = clusterLevels(swingL);
  const resCands = [], supCands = [];
  cH.filter(l => l.level > currentPrice * 1.001).forEach(l => resCands.push({ ...l, source: 'swing' }));
  cL.filter(l => l.level < currentPrice * 0.999).forEach(l => supCands.push({ ...l, source: 'swing' }));
  [pivots.R1, pivots.R2].filter(v => v > currentPrice).forEach(v => resCands.push({ level: v, strength: 1, source: 'pivot' }));
  [pivots.S1, pivots.S2].filter(v => v < currentPrice).forEach(v => supCands.push({ level: v, strength: 1, source: 'pivot' }));
  const finalRes = clusterLevels(resCands.map(l => l.level)).sort((a, b) => a.level - b.level).slice(0, 2);
  const finalSup = clusterLevels(supCands.map(l => l.level)).sort((a, b) => b.level - a.level).slice(0, 2);
  return { resistances: finalRes, supports: finalSup, pivots };
}

/* ============================================================
   SENTIMENT
============================================================ */
function calcSentiment(stock) {
  const { closes, volumes, week52High, week52Low, currentPrice } = stock;
  const rsiVal   = calcRSI(closes);
  const rsiScore = rsiVal == null ? 50 : rsiVal > 70 ? 82 : rsiVal > 60 ? 70 : rsiVal < 30 ? 18 : rsiVal < 40 ? 30 : 50;
  const macdData  = calcMACD(closes);
  const macdScore = macdData.isBullish == null ? 50 : macdData.isBullish ? 72 : 28;
  const sma50val  = smaLast(closes, 50);
  const smaScore  = sma50val == null ? 50 : currentPrice > sma50val ? 70 : 30;
  const vol5  = volumes.slice(-5).reduce((a, b) => a + b, 0) / 5;
  const vol20 = volumes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const upDays = closes.slice(-5).filter((c, i, a) => i > 0 && c > a[i-1]).length;
  const volScore = (vol5 > vol20 * 1.1 && upDays >= 3) ? 72 : (vol5 < vol20 * 0.9 && upDays <= 1) ? 28 : 50;
  const range52  = (week52High || 0) - (week52Low || 0);
  const pos52pct = range52 > 0 ? (currentPrice - (week52Low || 0)) / range52 * 100 : 50;
  const score = Math.round(rsiScore*0.30 + macdScore*0.25 + smaScore*0.20 + volScore*0.15 + pos52pct*0.10);
  const bias  = score >= 56 ? 'Bullish' : score <= 35 ? 'Bearish' : 'Neutral';
  let confidence;
  if      (bias === 'Bullish') confidence = Math.min(95, Math.round(30 + (score - 56) / 44 * 65));
  else if (bias === 'Bearish') confidence = Math.min(95, Math.round(30 + (35 - score) / 35 * 65));
  else                         confidence = Math.max(35, 65 - Math.abs(score - 45) * 3);
  return { score, bias, confidence, rsi: rsiVal, macd: macdData, sma50: sma50val,
           volRatio: vol20 > 0 ? vol5/vol20 : 1, pos52pct: Math.round(pos52pct) };
}

/* ============================================================
   OPTIONS SIGNAL
============================================================ */
function getOptionsSignal(sentiment, sr, currentPrice) {
  const { bias, rsi: rsiVal, macd: macdData } = sentiment;
  const { supports, resistances } = sr;
  const nearRes = resistances.length > 0 && Math.abs(currentPrice - resistances[0].level) / currentPrice < 0.025;
  const nearSup = supports.length    > 0 && Math.abs(currentPrice - supports[0].level)    / currentPrice < 0.025;
  if (rsiVal !== null && rsiVal < 35 && macdData.isBullish)
    return { type:'calls', signal:'Consider Calls', icon:'📈',
             reason:`Oversold bounce setup — RSI at ${rsiVal.toFixed(1)} (below 35) with MACD crossing bullish.` };
  if (rsiVal !== null && rsiVal > 65 && !macdData.isBullish)
    return { type:'puts', signal:'Consider Puts', icon:'📉',
             reason:`Overbought pullback setup — RSI at ${rsiVal.toFixed(1)} (above 65) with MACD crossing bearish.` };
  if (nearRes && bias !== 'Bullish')
    return { type:'puts', signal:'Consider Puts / Covered Calls', icon:'🔻',
             reason:`Price testing resistance near $${fmt(resistances[0].level)}. Watch for a rejection before entering.` };
  if (nearSup && bias !== 'Bearish')
    return { type:'calls', signal:'Consider Calls / Cash-Secured Puts', icon:'🔺',
             reason:`Price holding at support near $${fmt(supports[0].level)}. Look for a confirmed bounce before entering.` };
  if (bias === 'Bullish' && (rsiVal === null || rsiVal < 65))
    return { type:'calls', signal:'Lean Calls', icon:'↗️',
             reason:`Bullish momentum with no extreme readings. Consider waiting for a pullback to the nearest support for a better entry.` };
  if (bias === 'Bearish' && (rsiVal === null || rsiVal > 35))
    return { type:'puts', signal:'Lean Puts', icon:'↘️',
             reason:`Bearish momentum with room to move lower. Consider waiting for a bounce to resistance before entering puts.` };
  return { type:'neutral', signal:'Wait for Clearer Setup', icon:'⏳',
           reason:`Mixed signals — no strong confluence yet. Patience is the edge. Re-check when price approaches a key level.` };
}

/* ============================================================
   CHART
============================================================ */
let activeChart = { ticker: '', period: '1M', sr: null, type: 'line' };

function switchChartType(type) {
  document.querySelectorAll('.chart-type-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.type === type));
  activeChart.type = type;
  const key = `${activeChart.ticker}_${activeChart.period}`;
  if (chartCache[key]) drawChart(chartCache[key], activeChart.sr);
}

async function switchPeriod(period) {
  document.querySelectorAll('.period-btn').forEach(b => b.classList.toggle('active', b.dataset.period === period));
  activeChart.period = period;

  const canvas = document.getElementById('price-chart');
  canvas.style.opacity = '0.4';

  try {
    const cd = await fetchChartData(activeChart.ticker, period);
    if (cd) drawChart(cd, activeChart.sr);
  } catch { /* keep existing chart */ } finally {
    canvas.style.opacity = '1';
  }
}

function drawChart(cd, sr) {
  const canvas  = document.getElementById('price-chart');
  const tooltip = document.getElementById('chart-tooltip');
  const { closes, timestamps, volumes } = cd;
  const opens = cd.opens || closes;
  const highs = cd.highs || closes;
  const lows  = cd.lows  || closes;

  const dpr = window.devicePixelRatio || 1;
  const W   = canvas.parentElement.clientWidth;
  const H   = 210;
  canvas.width  = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const PAD_L = 6, PAD_R = 56, PAD_T = 14, PAD_B = 28, VOL_H = 26;
  const cW = W - PAD_L - PAD_R;
  const cH = H - PAD_T - PAD_B - VOL_H - 4;

  const minC = Math.min(...lows), maxC = Math.max(...highs);
  const priceSpan = maxC - minC || 1;
  const maxV = Math.max(...volumes) || 1;

  const toX  = i => PAD_L + (i / Math.max(closes.length - 1, 1)) * cW;
  const toY  = v => PAD_T + (1 - (v - minC) / priceSpan) * cH;
  const toVY = v => H - PAD_B - (v / maxV) * VOL_H;

  const isUp   = closes[closes.length - 1] >= closes[0];
  const lColor = isUp ? '#00d4aa' : '#ff4b4b';
  const period = activeChart.period;

  ctx.fillStyle = '#141b2d';
  ctx.fillRect(0, 0, W, H);

  ctx.strokeStyle = 'rgba(255,255,255,0.04)'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = PAD_T + (i / 4) * cH;
    ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y); ctx.stroke();
  }

  if (sr) {
    [...sr.resistances.map(l => ({ ...l, isRes: true })),
     ...sr.supports   .map(l => ({ ...l, isRes: false }))].forEach(l => {
      const y = toY(l.level);
      if (y < PAD_T - 4 || y > PAD_T + cH + 4) return;
      ctx.setLineDash([3, 4]); ctx.lineWidth = 1;
      ctx.strokeStyle = l.isRes ? 'rgba(255,75,75,0.5)' : 'rgba(0,212,170,0.5)';
      ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(W - PAD_R, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = l.isRes ? '#ff4b4b' : '#00d4aa';
      ctx.font = 'bold 9px system-ui,sans-serif'; ctx.textAlign = 'left';
      ctx.fillText('$' + l.level.toFixed(0), W - PAD_R + 5, y + 3);
    });
  }

  if (activeChart.type === 'candle') {
    const barW = Math.max(2, (cW / closes.length) * 0.7);
    for (let i = 0; i < closes.length; i++) {
      const x = toX(i), bull = closes[i] >= opens[i];
      const color = bull ? '#00d4aa' : '#ff4b4b';
      ctx.strokeStyle = color; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, toY(highs[i])); ctx.lineTo(x, toY(lows[i])); ctx.stroke();
      const bodyTop = toY(Math.max(opens[i], closes[i]));
      const bodyH   = Math.max(1, toY(Math.min(opens[i], closes[i])) - bodyTop);
      ctx.fillStyle = bull ? 'rgba(0,212,170,0.85)' : 'rgba(255,75,75,0.85)';
      ctx.fillRect(x - barW / 2, bodyTop, barW, bodyH);
    }
  } else {
    const grad = ctx.createLinearGradient(0, PAD_T, 0, PAD_T + cH);
    grad.addColorStop(0,   isUp ? 'rgba(0,212,170,0.22)' : 'rgba(255,75,75,0.22)');
    grad.addColorStop(0.8, 'rgba(0,0,0,0)');
    ctx.beginPath(); ctx.moveTo(toX(0), toY(closes[0]));
    for (let i = 1; i < closes.length; i++) ctx.lineTo(toX(i), toY(closes[i]));
    ctx.lineTo(toX(closes.length - 1), PAD_T + cH);
    ctx.lineTo(toX(0), PAD_T + cH); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath(); ctx.moveTo(toX(0), toY(closes[0]));
    for (let i = 1; i < closes.length; i++) ctx.lineTo(toX(i), toY(closes[i]));
    ctx.strokeStyle = lColor; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
  }

  const volBarW = Math.max(1, cW / closes.length - 0.5);
  ctx.globalAlpha = 0.3;
  for (let i = 0; i < closes.length; i++) {
    ctx.fillStyle = (i > 0 && closes[i] >= closes[i - 1]) ? '#00d4aa' : '#ff4b4b';
    ctx.fillRect(toX(i) - volBarW / 2, toVY(volumes[i]), volBarW, (volumes[i] / maxV) * VOL_H);
  }
  ctx.globalAlpha = 1;

  ctx.fillStyle = 'rgba(255,255,255,0.3)'; ctx.font = '9px system-ui,sans-serif'; ctx.textAlign = 'left';
  for (let i = 0; i <= 3; i++) {
    const v = minC + priceSpan * (1 - i / 3);
    ctx.fillText('$' + v.toFixed(0), W - PAD_R + 5, PAD_T + (i / 3) * cH + 3);
  }

  ctx.fillStyle = 'rgba(255,255,255,0.22)'; ctx.textAlign = 'center';
  for (let i = 0; i < 4; i++) {
    const idx = Math.round(i / 3 * (timestamps.length - 1));
    const dt  = new Date(timestamps[idx] * 1000);
    let lbl;
    if (period === '1D')      lbl = dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
    else if (period === '1W') lbl = dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    else                      lbl = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    ctx.fillText(lbl, toX(idx), H - PAD_B + 13);
  }

  canvas._chart = { opens, highs, lows, closes, timestamps, toX, toY, cH, PAD_T, PAD_L, PAD_R, cW, W, H, lColor, type: activeChart.type, period };

  // Update header % change to reflect selected period
  const periodChg = (closes[closes.length - 1] - closes[0]) / closes[0] * 100;
  const chgEl = document.getElementById('res-change');
  if (chgEl) {
    const labels = { '1D': '1D', '1W': '1W', '1M': '1M', '3M': '3M' };
    chgEl.textContent = `${periodChg >= 0 ? '+' : ''}${periodChg.toFixed(2)}% (${labels[period] || period})`;
    chgEl.className = 'stock-change ' + (periodChg >= 0 ? 'positive' : 'negative');
  }
  canvas.onmousemove  = e => showChartTip(e.clientX, canvas, tooltip);
  canvas.onmouseleave = () => { tooltip.classList.add('hidden'); drawChart(cd, sr); };
  canvas.ontouchmove  = e => { e.preventDefault(); showChartTip(e.touches[0].clientX, canvas, tooltip); };
  canvas.ontouchend   = () => tooltip.classList.add('hidden');
}

function showChartTip(clientX, canvas, tooltip) {
  const d = canvas._chart;
  if (!d) return;
  const rect = canvas.getBoundingClientRect();
  const x    = clientX - rect.left;
  const { opens, highs, lows, closes, timestamps, toX, toY, cH, PAD_T, PAD_L, PAD_R, cW, W, H, lColor, type, period } = d;
  const idx = Math.max(0, Math.min(closes.length - 1, Math.round((x - PAD_L) / cW * (closes.length - 1))));
  const cx  = toX(idx), cy = toY(closes[idx]);

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  ctx.save(); ctx.scale(dpr, dpr);
  ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(cx, PAD_T); ctx.lineTo(cx, PAD_T + cH); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = lColor; ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fill();
  ctx.restore();

  const dt = new Date(timestamps[idx] * 1000);
  const dateStr = period === '1D'
    ? dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
    : dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  if (type === 'candle') {
    const bull = closes[idx] >= opens[idx];
    const c    = bull ? '#00d4aa' : '#ff4b4b';
    tooltip.innerHTML = `<span style="color:${c};font-weight:800">C $${closes[idx].toFixed(2)}</span> <span style="color:rgba(255,255,255,0.5)">O $${opens[idx].toFixed(2)}</span><br><span style="color:#00d4aa">H $${highs[idx].toFixed(2)}</span> <span style="color:#ff4b4b">L $${lows[idx].toFixed(2)}</span><br><span style="color:rgba(255,255,255,0.45)">${dateStr}</span>`;
  } else {
    tooltip.innerHTML = `<span style="color:${lColor};font-weight:800">$${closes[idx].toFixed(2)}</span><br><span>${dateStr}</span>`;
  }
  tooltip.classList.remove('hidden');
  tooltip.style.left = Math.max(4, Math.min(cx + 8, W - 115)) + 'px';
  tooltip.style.top  = Math.max(4, cy - 46) + 'px';
}

/* ============================================================
   RENDERING
============================================================ */
function fmt(num) {
  if (num == null || isNaN(num)) return '—';
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderStockHeader(stock) {
  document.getElementById('res-ticker').textContent = stock.ticker;
  document.getElementById('res-name').textContent   = stock.name;
  const price = stock.currentPrice, prev = stock.previousClose;
  const chg   = prev ? (price - prev) / prev * 100 : 0;
  document.getElementById('res-price').textContent  = `$${fmt(price)}`;
  const el = document.getElementById('res-change');
  el.textContent = `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`;
  el.className   = 'stock-change ' + (chg >= 0 ? 'positive' : 'negative');
}

function renderPriceLadder(sr, currentPrice) {
  const { supports, resistances } = sr;
  const rows = [
    ...resistances.slice().reverse().map((l, i) => ({ ...l, type:'resistance', label:`R${resistances.length - i}` })),
    { level: currentPrice, type:'cur-price', label:'NOW', strength:0 },
    ...supports.map((l, i) => ({ ...l, type:'support', label:`S${i+1}` })),
  ];
  const maxDist = Math.max(1, ...rows.filter(r => r.type !== 'cur-price').map(r => Math.abs(r.level - currentPrice)));
  document.getElementById('sr-ladder').innerHTML = rows.map(row => {
    if (row.type === 'cur-price') return `
      <div class="ladder-row cur-price">
        <span class="ladder-label">NOW</span>
        <div class="ladder-bar-wrap"><div class="ladder-bar" style="width:0"></div></div>
        <span class="ladder-price">$${fmt(row.level)}</span>
        <span class="ladder-dist">current</span>
        <div class="ladder-dots"></div>
      </div>`;
    const dist    = Math.abs(row.level - currentPrice);
    const distPct = (dist / currentPrice * 100).toFixed(2);
    const barPct  = Math.round(dist / maxDist * 100);
    const arrow   = row.type === 'resistance' ? '↑' : '↓';
    const dots    = [1,2,3].map(i => `<div class="dot${i <= Math.min(row.strength,3) ? ' on':''}"></div>`).join('');
    return `
      <div class="ladder-row ${row.type}">
        <span class="ladder-label">${row.label}</span>
        <div class="ladder-bar-wrap"><div class="ladder-bar" style="width:${barPct}%"></div></div>
        <span class="ladder-price">$${fmt(row.level)}</span>
        <span class="ladder-dist">${arrow}${distPct}%</span>
        <div class="ladder-dots">${dots}</div>
      </div>`;
  }).join('');
}

function describeArc(cx, cy, r, s, e) {
  const toRad = a => (a - 90) * Math.PI / 180;
  const x1 = cx + r*Math.cos(toRad(s)), y1 = cy + r*Math.sin(toRad(s));
  const x2 = cx + r*Math.cos(toRad(e)), y2 = cy + r*Math.sin(toRad(e));
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${e-s>180?1:0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

function renderSentiment(sentiment) {
  const { score, bias, confidence } = sentiment;
  const nr  = (-150 + score/100*300) * Math.PI/180;
  const cx  = 72, cy = 72, r = 52;
  const nx  = (cx + r*Math.sin(nr)).toFixed(2);
  const ny  = (cy - r*Math.cos(nr)).toFixed(2);
  const bColor = bias === 'Bullish' ? '#00d4aa' : bias === 'Bearish' ? '#ff4b4b' : '#f0b429';
  document.getElementById('sentiment-gauge').innerHTML = `
    <svg width="144" height="92" viewBox="0 0 144 92" fill="none">
      <path d="${describeArc(72,72,52,-60,240)}" stroke="rgba(255,255,255,.06)" stroke-width="9" stroke-linecap="round" fill="none"/>
      <path d="${describeArc(72,72,52,-60,45)}"  stroke="#ff4b4b" stroke-width="9" stroke-linecap="round" fill="none" opacity=".45"/>
      <path d="${describeArc(72,72,52,45,113)}"  stroke="#f0b429" stroke-width="9" stroke-linecap="round" fill="none" opacity=".45"/>
      <path d="${describeArc(72,72,52,113,240)}" stroke="#00d4aa" stroke-width="9" stroke-linecap="round" fill="none" opacity=".45"/>
      <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="${bColor}" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="4.5" fill="${bColor}"/>
      <text x="${cx}" y="86" text-anchor="middle" fill="rgba(255,255,255,.35)" font-size="10" font-family="system-ui">${score}/100</text>
    </svg>`;
  const biasEl = document.getElementById('sentiment-bias');
  biasEl.textContent = bias;
  biasEl.className   = 'bias-label ' + bias.toLowerCase();
  document.getElementById('sentiment-detail').textContent = `${confidence}% confidence · 4-week outlook`;
  const bar = document.getElementById('sentiment-bar');
  bar.style.width = score + '%'; bar.style.background = bColor;
}

function renderOptionsSignal(signal) {
  const card = document.getElementById('options-card');
  const cls  = signal.type === 'calls' ? 'calls' : signal.type === 'puts' ? 'puts' : 'neutral-sig';
  card.className = `card signal-card ${cls}`;
  card.innerHTML = `
    <p class="card-title">Options Signal</p>
    <span class="signal-icon">${signal.icon}</span>
    <div class="signal-name">${signal.signal}</div>
    <p class="signal-reason">${signal.reason}</p>`;
}

function renderIndicators(sentiment) {
  const { rsi: rsiVal, macd: macdData, volRatio, pos52pct } = sentiment;
  const rsiBadge  = rsiVal == null ? 'neutral-badge' : rsiVal > 70 ? 'bear-badge' : rsiVal < 30 ? 'bull-badge' : rsiVal > 55 ? 'bull-badge' : rsiVal < 45 ? 'bear-badge' : 'neutral-badge';
  const rsiLabel  = rsiVal == null ? '—' : rsiVal > 70 ? 'Overbought' : rsiVal > 60 ? 'Strong' : rsiVal < 30 ? 'Oversold' : rsiVal < 40 ? 'Weak' : 'Neutral';
  const macdBadge = macdData.isBullish == null ? 'neutral-badge' : macdData.isBullish ? 'bull-badge' : 'bear-badge';
  const macdLabel = macdData.isBullish == null ? '—' : macdData.isBullish ? 'Bullish' : 'Bearish';
  const macdDisp  = macdData.value == null ? '—' : (macdData.value > 0 ? '+' : '') + macdData.value.toFixed(2);
  const volBadge  = volRatio > 1.2 ? 'bull-badge' : volRatio < 0.8 ? 'bear-badge' : 'neutral-badge';
  const volLabel  = volRatio > 1.2 ? 'Rising' : volRatio < 0.8 ? 'Declining' : 'Average';
  const posBadge  = pos52pct > 70 ? 'bull-badge' : pos52pct < 30 ? 'bear-badge' : 'neutral-badge';
  const posLabel  = pos52pct > 70 ? 'Near High' : pos52pct < 30 ? 'Near Low' : 'Mid-Range';
  document.getElementById('indicators-grid').innerHTML = `
    <div class="indicator-item">
      <div class="ind-label">RSI (14)</div>
      <div class="ind-value">${rsiVal != null ? rsiVal.toFixed(1) : '—'}</div>
      <span class="ind-badge ${rsiBadge}">${rsiLabel}</span>
    </div>
    <div class="indicator-item">
      <div class="ind-label">MACD (12,26,9)</div>
      <div class="ind-value">${macdDisp}</div>
      <span class="ind-badge ${macdBadge}">${macdLabel}</span>
    </div>
    <div class="indicator-item">
      <div class="ind-label">Volume Trend</div>
      <div class="ind-value">${volRatio.toFixed(2)}x</div>
      <span class="ind-badge ${volBadge}">${volLabel}</span>
    </div>
    <div class="indicator-item">
      <div class="ind-label">52-Wk Position</div>
      <div class="ind-value">${pos52pct}%</div>
      <span class="ind-badge ${posBadge}">${posLabel}</span>
    </div>`;
}

/* ============================================================
   STATE MACHINE
============================================================ */
function setView(view) {
  ['welcome','loading','error','results'].forEach(v =>
    document.getElementById(v + '-state').classList.toggle('hidden', v !== view));
}

function setLoadingMsg(msg) {
  const el = document.getElementById('loading-msg');
  if (el) el.textContent = msg;
}

/* ============================================================
   MAIN ANALYSIS FLOW
============================================================ */
let lastTicker = '';

async function analyze(ticker) {
  const t = ticker.trim().toUpperCase();
  if (!t) return;
  lastTicker = t;
  hideSuggestions();
  setView('loading');
  setLoadingMsg('Connecting to market data…');

  try {
    const stock     = await fetchStockData(t);
    setLoadingMsg('Calculating indicators…');

    const sr        = findSR(stock);
    const sentiment = calcSentiment(stock);
    const signal    = getOptionsSignal(sentiment, sr, stock.currentPrice);

    // Seed 3M cache from fetched data; derive 1M by slicing last ~21 trading days
    const cut1M = Date.now() / 1000 - 31 * 24 * 3600;
    const i1M   = stock.timestamps.findIndex(ts => ts >= cut1M);
    const sl    = (arr, i) => arr.slice(i >= 0 ? i : 0);
    chartCache[`${t}_3M`] = { opens: stock.opens, highs: stock.highs, lows: stock.lows, closes: stock.closes, timestamps: stock.timestamps, volumes: stock.volumes };
    chartCache[`${t}_1M`] = { opens: sl(stock.opens, i1M), highs: sl(stock.highs, i1M), lows: sl(stock.lows, i1M), closes: sl(stock.closes, i1M), timestamps: sl(stock.timestamps, i1M), volumes: sl(stock.volumes, i1M) };

    // Reset chart state
    activeChart.ticker = t;
    activeChart.period = '1M';
    activeChart.sr     = sr;
    document.querySelectorAll('.period-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.period === '1M'));

    renderStockHeader(stock);
    drawChart(chartCache[`${t}_1M`], sr);
    renderPriceLadder(sr, stock.currentPrice);
    renderSentiment(sentiment);
    renderOptionsSignal(signal);
    renderIndicators(sentiment);

    setView('results');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) {
    document.getElementById('error-msg').textContent = err.message;
    // Show search suggestions on error
    try {
      const data = await fetchJSON(`${YF_SEARCH}?q=${encodeURIComponent(lastTicker)}&quotesCount=4&newsCount=0&region=US`);
      const quotes = (data.quotes || []).filter(r => r.quoteType === 'EQUITY' || r.quoteType === 'ETF').slice(0, 4);
      const wrap = document.getElementById('error-suggestions');
      if (quotes.length) {
        wrap.innerHTML = '<p class="err-sug-label">Did you mean?</p>' +
          quotes.map(q => `<button class="err-sug-btn" onclick="quickSearch('${q.symbol}')">${q.symbol} — ${q.shortname || q.longname || ''}</button>`).join('');
        wrap.classList.remove('hidden');
      }
    } catch { /* no suggestions */ }
    setView('error');
  }
}

function retryLast() { if (lastTicker) analyze(lastTicker); }

/* ============================================================
   PWA INSTALL PROMPT
============================================================ */
let deferredInstall = null;
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); deferredInstall = e;
  document.getElementById('install-banner').classList.remove('hidden');
});
window.addEventListener('appinstalled', () => {
  document.getElementById('install-banner').classList.add('hidden');
  deferredInstall = null;
});

/* ============================================================
   INIT
============================================================ */
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('ticker-input');
  const btn   = document.getElementById('search-btn');

  btn.addEventListener('click', () => analyze(input.value));
  input.addEventListener('keydown', e => { if (e.key === 'Enter') analyze(input.value); });

  // Autocomplete
  input.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    suggestTimer = setTimeout(() => fetchSuggestions(input.value), 280);
  });
  input.addEventListener('blur', () => { setTimeout(hideSuggestions, 150); });

  // Period tabs
  document.getElementById('period-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.period-btn');
    if (btn && activeChart.ticker) switchPeriod(btn.dataset.period);
  });

  // Chart type tabs
  document.getElementById('chart-type-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.chart-type-btn');
    if (btn && activeChart.ticker) switchChartType(btn.dataset.type);
  });

  // Install banner
  document.getElementById('install-btn').addEventListener('click', async () => {
    if (deferredInstall) { await deferredInstall.prompt(); deferredInstall = null; }
    document.getElementById('install-banner').classList.add('hidden');
  });
  document.getElementById('dismiss-install').addEventListener('click', () =>
    document.getElementById('install-banner').classList.add('hidden'));

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(() => {});
  setView('welcome');
});

window.quickSearch = function(ticker) {
  document.getElementById('ticker-input').value = ticker;
  analyze(ticker);
};
