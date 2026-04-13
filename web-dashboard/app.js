const SHANGHAI_TIME_ZONE = 'Asia/Shanghai';

const state = {
  refreshSeconds: 1,
  chartReady: false,
  selectedBar: '15m',
  selectedStrategy: 'okx_15m_mtf',
  eventSource: null,
  timerId: null,
  hasRenderedData: false,
  lastRenderedBar: null,
  lastChartSignature: null,
  interactingUntil: 0,
  pendingChartPayload: null,
  hoverFramePending: false,
  pendingHoverText: null,
};

const dom = {
  badge: document.getElementById('signal-badge'),
  lastUpdate: document.getElementById('last-update'),
  strategySelect: document.getElementById('strategy-select'),
  importStrategyBtn: document.getElementById('import-strategy-btn'),
  strategyFileInput: document.getElementById('strategy-file-input'),
  metaInstrument: document.getElementById('meta-instrument'),
  barSelect: document.getElementById('bar-select'),
  metaRefresh: document.getElementById('meta-refresh'),
  refreshBtn: document.getElementById('refresh-btn'),
  priceValue: document.getElementById('price-value'),
  priceSubvalue: document.getElementById('price-subvalue'),
  wsStatusText: document.getElementById('ws-status-text'),
  wsStatusDot: document.getElementById('ws-status-dot'),
  signalValue: document.getElementById('signal-value'),
  suggestedSide: document.getElementById('suggested-side'),
  suggestedEntry: document.getElementById('suggested-entry'),
  suggestedStopLoss: document.getElementById('suggested-stop-loss'),
  suggestedTakeProfit: document.getElementById('suggested-take-profit'),
  marketRegime: document.getElementById('market-regime'),
  hoverInfo: document.getElementById('hover-info'),
  chartRange: document.getElementById('chart-range'),
  quickHint: document.getElementById('quick-hint'),
  analysisTitle: document.getElementById('analysis-title'),
  analysisBias: document.getElementById('analysis-bias'),
  analysisConfidence: document.getElementById('analysis-confidence'),
  analysisDescription: document.getElementById('analysis-description'),
  priceChart: document.getElementById('price-chart'),
  rsiChart: document.getElementById('rsi-chart'),
  macdChart: document.getElementById('macd-chart'),
};

const chartTheme = {
  layout: {
    attributionLogo: false,
    background: { color: '#0a0f1a' },
    textColor: '#d7dde7',
    fontFamily: 'Inter, Microsoft YaHei UI, sans-serif'
  },
  grid: { vertLines: { color: '#1a2437' }, horzLines: { color: '#1a2437' } },
  rightPriceScale: { borderColor: '#24324a' },
  timeScale: { borderColor: '#24324a', timeVisible: true, secondsVisible: false },
  crosshair: {
    mode: LightweightCharts.CrosshairMode.Normal,
    vertLine: { color: '#6b7b93', style: LightweightCharts.LineStyle.Dashed },
    horzLine: { color: '#6b7b93', style: LightweightCharts.LineStyle.Dashed },
  },
  handleScroll: { pressedMouseMove: true, mouseWheel: true, horzTouchDrag: true, vertTouchDrag: true },
  handleScale: { axisPressedMouseMove: true, pinch: true, mouseWheel: true },
};

function parseIsoAsUtc(iso) {
  if (!iso) return null;
  if (iso.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(iso)) {
    return new Date(iso);
  }
  return new Date(`${iso}Z`);
}

function formatBeijingTime(iso) {
  if (!iso) return '-';
  const date = parseIsoAsUtc(iso);
  if (!date || Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: SHANGHAI_TIME_ZONE,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date).replaceAll('/', '-');
}

function toUnixSeconds(iso) {
  const date = parseIsoAsUtc(iso);
  return Math.floor(date.getTime() / 1000);
}

function mapRecommendation(value) {
  return ({ enter_long: '建议开多', exit_long: '建议平仓', hold_long: '继续持有', stand_aside: '继续观望' })[value] || '继续观望';
}

function setBadge(snapshot) {
  dom.badge.classList.remove('buy', 'sell', 'idle');
  const text = mapRecommendation(snapshot.recommendation);
  dom.badge.textContent = text;
  if (snapshot.recommendation === 'enter_long') {
    dom.badge.classList.add('buy');
  } else if (snapshot.recommendation === 'exit_long') {
    dom.badge.classList.add('sell');
  } else {
    dom.badge.classList.add('idle');
  }
}

function setConnectionStatus(realtime) {
  const online = realtime && realtime.status === 'connected';
  dom.wsStatusText.textContent = online ? '已连接' : '未连接';
  dom.wsStatusDot.classList.toggle('status-online', online);
  dom.wsStatusDot.classList.toggle('status-offline', !online);
}

function buildMarkers(trades) {
  return trades.map((trade) => ({
    time: toUnixSeconds(trade.timestamp),
    position: trade.side === 'buy' ? 'belowBar' : 'aboveBar',
    color: trade.side === 'buy' ? '#ef4444' : '#22c55e',
    shape: trade.side === 'buy' ? 'arrowUp' : 'arrowDown',
    text: trade.side === 'buy' ? '买入' : '卖出',
  }));
}

function queueHoverText(text) {
  state.pendingHoverText = text;
  if (state.hoverFramePending) return;
  state.hoverFramePending = true;
  window.requestAnimationFrame(() => {
    dom.hoverInfo.textContent = state.pendingHoverText;
    state.hoverFramePending = false;
  });
}

function markChartInteraction() {
  state.interactingUntil = Date.now() + 900;
}

function flushPendingChartUpdate() {
  if (Date.now() < state.interactingUntil) {
    window.setTimeout(flushPendingChartUpdate, 120);
    return;
  }
  if (state.pendingChartPayload) {
    const payload = state.pendingChartPayload;
    state.pendingChartPayload = null;
    renderCharts(payload);
  }
}

function explainCandle(candle, iso) {
  const move = candle.close - candle.open;
  const direction = move > 0 ? '上涨' : move < 0 ? '下跌' : '横盘';
  return `${formatBeijingTime(iso)}，这根K线${direction}，开盘 ${Number(candle.open).toFixed(2)}，收盘 ${Number(candle.close).toFixed(2)}，最高 ${Number(candle.high).toFixed(2)}，最低 ${Number(candle.low).toFixed(2)}。`;
}

function setupCharts() {
  if (state.chartReady) return;
  state.priceChartObj = LightweightCharts.createChart(dom.priceChart, { ...chartTheme, height: dom.priceChart.clientHeight });
  state.rsiChartObj = LightweightCharts.createChart(dom.rsiChart, { ...chartTheme, height: dom.rsiChart.clientHeight });
  state.macdChartObj = LightweightCharts.createChart(dom.macdChart, { ...chartTheme, height: dom.macdChart.clientHeight });

  state.candleSeries = state.priceChartObj.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: '#ef4444', downColor: '#22c55e', borderVisible: false, wickUpColor: '#ef4444', wickDownColor: '#22c55e'
  });
  state.ma5Series = state.priceChartObj.addSeries(LightweightCharts.LineSeries, { color: '#38bdf8', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.ma10Series = state.priceChartObj.addSeries(LightweightCharts.LineSeries, { color: '#a78bfa', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.ma20Series = state.priceChartObj.addSeries(LightweightCharts.LineSeries, { color: '#fb923c', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });

  state.rsiSeries = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#e879f9', lineWidth: 3, priceLineVisible: false, lastValueVisible: true });
  state.rsiTop = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#f59e0b', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
  state.rsiMid = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#64748b', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
  state.rsiLow = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#f59e0b', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
  state.rsiChartObj.priceScale('right').applyOptions({ autoScale: true, scaleMargins: { top: 0.12, bottom: 0.12 } });

  state.macdSeries = state.macdChartObj.addSeries(LightweightCharts.LineSeries, { color: '#38bdf8', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.macdSignalSeries = state.macdChartObj.addSeries(LightweightCharts.LineSeries, { color: '#fb923c', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.macdHistSeries = state.macdChartObj.addSeries(LightweightCharts.HistogramSeries, { priceLineVisible: false, lastValueVisible: false, base: 0 });

  syncCharts(state.priceChartObj, state.rsiChartObj);
  syncCharts(state.priceChartObj, state.macdChartObj);

  state.priceChartObj.subscribeCrosshairMove(param => {
    if (!param || !param.time || !param.seriesData) {
      queueHoverText('将鼠标移动到图表上，可查看当前K线的中文解读。');
      return;
    }
    const candle = param.seriesData.get(state.candleSeries);
    if (!candle) return;
    queueHoverText(explainCandle(candle, new Date(param.time * 1000).toISOString()));
  });

  [dom.priceChart, dom.rsiChart, dom.macdChart].forEach((el) => {
    ['pointerdown', 'wheel', 'touchstart'].forEach((eventName) => {
      el.addEventListener(eventName, () => {
        markChartInteraction();
        window.setTimeout(flushPendingChartUpdate, 1000);
      }, { passive: true });
    });
  });

  window.addEventListener('resize', () => {
    state.priceChartObj.resize(dom.priceChart.clientWidth, dom.priceChart.clientHeight);
    state.rsiChartObj.resize(dom.rsiChart.clientWidth, dom.rsiChart.clientHeight);
    state.macdChartObj.resize(dom.macdChart.clientWidth, dom.macdChart.clientHeight);
  });

  state.chartReady = true;
}

function syncCharts(sourceChart, targetChart) {
  let syncing = false;
  sourceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (!range || syncing) return;
    syncing = true;
    targetChart.timeScale().setVisibleLogicalRange(range);
    window.requestAnimationFrame(() => { syncing = false; });
  });
}

function makeLineData(candles, values) {
  return values.map((value, index) => value == null ? null : ({ time: toUnixSeconds(candles[index].time), value })).filter(Boolean);
}

function buildChartSignature(payload) {
  const candles = payload.candles || [];
  if (candles.length === 0) return 'empty';
  const last = candles[candles.length - 1];
  return [payload.meta.bar, payload.meta.strategy, candles.length, last.time, last.open, last.high, last.low, last.close].join('|');
}

function renderCharts(payload) {
  if (!payload.candles || payload.candles.length === 0) return;

  const candles = payload.candles.map(c => ({
    time: toUnixSeconds(c.time),
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
  const candleSource = payload.candles;
  const indicators = payload.indicators;

  state.candleSeries.setData(candles);
  LightweightCharts.createSeriesMarkers(state.candleSeries, buildMarkers(payload.snapshot.recent_trades || []));
  state.ma5Series.setData(makeLineData(candleSource, indicators.ma5));
  state.ma10Series.setData(makeLineData(candleSource, indicators.ma10));
  state.ma20Series.setData(makeLineData(candleSource, indicators.ma20));

  state.rsiSeries.setData(makeLineData(candleSource, indicators.rsi14));
  const guideData70 = candleSource.map(c => ({ time: toUnixSeconds(c.time), value: 70 }));
  const guideData50 = candleSource.map(c => ({ time: toUnixSeconds(c.time), value: 50 }));
  const guideData30 = candleSource.map(c => ({ time: toUnixSeconds(c.time), value: 30 }));
  state.rsiTop.setData(guideData70);
  state.rsiMid.setData(guideData50);
  state.rsiLow.setData(guideData30);

  state.macdSeries.setData(makeLineData(candleSource, indicators.macd));
  state.macdSignalSeries.setData(makeLineData(candleSource, indicators.macd_signal));
  state.macdHistSeries.setData(indicators.macd_histogram.map((value, index) => value == null ? null : ({
    time: toUnixSeconds(candleSource[index].time),
    value,
    color: value >= 0 ? '#ef4444' : '#22c55e',
  })).filter(Boolean));

  if (!state.hasRenderedData || state.lastRenderedBar !== state.selectedBar) {
    state.priceChartObj.timeScale().fitContent();
    state.rsiChartObj.timeScale().fitContent();
    state.macdChartObj.timeScale().fitContent();
  }
  state.hasRenderedData = true;
  state.lastRenderedBar = state.selectedBar;
  state.lastChartSignature = buildChartSignature(payload);

  dom.chartRange.textContent = `${formatBeijingTime(payload.candles[0].time)} -> ${formatBeijingTime(payload.candles[payload.candles.length - 1].time)}`;
}

function updateCharts(payload) {
  const signature = buildChartSignature(payload);
  if (signature === state.lastChartSignature && state.lastRenderedBar === state.selectedBar) {
    return;
  }
  if (Date.now() < state.interactingUntil) {
    state.pendingChartPayload = payload;
    return;
  }
  renderCharts(payload);
}

function renderStrategyChoices(choices, currentValue) {
  if (!choices || choices.length === 0) return;
  dom.strategySelect.innerHTML = choices.map(item => `<option value="${item.name}">${item.label}</option>`).join('');
  dom.strategySelect.value = currentValue;
}

function updateSummary(payload) {
  const s = payload.snapshot;
  const realtime = payload.realtime || {};

  renderStrategyChoices(payload.meta.strategy_choices || [], payload.meta.strategy);
  state.selectedStrategy = payload.meta.strategy;
  dom.metaInstrument.textContent = payload.meta.instrument;
  dom.barSelect.value = payload.meta.bar;
  state.selectedBar = payload.meta.bar;
  dom.metaRefresh.textContent = '实时推送';
  const headlinePrice = realtime.latest_price == null ? s.latest_close : realtime.latest_price;
  dom.priceValue.textContent = `${Number(headlinePrice).toFixed(2)} USDT`;
  dom.priceSubvalue.textContent = `K线收盘价（北京时间）：${realtime.latest_candle_close == null ? '-' : `${Number(realtime.latest_candle_close).toFixed(2)} USDT`} | Tick时间（北京时间）：${formatBeijingTime(realtime.latest_price_ts)}`;
  setConnectionStatus(realtime);
  dom.signalValue.textContent = mapRecommendation(s.recommendation);
  dom.suggestedSide.textContent = s.suggested_side;
  dom.suggestedEntry.textContent = `${Number(s.suggested_entry).toFixed(2)} USDT`;
  dom.suggestedStopLoss.textContent = `${Number(s.suggested_stop_loss).toFixed(2)} USDT`;
  dom.suggestedTakeProfit.textContent = `${Number(s.suggested_take_profit).toFixed(2)} USDT`;
  dom.marketRegime.textContent = `${s.market_regime}，偏向 ${s.market_bias}`;
  dom.analysisTitle.textContent = `${payload.meta.strategy_label} · ${s.market_regime}`;
  dom.analysisBias.textContent = `行情倾向：${s.market_bias} | 建议方向：${s.suggested_side}`;
  dom.analysisConfidence.textContent = `分析置信度：${(Number(s.market_confidence) * 100).toFixed(0)}% | 周期：${payload.meta.bar}`;
  dom.analysisDescription.textContent = s.strategy_description;
  dom.quickHint.textContent = `${payload.meta.strategy_label} 当前建议：${mapRecommendation(s.recommendation)}。建议方向：${s.suggested_side}，参考开仓 ${Number(s.suggested_entry).toFixed(2)}，止损 ${Number(s.suggested_stop_loss).toFixed(2)}，止盈 ${Number(s.suggested_take_profit).toFixed(2)}。`;
  dom.lastUpdate.textContent = `上次更新：${formatBeijingTime(new Date().toISOString())}`;
  setBadge(s);
}

function applyPayload(payload) {
  state.refreshSeconds = payload.meta.refresh_seconds || 1;
  updateSummary(payload);
  updateCharts(payload);
}

async function fetchDashboard() {
  const params = new URLSearchParams({ bar: state.selectedBar, strategy: state.selectedStrategy });
  const res = await fetch(`/api/dashboard?${params.toString()}`, { cache: 'no-store' });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || '获取数据失败');
  applyPayload(payload);
}

function stopPolling() {
  window.clearTimeout(state.timerId);
  state.timerId = null;
}

function schedulePolling() {
  stopPolling();
  state.timerId = window.setTimeout(async () => {
    try {
      await fetchDashboard();
    } catch (err) {
      dom.lastUpdate.textContent = `刷新失败：${err.message}`;
      dom.quickHint.textContent = '数据拉取失败，请检查本地服务日志';
    } finally {
      schedulePolling();
    }
  }, Math.max(1, state.refreshSeconds) * 1000);
}

function closeStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function connectStream() {
  closeStream();
  stopPolling();
  if (!window.EventSource) {
    schedulePolling();
    return;
  }
  const params = new URLSearchParams({ bar: state.selectedBar, strategy: state.selectedStrategy });
  const stream = new EventSource(`/api/dashboard-stream?${params.toString()}`);
  state.eventSource = stream;

  stream.addEventListener('dashboard', (event) => {
    try {
      const payload = JSON.parse(event.data);
      applyPayload(payload);
    } catch (err) {
      dom.lastUpdate.textContent = `实时消息解析失败：${err.message}`;
    }
  });

  stream.onerror = () => {
    dom.lastUpdate.textContent = `实时推送重连中：${formatBeijingTime(new Date().toISOString())}`;
    if (!state.eventSource) return;
    closeStream();
    schedulePolling();
    window.setTimeout(() => {
      if (!state.eventSource) connectStream();
    }, 1500);
  };
}

async function importStrategyFile(file) {
  const text = await file.text();
  const contentBase64 = btoa(unescape(encodeURIComponent(text)));
  const res = await fetch('/api/strategy-import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name, content_base64: contentBase64 }),
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) {
    throw new Error(payload.error || '策略导入失败');
  }
  renderStrategyChoices(payload.strategies || [], state.selectedStrategy);
  return payload;
}

async function bootstrapRealtime() {
  try {
    await fetchDashboard();
    connectStream();
  } catch (err) {
    dom.lastUpdate.textContent = `初始化失败：${err.message}`;
    dom.quickHint.textContent = '数据拉取失败，请检查本地服务日志';
    schedulePolling();
  }
}

dom.refreshBtn.addEventListener('click', async () => {
  stopPolling();
  try {
    await fetchDashboard();
  } catch (err) {
    dom.lastUpdate.textContent = `刷新失败：${err.message}`;
  }
  connectStream();
});

dom.barSelect.addEventListener('change', () => {
  state.selectedBar = dom.barSelect.value;
  state.hasRenderedData = false;
  state.lastChartSignature = null;
  bootstrapRealtime();
});

dom.strategySelect.addEventListener('change', () => {
  state.selectedStrategy = dom.strategySelect.value;
  state.hasRenderedData = false;
  state.lastChartSignature = null;
  bootstrapRealtime();
});

dom.importStrategyBtn.addEventListener('click', () => {
  dom.strategyFileInput.click();
});

dom.strategyFileInput.addEventListener('change', async () => {
  const file = dom.strategyFileInput.files && dom.strategyFileInput.files[0];
  if (!file) return;
  try {
    dom.lastUpdate.textContent = '正在导入策略...';
    const payload = await importStrategyFile(file);
    const newest = payload.strategies[payload.strategies.length - 1];
    if (newest) {
      state.selectedStrategy = newest.name;
      dom.strategySelect.value = newest.name;
    }
    await fetchDashboard();
    connectStream();
    dom.lastUpdate.textContent = payload.message;
  } catch (err) {
    dom.lastUpdate.textContent = `策略导入失败：${err.message}`;
  } finally {
    dom.strategyFileInput.value = '';
  }
});

window.addEventListener('beforeunload', () => {
  closeStream();
  stopPolling();
});

setupCharts();
bootstrapRealtime();
