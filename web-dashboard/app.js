const state = {
  refreshSeconds: 1,
  timers: new Set(),
  chartReady: false,
  selectedBar: '15m',
};

const dom = {
  badge: document.getElementById('signal-badge'),
  lastUpdate: document.getElementById('last-update'),
  metaStrategy: document.getElementById('meta-strategy'),
  metaInstrument: document.getElementById('meta-instrument'),
  barSelect: document.getElementById('bar-select'),
  metaRefresh: document.getElementById('meta-refresh'),
  refreshBtn: document.getElementById('refresh-btn'),
  priceValue: document.getElementById('price-value'),
  signalValue: document.getElementById('signal-value'),
  recommendValue: document.getElementById('recommend-value'),
  suggestedSide: document.getElementById('suggested-side'),
  suggestedEntry: document.getElementById('suggested-entry'),
  suggestedStopLoss: document.getElementById('suggested-stop-loss'),
  suggestedTakeProfit: document.getElementById('suggested-take-profit'),
  marketRegime: document.getElementById('market-regime'),
  positionValue: document.getElementById('position-value'),
  equityValue: document.getElementById('equity-value'),
  cashValue: document.getElementById('cash-value'),
  candleTime: document.getElementById('candle-time'),
  hoverInfo: document.getElementById('hover-info'),
  chartRange: document.getElementById('chart-range'),
  quickHint: document.getElementById('quick-hint'),
  analysisTitle: document.getElementById('analysis-title'),
  analysisBias: document.getElementById('analysis-bias'),
  analysisConfidence: document.getElementById('analysis-confidence'),
  analysisDescription: document.getElementById('analysis-description'),
  tradesBody: document.getElementById('trades-body'),
  jsonOutput: document.getElementById('json-output'),
  priceChart: document.getElementById('price-chart'),
  rsiChart: document.getElementById('rsi-chart'),
  macdChart: document.getElementById('macd-chart'),
};

const chartTheme = {
  layout: { background: { color: '#0a0f1a' }, textColor: '#d7dde7', fontFamily: 'Inter, Microsoft YaHei UI, sans-serif' },
  grid: { vertLines: { color: '#1a2437' }, horzLines: { color: '#1a2437' } },
  rightPriceScale: { borderColor: '#24324a' },
  timeScale: { borderColor: '#24324a', timeVisible: true, secondsVisible: false },
  crosshair: {
    mode: LightweightCharts.CrosshairMode.Normal,
    vertLine: { color: '#6b7b93', style: LightweightCharts.LineStyle.Dashed },
    horzLine: { color: '#6b7b93', style: LightweightCharts.LineStyle.Dashed },
  },
};

function formatTimeLabel(iso) {
  return iso.replace('T', ' ');
}

function toUnixSeconds(iso) {
  return Math.floor(new Date(iso).getTime() / 1000);
}

function mapSignal(action, reason) {
  const label = ({ buy: '买入', sell: '卖出', hold: '观望' })[action] || action;
  return reason ? `${label} / ${reason}` : label;
}

function mapRecommendation(value) {
  return ({ enter_long: '建议开多', exit_long: '建议平仓', hold_long: '继续持有', stand_aside: '继续观望' })[value] || value;
}

function mapPosition(state, qty) {
  return `${({ flat: '空仓', long: '持多' })[state] || state} (${Number(qty).toFixed(6)})`;
}

function setBadge(snapshot) {
  dom.badge.classList.remove('buy', 'sell', 'idle');
  if (snapshot.latest_signal_action === 'buy' || snapshot.recommendation === 'enter_long') {
    dom.badge.textContent = '买入信号';
    dom.badge.classList.add('buy');
  } else if (snapshot.latest_signal_action === 'sell' || snapshot.recommendation === 'exit_long') {
    dom.badge.textContent = '卖出信号';
    dom.badge.classList.add('sell');
  } else {
    dom.badge.textContent = '观望中';
    dom.badge.classList.add('idle');
  }
}

function buildMarkers(trades) {
  return trades.map((trade) => ({
    time: toUnixSeconds(trade.timestamp),
    position: trade.side === 'buy' ? 'belowBar' : 'aboveBar',
    color: trade.side === 'buy' ? '#22c55e' : '#ef4444',
    shape: trade.side === 'buy' ? 'arrowUp' : 'arrowDown',
    text: trade.side === 'buy' ? '买入' : '卖出',
  }));
}

function setupCharts() {
  if (state.chartReady) return;
  state.priceChartObj = LightweightCharts.createChart(dom.priceChart, { ...chartTheme, height: dom.priceChart.clientHeight });
  state.rsiChartObj = LightweightCharts.createChart(dom.rsiChart, { ...chartTheme, height: dom.rsiChart.clientHeight });
  state.macdChartObj = LightweightCharts.createChart(dom.macdChart, { ...chartTheme, height: dom.macdChart.clientHeight });

  state.candleSeries = state.priceChartObj.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444'
  });
  state.ma5Series = state.priceChartObj.addSeries(LightweightCharts.LineSeries, { color: '#38bdf8', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.ma10Series = state.priceChartObj.addSeries(LightweightCharts.LineSeries, { color: '#a78bfa', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.ma20Series = state.priceChartObj.addSeries(LightweightCharts.LineSeries, { color: '#fb923c', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });

  state.rsiSeries = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#a78bfa', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.rsiTop = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#f59e0b', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
  state.rsiMid = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#3b4a61', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
  state.rsiLow = state.rsiChartObj.addSeries(LightweightCharts.LineSeries, { color: '#f59e0b', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
  state.rsiChartObj.priceScale('right').applyOptions({ autoScale: false, scaleMargins: { top: 0.15, bottom: 0.15 } });

  state.macdSeries = state.macdChartObj.addSeries(LightweightCharts.LineSeries, { color: '#38bdf8', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.macdSignalSeries = state.macdChartObj.addSeries(LightweightCharts.LineSeries, { color: '#fb923c', lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
  state.macdHistSeries = state.macdChartObj.addSeries(LightweightCharts.HistogramSeries, { priceLineVisible: false, lastValueVisible: false, base: 0 });

  syncCharts(state.priceChartObj, state.rsiChartObj);
  syncCharts(state.priceChartObj, state.macdChartObj);

  state.priceChartObj.subscribeCrosshairMove(param => {
    if (!param || !param.time || !param.seriesData) {
      dom.hoverInfo.textContent = '将鼠标移动到图表上';
      return;
    }
    const candle = param.seriesData.get(state.candleSeries);
    if (!candle) return;
    const time = new Date(param.time * 1000).toISOString().slice(0, 16).replace('T', ' ');
    dom.hoverInfo.textContent = `${time} | O ${Number(candle.open).toFixed(2)} H ${Number(candle.high).toFixed(2)} L ${Number(candle.low).toFixed(2)} C ${Number(candle.close).toFixed(2)}`;
  });

  window.addEventListener('resize', () => {
    state.priceChartObj.resize(dom.priceChart.clientWidth, dom.priceChart.clientHeight);
    state.rsiChartObj.resize(dom.rsiChart.clientWidth, dom.rsiChart.clientHeight);
    state.macdChartObj.resize(dom.macdChart.clientWidth, dom.macdChart.clientHeight);
  });

  state.chartReady = true;
}

function syncCharts(sourceChart, targetChart) {
  sourceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (range) targetChart.timeScale().setVisibleLogicalRange(range);
  });
}

function makeLineData(candles, values) {
  return values.map((value, index) => value == null ? null : ({ time: toUnixSeconds(candles[index].time), value })).filter(Boolean);
}

function updateCharts(payload) {
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
    color: value >= 0 ? '#22c55e' : '#ef4444',
  })).filter(Boolean));

  state.priceChartObj.timeScale().fitContent();
  state.rsiChartObj.timeScale().fitContent();
  state.macdChartObj.timeScale().fitContent();

  dom.chartRange.textContent = `${formatTimeLabel(payload.candles[0].time)} -> ${formatTimeLabel(payload.candles[payload.candles.length - 1].time)}`;
}

function updateSummary(payload) {
  const s = payload.snapshot;
  dom.metaStrategy.textContent = payload.meta.strategy;
  dom.metaInstrument.textContent = payload.meta.instrument;
  dom.barSelect.value = payload.meta.bar;
  state.selectedBar = payload.meta.bar;
  dom.metaRefresh.textContent = `${payload.meta.refresh_seconds}秒`;
  dom.priceValue.textContent = `${Number(s.latest_close).toFixed(2)} USDT`;
  dom.signalValue.textContent = mapSignal(s.latest_signal_action, s.latest_signal_reason);
  dom.recommendValue.textContent = mapRecommendation(s.recommendation);
  dom.suggestedSide.textContent = s.suggested_side;
  dom.suggestedEntry.textContent = `${Number(s.suggested_entry).toFixed(2)} USDT`;
  dom.suggestedStopLoss.textContent = `${Number(s.suggested_stop_loss).toFixed(2)} USDT`;
  dom.suggestedTakeProfit.textContent = `${Number(s.suggested_take_profit).toFixed(2)} USDT`;
  dom.marketRegime.textContent = `${s.market_regime} / ${s.market_bias}`;
  dom.positionValue.textContent = mapPosition(s.current_position_state, s.current_position_qty);
  dom.equityValue.textContent = `${Number(s.equity).toFixed(2)} USDT`;
  dom.cashValue.textContent = `${Number(s.cash).toFixed(2)} USDT`;
  dom.candleTime.textContent = formatTimeLabel(s.latest_timestamp);
  dom.analysisTitle.textContent = `${s.market_regime} · ${s.strategy_label}`;
  dom.analysisBias.textContent = `行情倾向：${s.market_bias} | 建议方向：${s.suggested_side}`;
  dom.analysisConfidence.textContent = `分析置信度：${(Number(s.market_confidence) * 100).toFixed(0)}% | 周期：${payload.meta.bar}`;
  dom.analysisDescription.textContent = s.strategy_description;
  dom.quickHint.textContent = `当前建议：${mapRecommendation(s.recommendation)} | ${s.market_regime} | 建议方向：${s.suggested_side} | 开仓 ${Number(s.suggested_entry).toFixed(2)} / 止损 ${Number(s.suggested_stop_loss).toFixed(2)} / 止盈 ${Number(s.suggested_take_profit).toFixed(2)}`;
  dom.lastUpdate.textContent = `上次刷新：${new Date().toLocaleString('zh-CN')}`;
  setBadge(s);
}

function updateTrades(trades) {
  if (!trades || trades.length === 0) {
    dom.tradesBody.innerHTML = '<tr><td colspan="5" class="muted center">暂无最近成交</td></tr>';
    return;
  }
  dom.tradesBody.innerHTML = trades.map(trade => {
    const sideClass = trade.side === 'buy' ? 'buy-text' : 'sell-text';
    const sideLabel = trade.side === 'buy' ? '买入' : '卖出';
    return `<tr>
      <td>${formatTimeLabel(trade.timestamp)}</td>
      <td class="${sideClass}">${sideLabel}</td>
      <td>${Number(trade.price).toFixed(2)}</td>
      <td>${Number(trade.quantity).toFixed(6)}</td>
      <td>${trade.reason || ''}</td>
    </tr>`;
  }).join('');
}

async function fetchDashboard() {
  const params = new URLSearchParams({ bar: state.selectedBar });
  const res = await fetch(`/api/dashboard?${params.toString()}`, { cache: 'no-store' });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || '获取数据失败');
  state.refreshSeconds = payload.meta.refresh_seconds;
  updateSummary(payload);
  updateTrades(payload.snapshot.recent_trades || []);
  dom.jsonOutput.textContent = JSON.stringify(payload.snapshot, null, 2);
  updateCharts(payload);
}

async function refreshLoop() {
  try {
    await fetchDashboard();
  } catch (err) {
    dom.lastUpdate.textContent = `刷新失败：${err.message}`;
    dom.quickHint.textContent = '数据拉取失败，请检查本地服务日志';
  } finally {
    window.clearTimeout(state.timerId);
    state.timerId = window.setTimeout(refreshLoop, state.refreshSeconds * 1000);
  }
}

dom.refreshBtn.addEventListener('click', () => {
  window.clearTimeout(state.timerId);
  refreshLoop();
});

dom.barSelect.addEventListener('change', () => {
  state.selectedBar = dom.barSelect.value;
  window.clearTimeout(state.timerId);
  refreshLoop();
});

setupCharts();
refreshLoop();
