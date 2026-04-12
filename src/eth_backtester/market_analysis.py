from __future__ import annotations

from dataclasses import dataclass

from .indicators import average_true_range, relative_strength_index, simple_moving_average
from .models import Candle


@dataclass(frozen=True)
class MarketAnalysis:
    timeframe: str
    regime: str
    bias: str
    confidence: float
    strategy_label: str
    strategy_description: str
    suggested_side: str
    suggested_entry: float
    suggested_stop_loss: float
    suggested_take_profit: float

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "regime": self.regime,
            "bias": self.bias,
            "confidence": round(self.confidence, 4),
            "strategy_label": self.strategy_label,
            "strategy_description": self.strategy_description,
            "suggested_side": self.suggested_side,
            "suggested_entry": round(self.suggested_entry, 6),
            "suggested_stop_loss": round(self.suggested_stop_loss, 6),
            "suggested_take_profit": round(self.suggested_take_profit, 6),
        }


def _last_non_none(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def analyze_market(candles: list[Candle], timeframe: str) -> MarketAnalysis:
    if len(candles) < 30:
        raise ValueError("at least 30 candles are required for market analysis")

    closes = [c.close for c in candles]
    latest_close = closes[-1]
    sma10 = _last_non_none(simple_moving_average(closes, 10))
    sma20 = _last_non_none(simple_moving_average(closes, 20))
    atr = _last_non_none(average_true_range(candles, 14))
    rsi = _last_non_none(relative_strength_index(closes, 14))
    if sma10 is None or sma20 is None or atr is None or rsi is None:
        raise ValueError("not enough indicator history for market analysis")

    atr = max(atr, latest_close * 0.002)
    atr_pct = atr / latest_close if latest_close else 0.0
    recent_window = closes[-20:]
    range_high = max(recent_window)
    range_low = min(recent_window)
    range_width = max(range_high - range_low, atr)
    ma_spread_pct = abs(sma10 - sma20) / latest_close if latest_close else 0.0
    price_vs_sma20 = (latest_close - sma20) / latest_close if latest_close else 0.0

    if latest_close > sma10 > sma20 and price_vs_sma20 > 0.003 and ma_spread_pct > 0.0025:
        regime = "上涨趋势"
        bias = "偏多"
        confidence = _clamp((price_vs_sma20 * 120) + (ma_spread_pct * 180), 0.55, 0.95)
        entry = min(latest_close - atr * 0.35, sma10 + atr * 0.15)
        stop_loss = entry - atr * 1.25
        take_profit = entry + atr * 2.4
        strategy_label = "顺势回踩做多"
        strategy_description = f"{timeframe} 周期偏强，优先等待回踩均线后做多，避免追高。"
        suggested_side = "做多"
    elif latest_close < sma10 < sma20 and price_vs_sma20 < -0.003 and ma_spread_pct > 0.0025:
        regime = "下跌趋势"
        bias = "偏空"
        confidence = _clamp((abs(price_vs_sma20) * 120) + (ma_spread_pct * 180), 0.55, 0.95)
        entry = max(latest_close + atr * 0.35, sma10 - atr * 0.15)
        stop_loss = entry + atr * 1.25
        take_profit = entry - atr * 2.4
        strategy_label = "顺势反弹做空"
        strategy_description = f"{timeframe} 周期偏弱，优先等待反弹后做空，不建议逆势抄底。"
        suggested_side = "做空"
    else:
        regime = "震荡"
        bias = "中性"
        confidence = _clamp((range_width / latest_close) * 35 + (0.08 if 40 <= rsi <= 60 else 0.02), 0.45, 0.82)
        mid = (range_high + range_low) / 2
        if latest_close <= mid:
            entry = range_low + atr * 0.45
            stop_loss = entry - atr * 1.05
            take_profit = min(range_high - atr * 0.25, entry + atr * 1.8)
            suggested_side = "低吸做多"
        else:
            entry = range_high - atr * 0.45
            stop_loss = entry + atr * 1.05
            take_profit = max(range_low + atr * 0.25, entry - atr * 1.8)
            suggested_side = "高抛做空"
        strategy_label = "区间震荡策略"
        strategy_description = f"{timeframe} 周期更适合区间交易：靠近支撑低吸，靠近压力高抛，止盈不要贪。"

    return MarketAnalysis(
        timeframe=timeframe,
        regime=regime,
        bias=bias,
        confidence=confidence,
        strategy_label=strategy_label,
        strategy_description=strategy_description,
        suggested_side=suggested_side,
        suggested_entry=entry,
        suggested_stop_loss=stop_loss,
        suggested_take_profit=take_profit,
    )
