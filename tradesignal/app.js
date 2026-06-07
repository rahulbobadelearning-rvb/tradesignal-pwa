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
  const url    = `${YF_BASE}${symbol}?interval=1d&range=1y`;

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

/* ── Chart data (cached per period + interval) ── */
const AUTO_INTERVAL     = { '1D':'5m',  '1W':'60m', '1M':'1d', '3M':'1d', 'YTD':'1d', '1Y':'1d' };
const PERIOD_RANGE      = { '1D':'1d',  '1W':'5d',  '1M':'1mo','3M':'3mo','YTD':'ytd','1Y':'1y'  };
const PERIOD_DAYS       = { '1D':1, '1W':7, '1M':31, '3M':92, 'YTD':365, '1Y':365 };
const INTERVAL_MAX_DAYS = { '1m':7, '5m':60, '15m':60, '30m':60, '60m':730, '1d':3650 };

const chartCache = {};

async function fetchChartData(ticker, period, interval) {
  const iv  = interval || AUTO_INTERVAL[period] || '1d';
  const key = `${ticker}_${period}_${iv}`;
  if (chartCache[key]) return chartCache[key];

  const url  = `${YF_BASE}${ticker}?interval=${iv}&range=${PERIOD_RANGE[period] || '1mo'}`;
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
  const ema200arr = ema(closes, 200);
  const ema200val = [...ema200arr].reverse().find(v => v !== null) ?? null;
  return { score, bias, confidence, rsi: rsiVal, macd: macdData, sma50: sma50val,
           volRatio: vol20 > 0 ? vol5/vol20 : 1, pos52pct: Math.round(pos52pct),
           ema200: ema200val, currentPrice };
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
const CHART_COLORS = {
  ema20:   '#f0b429',
  ema50:   '#7ecbff',
  ema200:  '#ff7f50',
  bbUpper: '#9b59b6',
  bbMid:   'rgba(155,89,182,0.5)',
  bbLower: '#9b59b6',
};

let activeChart         = { ticker: '', period: '1M', sr: null, type: 'line', stock: null, interval: null };
const activeIndicators  = { ema20: true, ema50: true, ema200: false, bb: false };
const indicatorSettings = { ema20: 20, ema50: 50, ema200: 200, bbPeriod: 20, bbMult: 2 };
let lwChart            = null;
let lwMainSeries       = null;
let lwBuyVolSeries     = null;
let lwSellVolSeries    = null;
const lwInd            = {};

function calcBB(closes, period = 20, mult = 2) {
  return closes.map((_, i) => {
    if (i < period - 1) return null;
    const sl   = closes.slice(i - period + 1, i + 1);
    const mean = sl.reduce((a, b) => a + b, 0) / period;
    const std  = Math.sqrt(sl.reduce((a, b) => a + (b - mean) ** 2, 0) / period);
    return { mid: mean, upper: mean + mult * std, lower: mean - mult * std };
  });
}

function tsToDay(ts) {
  const d = new Date(ts * 1000);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`;
}

function addIndSeries(color, lineWidth = 1.5, lineStyle = 0) {
  return lwChart.addLineSeries({
    color, lineWidth, lineStyle,
    lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
  });
}

function applyIndicatorVisibility() {
  lwInd.ema20?.applyOptions({ visible: activeIndicators.ema20 });
  lwInd.ema50?.applyOptions({ visible: activeIndicators.ema50 });
  lwInd.ema200?.applyOptions({ visible: activeIndicators.ema200 });
  lwInd.bbUpper?.applyOptions({ visible: activeIndicators.bb });
  lwInd.bbMid?.applyOptions({ visible: activeIndicators.bb });
  lwInd.bbLower?.applyOptions({ visible: activeIndicators.bb });
}

function toggleIndicator(name) {
  activeIndicators[name] = !activeIndicators[name];
  document.querySelectorAll('.pill').forEach(p => {
    if (p.dataset.ind === name) p.classList.toggle('active', activeIndicators[name]);
  });
  applyIndicatorVisibility();
}

function destroyLwChart() {
  if (lwChart) { lwChart.remove(); lwChart = null; }
  lwMainSeries = null; lwBuyVolSeries = null; lwSellVolSeries = null;
  Object.keys(lwInd).forEach(k => delete lwInd[k]);
}

function switchChartType(type) {
  document.querySelectorAll('.chart-type-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.type === type));
  activeChart.type = type;
  const iv  = activeChart.interval || AUTO_INTERVAL[activeChart.period] || '1d';
  const key = `${activeChart.ticker}_${activeChart.period}_${iv}`;
  if (chartCache[key]) drawChart(chartCache[key], activeChart.sr);
}

function switchInterval(interval) {
  document.querySelectorAll('.ipill').forEach(b =>
    b.classList.toggle('active', b.dataset.int === interval));
  activeChart.interval = interval === 'auto' ? null : interval;

  // Auto-adjust period if incompatible with chosen interval
  if (activeChart.interval) {
    const maxDays = INTERVAL_MAX_DAYS[activeChart.interval] || 3650;
    if ((PERIOD_DAYS[activeChart.period] || 31) > maxDays) {
      const best = activeChart.interval === '1m' ? '1D' : '1M';
      switchPeriod(best);
      return;
    }
  }

  if (!activeChart.ticker) return;
  const iv  = activeChart.interval || AUTO_INTERVAL[activeChart.period] || '1d';
  const key = `${activeChart.ticker}_${activeChart.period}_${iv}`;
  if (chartCache[key]) {
    drawChart(chartCache[key], activeChart.sr);
  } else {
    fetchChartData(activeChart.ticker, activeChart.period, activeChart.interval)
      .then(cd => { if (cd) drawChart(cd, activeChart.sr); })
      .catch(() => {});
  }
}

async function switchPeriod(period) {
  document.querySelectorAll('.period-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.period === period));
  activeChart.period = period;

  // Reset interval to auto if incompatible with new period
  if (activeChart.interval) {
    const maxDays = INTERVAL_MAX_DAYS[activeChart.interval] || 3650;
    if ((PERIOD_DAYS[period] || 31) > maxDays) {
      activeChart.interval = null;
      document.querySelectorAll('.ipill').forEach(b =>
        b.classList.toggle('active', b.dataset.int === 'auto'));
    }
  }

  const wrap = document.getElementById('price-chart');
  wrap.style.opacity = '0.4';
  try {
    const cd = await fetchChartData(activeChart.ticker, period, activeChart.interval);
    if (cd) drawChart(cd, activeChart.sr);
  } catch { /* keep existing chart */ } finally {
    wrap.style.opacity = '1';
  }
}

function drawChart(cd, sr) {
  const { closes, timestamps, volumes } = cd;
  const opens = cd.opens || closes;
  const highs = cd.highs || closes;
  const lows  = cd.lows  || closes;

  const effectiveInterval = activeChart.interval || AUTO_INTERVAL[activeChart.period] || '1d';
  const isIntraday        = effectiveInterval !== '1d';
  const periodChg  = (closes[closes.length - 1] - closes[0]) / closes[0] * 100;
  const isUp       = periodChg >= 0;
  const toTime     = ts => isIntraday ? ts : tsToDay(ts);

  destroyLwChart();
  const container = document.getElementById('price-chart');
  container.innerHTML = '';

  lwChart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: 270,
    layout: {
      background: { color: '#141b2d' },
      textColor:  'rgba(255,255,255,0.35)',
      fontSize:   10,
      fontFamily: "'SF Pro Display',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
    },
    grid: {
      vertLines: { color: 'rgba(255,255,255,0.04)' },
      horzLines: { color: 'rgba(255,255,255,0.04)' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: 'rgba(255,255,255,0.2)', style: 1, labelBackgroundColor: '#1a2236' },
      horzLine: { color: 'rgba(255,255,255,0.2)', style: 1, labelBackgroundColor: '#1a2236' },
    },
    rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
    timeScale: {
      borderColor:    'rgba(255,255,255,0.06)',
      timeVisible:    isIntraday,
      secondsVisible: false,
    },
  });

  /* Buy / sell volume split — Williams Buying Pressure: (close-low)/(high-low) × vol */
  const buyVols  = volumes.map((v, i) => {
    const range = highs[i] - lows[i];
    return (range > 0 ? (closes[i] - lows[i]) / range : 0.5) * (v || 0);
  });
  const sellVols = volumes.map((v, i) => (v || 0) - buyVols[i]);

  /* Green series (full volume) rendered first (behind), red series (sell portion)
     rendered second (on top of the lower part) → stacked buy/sell appearance */
  const volHistOpts = { priceFormat: { type: 'volume' }, priceScaleId: 'vol',
                        lastValueVisible: false, priceLineVisible: false };
  lwBuyVolSeries  = lwChart.addHistogramSeries(volHistOpts);
  lwSellVolSeries = lwChart.addHistogramSeries(volHistOpts);
  lwChart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });

  lwBuyVolSeries.setData(timestamps.map((ts, i) => ({
    time: toTime(ts), value: volumes[i] || 0, color: 'rgba(0,212,170,0.28)',
  })));
  lwSellVolSeries.setData(timestamps.map((ts, i) => ({
    time: toTime(ts), value: sellVols[i], color: 'rgba(255,75,75,0.42)',
  })));

  /* Time → index lookup for legend */
  const timeToIdx = isIntraday
    ? new Map(timestamps.map((ts, i) => [ts, i]))
    : new Map(timestamps.map((ts, i) => [tsToDay(ts), i]));

  /* Main price series */
  if (activeChart.type === 'candle') {
    lwMainSeries = lwChart.addCandlestickSeries({
      upColor: '#00d4aa', downColor: '#ff4b4b',
      borderUpColor: '#00d4aa', borderDownColor: '#ff4b4b',
      wickUpColor:   '#00d4aa', wickDownColor:   '#ff4b4b',
    });
    lwMainSeries.setData(timestamps.map((ts, i) => ({
      time: toTime(ts), open: opens[i], high: highs[i], low: lows[i], close: closes[i],
    })));
  } else {
    const lColor = isUp ? '#00d4aa' : '#ff4b4b';
    lwMainSeries = lwChart.addAreaSeries({
      lineColor:    lColor,
      topColor:     isUp ? 'rgba(0,212,170,0.16)' : 'rgba(255,75,75,0.16)',
      bottomColor:  'rgba(0,0,0,0)',
      lineWidth:    2,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    lwMainSeries.setData(timestamps.map((ts, i) => ({ time: toTime(ts), value: closes[i] })));
  }

  /* S/R dashed price lines */
  if (sr) {
    sr.resistances.forEach(l => lwMainSeries.createPriceLine({
      price: l.level, color: 'rgba(255,75,75,0.65)',
      lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: 'R',
    }));
    sr.supports.forEach(l => lwMainSeries.createPriceLine({
      price: l.level, color: 'rgba(0,212,170,0.6)',
      lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: 'S',
    }));
  }

  /* Indicators — only for daily periods */
  const pillsEl = document.getElementById('indicator-pills');
  if (isIntraday) {
    if (pillsEl) { pillsEl.style.opacity = '0.35'; pillsEl.style.pointerEvents = 'none'; }
  } else {
    if (pillsEl) { pillsEl.style.opacity = '1'; pillsEl.style.pointerEvents = ''; }

    /* Use full 1Y stock data for better EMA accuracy; filter to chart window */
    const base    = activeChart.stock;
    const fCloses = base ? base.closes     : closes;
    const fTs     = base ? base.timestamps : timestamps;

    const e20   = ema(fCloses, indicatorSettings.ema20);
    const e50   = ema(fCloses, indicatorSettings.ema50);
    const e200  = ema(fCloses, indicatorSettings.ema200);
    const bbArr = calcBB(fCloses, indicatorSettings.bbPeriod, indicatorSettings.bbMult);

    const tsMap  = new Map(fTs.map((t, i) => [t, i]));
    const indPts = valFn => timestamps.map(ts => {
      const fi = tsMap.get(ts);
      if (fi === undefined) return null;
      const v = valFn(fi);
      return (v != null && !isNaN(v)) ? { time: toTime(ts), value: v } : null;
    }).filter(Boolean);

    lwInd.ema20   = addIndSeries(CHART_COLORS.ema20,   1.5);
    lwInd.ema50   = addIndSeries(CHART_COLORS.ema50,   1.5);
    lwInd.ema200  = addIndSeries(CHART_COLORS.ema200,  2);
    lwInd.bbUpper = addIndSeries(CHART_COLORS.bbUpper, 1, LightweightCharts.LineStyle.Dashed);
    lwInd.bbMid   = addIndSeries(CHART_COLORS.bbMid,   1);
    lwInd.bbLower = addIndSeries(CHART_COLORS.bbLower, 1, LightweightCharts.LineStyle.Dashed);

    lwInd.ema20.setData(indPts(i => e20[i]));
    lwInd.ema50.setData(indPts(i => e50[i]));
    lwInd.ema200.setData(indPts(i => e200[i]));
    lwInd.bbUpper.setData(indPts(i => bbArr[i]?.upper ?? null));
    lwInd.bbMid.setData(indPts(i => bbArr[i]?.mid   ?? null));
    lwInd.bbLower.setData(indPts(i => bbArr[i]?.lower ?? null));

    applyIndicatorVisibility();
  }

  /* Live legend on crosshair move */
  lwChart.subscribeCrosshairMove(param => {
    const leg = document.getElementById('chart-legend');
    if (!leg) return;

    let mainHtml = '';
    if (lwMainSeries && param.seriesData?.has(lwMainSeries)) {
      const d = param.seriesData.get(lwMainSeries);
      if (activeChart.type === 'candle' && d.open != null) {
        const up  = d.close >= d.open;
        const clr = up ? '#00d4aa' : '#ff4b4b';
        mainHtml  = `<span class="leg-main" style="color:${clr}">C $${d.close.toFixed(2)}</span>`
          + `<span class="leg-item">O $${d.open.toFixed(2)}</span>`
          + `<span class="leg-item" style="color:#00d4aa">H $${d.high.toFixed(2)}</span>`
          + `<span class="leg-item" style="color:#ff4b4b">L $${d.low.toFixed(2)}</span>`;
      } else if (d.value != null) {
        const chg0 = (d.value - closes[0]) / closes[0] * 100;
        const clr  = chg0 >= 0 ? '#00d4aa' : '#ff4b4b';
        mainHtml   = `<span class="leg-main" style="color:${clr}">$${d.value.toFixed(2)}</span>`;
      }
    }

    const getV = (serKey, indKey) => {
      const s = lwInd[serKey];
      return (s && activeIndicators[indKey] && param.seriesData?.has(s))
        ? param.seriesData.get(s)?.value : null;
    };
    const e20v  = getV('ema20',   'ema20');
    const e50v  = getV('ema50',   'ema50');
    const e200v = getV('ema200',  'ema200');
    const bbUv  = getV('bbUpper', 'bb');
    const bbLv  = getV('bbLower', 'bb');
    const indParts = [];
    if (e20v  != null) indParts.push(`<span class="leg-item" style="color:${CHART_COLORS.ema20}">EMA${indicatorSettings.ema20} $${e20v.toFixed(2)}</span>`);
    if (e50v  != null) indParts.push(`<span class="leg-item" style="color:${CHART_COLORS.ema50}">EMA${indicatorSettings.ema50} $${e50v.toFixed(2)}</span>`);
    if (e200v != null) indParts.push(`<span class="leg-item" style="color:${CHART_COLORS.ema200}">EMA${indicatorSettings.ema200} $${e200v.toFixed(2)}</span>`);
    if (bbUv  != null && bbLv != null) indParts.push(`<span class="leg-item" style="color:${CHART_COLORS.bbUpper}">BB(${indicatorSettings.bbPeriod}) ${bbLv.toFixed(2)}–${bbUv.toFixed(2)}</span>`);

    /* Buy / sell pressure for hovered bar */
    let volHtml = '';
    const idx = param.time != null ? (timeToIdx.get(param.time) ?? -1) : -1;
    if (idx >= 0 && volumes[idx] > 0) {
      const totalV = volumes[idx];
      const buyPct  = Math.round(buyVols[idx]  / totalV * 100);
      const sellPct = 100 - buyPct;
      const volFmt  = totalV >= 1e6 ? (totalV / 1e6).toFixed(1) + 'M'
                    : totalV >= 1e3 ? (totalV / 1e3).toFixed(0) + 'K'
                    : totalV.toFixed(0);
      volHtml = `<span class="leg-buysell"><span style="color:#00d4aa">▲${buyPct}%</span>`
              + `<span class="leg-vol-bar"><span style="width:${buyPct}%;background:#00d4aa"></span></span>`
              + `<span style="color:#ff4b4b">▼${sellPct}%</span>`
              + `<span class="leg-vol-total">${volFmt}</span></span>`;
    }

    let dateHtml = '';
    if (param.time) {
      if (isIntraday) {
        const dt = new Date(param.time * 1000);
        dateHtml = dt.toLocaleString('en-US', { month:'short', day:'numeric', hour:'numeric', minute:'2-digit', hour12:true });
      } else if (typeof param.time === 'string') {
        const [y, m, d] = param.time.split('-');
        const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        dateHtml = `${mo[+m-1]} ${+d}, ${y}`;
      }
    }

    leg.style.display = mainHtml ? '' : 'none';
    leg.innerHTML = `<div class="leg-row">${mainHtml}${indParts.join('')}</div>`
      + (volHtml  ? volHtml  : '')
      + (dateHtml ? `<div class="leg-date">${dateHtml}</div>` : '');
  });

  /* Period % change in header */
  const chgEl = document.getElementById('res-change');
  if (chgEl) {
    chgEl.textContent = `${periodChg >= 0 ? '+' : ''}${periodChg.toFixed(2)}% (${activeChart.period})`;
    chgEl.className   = 'stock-change ' + (periodChg >= 0 ? 'positive' : 'negative');
  }

  lwChart.timeScale().fitContent();

  /* Responsive resize */
  if (container._ro) container._ro.disconnect();
  container._ro = new ResizeObserver(() => {
    if (lwChart) lwChart.applyOptions({ width: container.clientWidth });
  });
  container._ro.observe(container);
}

/* ============================================================
   PRICE LEVEL TOUCHES
============================================================ */
function countTouches(level, highs, lows) {
  const tol = 0.015;
  const n   = Math.min(60, highs.length);
  let count = 0;
  for (let i = highs.length - n; i < highs.length; i++) {
    if (
      Math.abs(highs[i] - level) / level <= tol ||
      Math.abs(lows[i]  - level) / level <= tol ||
      (highs[i] >= level && lows[i] <= level)
    ) count++;
  }
  return count;
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

function renderPriceLadder(sr, currentPrice, stock) {
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
        <span class="ladder-oi"></span>
      </div>`;

    const dist      = Math.abs(row.level - currentPrice);
    const distPct   = (dist / currentPrice * 100).toFixed(2);
    const barPct    = Math.round(dist / maxDist * 100);
    const arrow     = row.type === 'resistance' ? '↑' : '↓';
    const dots      = [1,2,3].map(i => `<div class="dot${i <= Math.min(row.strength,3) ? ' on':''}"></div>`).join('');
    const isRes    = row.type === 'resistance';
    const touches  = stock ? countTouches(row.level, stock.highs, stock.lows) : 0;
    const oiColor  = isRes ? 'var(--bear)' : 'var(--bull)';
    const opacity  = touches >= 4 ? '1' : touches >= 2 ? '0.75' : '0.45';
    const oiBadge  = touches > 0
      ? `<span class="ladder-oi" style="color:${oiColor};opacity:${opacity}">${touches}× tested</span>`
      : `<span class="ladder-oi"></span>`;
    return `
      <div class="ladder-row ${row.type}">
        <span class="ladder-label">${row.label}</span>
        <div class="ladder-bar-wrap"><div class="ladder-bar" style="width:${barPct}%"></div></div>
        <span class="ladder-price">$${fmt(row.level)}</span>
        <span class="ladder-dist">${arrow}${distPct}%</span>
        <div class="ladder-dots">${dots}</div>
        ${oiBadge}
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
  const { ema200, currentPrice: curP } = sentiment;
  const ema200Tag = ema200 != null
    ? ` · <span style="color:${curP > ema200 ? '#00d4aa' : '#ff4b4b'};font-weight:700">${curP > ema200 ? '↑ Above' : '↓ Below'} EMA 200</span>`
    : '';
  document.getElementById('sentiment-detail').innerHTML = `${confidence}% confidence · 4-week outlook${ema200Tag}`;
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

  // Clear any cached chart data so every Analyze press fetches fresh data
  Object.keys(chartCache).filter(k => k.startsWith(t + '_')).forEach(k => delete chartCache[k]);

  setView('loading');
  setLoadingMsg('Connecting to market data…');

  try {
    const stock     = await fetchStockData(t);
    setLoadingMsg('Calculating indicators…');

    const sr        = findSR(stock);
    const sentiment = calcSentiment(stock);
    const signal    = getOptionsSignal(sentiment, sr, stock.currentPrice);

    // Seed daily chart caches from the 1Y fetch
    const now   = Date.now() / 1000;
    const jan1  = new Date(new Date().getFullYear(), 0, 1).getTime() / 1000;
    const cut3M = now - 92 * 24 * 3600;
    const cut1M = now - 31 * 24 * 3600;
    const sl    = (arr, i) => arr.slice(i >= 0 ? i : 0);
    const iYTD  = stock.timestamps.findIndex(ts => ts >= jan1);
    const i3M   = stock.timestamps.findIndex(ts => ts >= cut3M);
    const i1M   = stock.timestamps.findIndex(ts => ts >= cut1M);
    const mkCd  = i => ({ opens: sl(stock.opens, i), highs: sl(stock.highs, i), lows: sl(stock.lows, i), closes: sl(stock.closes, i), timestamps: sl(stock.timestamps, i), volumes: sl(stock.volumes, i) });
    chartCache[`${t}_1Y_1d`]  = { opens: stock.opens, highs: stock.highs, lows: stock.lows, closes: stock.closes, timestamps: stock.timestamps, volumes: stock.volumes };
    chartCache[`${t}_YTD_1d`] = mkCd(iYTD);
    chartCache[`${t}_3M_1d`]  = mkCd(i3M);
    chartCache[`${t}_1M_1d`]  = mkCd(i1M);

    // Reset chart state
    activeChart.ticker   = t;
    activeChart.period   = '1M';
    activeChart.sr       = sr;
    activeChart.stock    = stock;
    activeChart.interval = null;
    document.querySelectorAll('.period-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.period === '1M'));
    document.querySelectorAll('.ipill').forEach(b =>
      b.classList.toggle('active', b.dataset.int === 'auto'));

    renderStockHeader(stock);
    drawChart(chartCache[`${t}_1M_1d`], sr);
    renderPriceLadder(sr, stock.currentPrice, stock);
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

  // Indicator pills
  document.getElementById('indicator-pills').addEventListener('click', e => {
    const pill = e.target.closest('.pill');
    if (pill && activeChart.ticker) toggleIndicator(pill.dataset.ind);
  });

  // Interval pills
  document.getElementById('interval-pills').addEventListener('click', e => {
    const pill = e.target.closest('.ipill');
    if (pill) switchInterval(pill.dataset.int);
  });

  // Indicator settings gear toggle
  document.getElementById('indicator-settings-btn').addEventListener('click', () => {
    const panel = document.getElementById('indicator-settings-panel');
    const gear  = document.getElementById('indicator-settings-btn');
    panel.classList.toggle('hidden');
    gear.classList.toggle('active', !panel.classList.contains('hidden'));
  });

  // Apply indicator settings
  document.getElementById('apply-settings-btn').addEventListener('click', () => {
    indicatorSettings.ema20    = Math.max(2, parseInt(document.getElementById('set-ema20').value)    || 20);
    indicatorSettings.ema50    = Math.max(2, parseInt(document.getElementById('set-ema50').value)    || 50);
    indicatorSettings.ema200   = Math.max(2, parseInt(document.getElementById('set-ema200').value)   || 200);
    indicatorSettings.bbPeriod = Math.max(2, parseInt(document.getElementById('set-bbperiod').value) || 20);
    indicatorSettings.bbMult   = Math.max(0.1, parseFloat(document.getElementById('set-bbmult').value) || 2);

    // Update pill labels to reflect new periods
    document.querySelector('.pill[data-ind="ema20"]').textContent  = `EMA ${indicatorSettings.ema20}`;
    document.querySelector('.pill[data-ind="ema50"]').textContent  = `EMA ${indicatorSettings.ema50}`;
    document.querySelector('.pill[data-ind="ema200"]').textContent = `EMA ${indicatorSettings.ema200}`;
    document.querySelector('.pill[data-ind="bb"]').textContent     = `BB(${indicatorSettings.bbPeriod})`;

    // Redraw with new settings
    if (activeChart.ticker) {
      const iv  = activeChart.interval || AUTO_INTERVAL[activeChart.period] || '1d';
      const key = `${activeChart.ticker}_${activeChart.period}_${iv}`;
      if (chartCache[key]) drawChart(chartCache[key], activeChart.sr);
    }

    document.getElementById('indicator-settings-panel').classList.add('hidden');
    document.getElementById('indicator-settings-btn').classList.remove('active');
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
