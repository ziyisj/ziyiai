from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .indicators import (
    average_true_range,
    exponential_moving_average,
    relative_strength_index,
    rolling_high,
    rolling_low,
    simple_moving_average,
)
from .intraday import aggregate_candles_by_hours, align_higher_timeframe_values, is_in_session
from .models import Candle, Signal


class Strategy(Protocol):
    name: str

    def generate_signals(self, candles: list[Candle]) -> list[Signal]:
        ...


@dataclass(frozen=True)
class MovingAverageCrossStrategy:
    fast_window: int = 8
    slow_window: int = 21
    name: str = "ma_cross"

    def __post_init__(self) -> None:
        if self.fast_window <= 0 or self.slow_window <= 0:
            raise ValueError("moving average windows must be positive")
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be less than slow_window")

    def generate_signals(self, candles: list[Candle]) -> list[Signal]:
        closes = [candle.close for candle in candles]
        fast = simple_moving_average(closes, self.fast_window)
        slow = simple_moving_average(closes, self.slow_window)

        signals: list[Signal] = []
        previous_fast: float | None = None
        previous_slow: float | None = None

        for candle, fast_value, slow_value in zip(candles, fast, slow):
            action = "hold"
            reason = "waiting_for_indicators"

            if fast_value is not None and slow_value is not None:
                reason = "trend_unchanged"
                if previous_fast is not None and previous_slow is not None:
                    crossed_up = previous_fast <= previous_slow and fast_value > slow_value
                    crossed_down = previous_fast >= previous_slow and fast_value < slow_value
                    if crossed_up:
                        action = "buy"
                        reason = "fast_crossed_above_slow"
                    elif crossed_down:
                        action = "sell"
                        reason = "fast_crossed_below_slow"
                previous_fast = fast_value
                previous_slow = slow_value

            signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))

        return signals


@dataclass(frozen=True)
class RSIMeanReversionStrategy:
    window: int = 14
    oversold: float = 35.0
    overbought: float = 65.0
    name: str = "rsi"

    def __post_init__(self) -> None:
        if self.window <= 1:
            raise ValueError("RSI window must be greater than 1")
        if not 0 < self.oversold < self.overbought < 100:
            raise ValueError("RSI thresholds must satisfy 0 < oversold < overbought < 100")

    def generate_signals(self, candles: list[Candle]) -> list[Signal]:
        closes = [candle.close for candle in candles]
        rsi_values = relative_strength_index(closes, self.window)
        signals: list[Signal] = []
        in_position = False

        for candle, rsi_value in zip(candles, rsi_values):
            action = "hold"
            reason = "waiting_for_indicators"
            if rsi_value is not None:
                reason = "rsi_neutral"
                if not in_position and rsi_value <= self.oversold:
                    action = "buy"
                    reason = "rsi_oversold"
                    in_position = True
                elif in_position and rsi_value >= self.overbought:
                    action = "sell"
                    reason = "rsi_overbought"
                    in_position = False
            signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
        return signals


@dataclass(frozen=True)
class MACDStrategy:
    fast_window: int = 12
    slow_window: int = 26
    signal_window: int = 9
    name: str = "macd"

    def __post_init__(self) -> None:
        if min(self.fast_window, self.slow_window, self.signal_window) <= 0:
            raise ValueError("MACD windows must be positive")
        if self.fast_window >= self.slow_window:
            raise ValueError("MACD fast_window must be less than slow_window")

    def generate_signals(self, candles: list[Candle]) -> list[Signal]:
        closes = [candle.close for candle in candles]
        fast = exponential_moving_average(closes, self.fast_window)
        slow = exponential_moving_average(closes, self.slow_window)

        macd_line: list[float | None] = []
        valid_macd_values: list[float] = []
        for fast_value, slow_value in zip(fast, slow):
            if fast_value is None or slow_value is None:
                macd_line.append(None)
            else:
                value = fast_value - slow_value
                macd_line.append(value)
                valid_macd_values.append(value)

        signal_only = exponential_moving_average(valid_macd_values, self.signal_window)
        signal_line: list[float | None] = []
        signal_index = 0
        for value in macd_line:
            if value is None:
                signal_line.append(None)
            else:
                signal_line.append(signal_only[signal_index])
                signal_index += 1

        signals: list[Signal] = []
        previous_macd: float | None = None
        previous_signal: float | None = None

        for candle, macd_value, signal_value in zip(candles, macd_line, signal_line):
            action = "hold"
            reason = "waiting_for_indicators"
            if macd_value is not None and signal_value is not None:
                reason = "macd_neutral"
                if previous_macd is None or previous_signal is None:
                    if macd_value > signal_value:
                        action = "buy"
                        reason = "macd_above_signal"
                    elif macd_value < signal_value:
                        action = "sell"
                        reason = "macd_below_signal"
                else:
                    crossed_up = previous_macd <= previous_signal and macd_value > signal_value
                    crossed_down = previous_macd >= previous_signal and macd_value < signal_value
                    if crossed_up:
                        action = "buy"
                        reason = "macd_crossed_above_signal"
                    elif crossed_down:
                        action = "sell"
                        reason = "macd_crossed_below_signal"
                previous_macd = macd_value
                previous_signal = signal_value
            signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
        return signals


@dataclass(frozen=True)
class BreakoutStrategy:
    lookback: int = 20
    exit_lookback: int = 10
    name: str = "breakout"

    def __post_init__(self) -> None:
        if self.lookback <= 1 or self.exit_lookback <= 1:
            raise ValueError("breakout windows must be greater than 1")

    def generate_signals(self, candles: list[Candle]) -> list[Signal]:
        closes = [candle.close for candle in candles]
        rolling_entry = rolling_high(closes, self.lookback)
        rolling_exit = rolling_low(closes, self.exit_lookback)
        signals: list[Signal] = []
        in_position = False

        for candle, entry_high, exit_low in zip(candles, rolling_entry, rolling_exit):
            action = "hold"
            reason = "waiting_for_indicators"
            if entry_high is not None and exit_low is not None:
                reason = "inside_breakout_range"
                if not in_position and candle.close > entry_high:
                    action = "buy"
                    reason = "close_broke_recent_high"
                    in_position = True
                elif in_position and candle.close < exit_low:
                    action = "sell"
                    reason = "close_broke_recent_low"
                    in_position = False
            signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
        return signals


@dataclass(frozen=True)
class OKX15mIntradayStrategy:
    fast_window: int = 20
    slow_window: int = 50
    rsi_window: int = 7
    pullback_threshold: float = 38.0
    exit_rsi: float = 58.0
    atr_window: int = 14
    min_atr_pct: float = 0.002
    max_atr_pct: float = 0.025
    session_start_hour: int = 6
    session_end_hour: int = 22
    cooldown_candles: int = 4
    name: str = "okx_15m_intraday"

    def __post_init__(self) -> None:
        if self.fast_window <= 0 or self.slow_window <= 0 or self.fast_window >= self.slow_window:
            raise ValueError("intraday fast_window must be positive and less than slow_window")
        if self.rsi_window <= 1:
            raise ValueError("intraday rsi_window must be greater than 1")
        if not 0 < self.pullback_threshold < self.exit_rsi < 100:
            raise ValueError("intraday RSI thresholds must satisfy 0 < pullback < exit < 100")
        if self.atr_window <= 0:
            raise ValueError("atr_window must be positive")
        if not 0 <= self.min_atr_pct < self.max_atr_pct:
            raise ValueError("ATR percentage thresholds are invalid")
        if self.cooldown_candles < 0:
            raise ValueError("cooldown_candles must be non-negative")

    def generate_signals(self, candles: list[Candle]) -> list[Signal]:
        closes = [candle.close for candle in candles]
        fast = simple_moving_average(closes, self.fast_window)
        slow = simple_moving_average(closes, self.slow_window)
        rsi_values = relative_strength_index(closes, self.rsi_window)
        atr_values = average_true_range(candles, self.atr_window)

        signals: list[Signal] = []
        in_position = False
        cooldown_remaining = 0

        for candle, fast_value, slow_value, rsi_value, atr_value in zip(candles, fast, slow, rsi_values, atr_values):
            action = "hold"
            reason = "waiting_for_indicators"
            in_session = is_in_session(candle.timestamp, self.session_start_hour, self.session_end_hour)

            if not in_session:
                if in_position:
                    action = "sell"
                    reason = "session_exit"
                    in_position = False
                    cooldown_remaining = self.cooldown_candles
                else:
                    reason = "outside_session"
                signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
                continue

            if cooldown_remaining > 0:
                cooldown_remaining -= 1
                reason = "cooldown"
                signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
                continue

            if fast_value is not None and slow_value is not None and rsi_value is not None and atr_value is not None:
                atr_pct = atr_value / candle.close if candle.close else 0.0
                trend_up = fast_value > slow_value
                volatility_ok = self.min_atr_pct <= atr_pct <= self.max_atr_pct
                if not in_position:
                    reason = "intraday_entry_not_ready"
                    if trend_up and volatility_ok and rsi_value <= self.pullback_threshold:
                        action = "buy"
                        reason = "trend_pullback_entry"
                        in_position = True
                else:
                    reason = "intraday_hold"
                    if candle.close < fast_value:
                        action = "sell"
                        reason = "lost_fast_trend"
                        in_position = False
                        cooldown_remaining = self.cooldown_candles
                    elif rsi_value >= self.exit_rsi:
                        action = "sell"
                        reason = "mean_reversion_exit"
                        in_position = False
                        cooldown_remaining = self.cooldown_candles
                    elif not volatility_ok:
                        action = "sell"
                        reason = "volatility_exit"
                        in_position = False
                        cooldown_remaining = self.cooldown_candles
            signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))

        return signals


@dataclass(frozen=True)
class MultiTimeframe15mStrategy:
    trend_fast_window: int = 6
    trend_slow_window: int = 12
    trigger_fast_window: int = 8
    trigger_slow_window: int = 21
    trigger_signal_window: int = 5
    entry_rsi_window: int = 7
    entry_rsi_threshold: float = 55.0
    exit_rsi: float = 68.0
    atr_window: int = 10
    min_atr_pct: float = 0.002
    max_atr_pct: float = 0.02
    session_start_hour: int = 6
    session_end_hour: int = 22
    cooldown_candles: int = 2
    name: str = "okx_15m_mtf"

    def __post_init__(self) -> None:
        if self.trend_fast_window <= 0 or self.trend_slow_window <= 0:
            raise ValueError("trend windows must be positive")
        if self.trend_fast_window >= self.trend_slow_window:
            raise ValueError("trend_fast_window must be less than trend_slow_window")
        if min(self.trigger_fast_window, self.trigger_slow_window, self.trigger_signal_window) <= 0:
            raise ValueError("trigger MACD windows must be positive")
        if self.trigger_fast_window >= self.trigger_slow_window:
            raise ValueError("trigger_fast_window must be less than trigger_slow_window")
        if self.entry_rsi_window <= 1:
            raise ValueError("entry_rsi_window must be greater than 1")
        if not 0 < self.entry_rsi_threshold < self.exit_rsi < 100:
            raise ValueError("RSI thresholds must satisfy 0 < entry < exit < 100")
        if self.atr_window <= 0:
            raise ValueError("atr_window must be positive")
        if not 0 <= self.min_atr_pct < self.max_atr_pct:
            raise ValueError("ATR percentage thresholds are invalid")
        if self.cooldown_candles < 0:
            raise ValueError("cooldown_candles must be non-negative")

    def generate_signals(self, candles: list[Candle]) -> list[Signal]:
        closes = [candle.close for candle in candles]
        lower_rsi = relative_strength_index(closes, self.entry_rsi_window)
        lower_atr = average_true_range(candles, self.atr_window)

        fast = exponential_moving_average(closes, self.trigger_fast_window)
        slow = exponential_moving_average(closes, self.trigger_slow_window)
        macd_line: list[float | None] = []
        valid_macd_values: list[float] = []
        for fast_value, slow_value in zip(fast, slow):
            if fast_value is None or slow_value is None:
                macd_line.append(None)
            else:
                value = fast_value - slow_value
                macd_line.append(value)
                valid_macd_values.append(value)
        signal_only = exponential_moving_average(valid_macd_values, self.trigger_signal_window)
        signal_line: list[float | None] = []
        signal_index = 0
        for value in macd_line:
            if value is None:
                signal_line.append(None)
            else:
                signal_line.append(signal_only[signal_index])
                signal_index += 1

        higher_candles = aggregate_candles_by_hours(candles, hours=1)
        higher_closes = [candle.close for candle in higher_candles]
        higher_fast = simple_moving_average(higher_closes, self.trend_fast_window)
        higher_slow = simple_moving_average(higher_closes, self.trend_slow_window)
        aligned_higher_fast = align_higher_timeframe_values(candles, higher_candles, higher_fast, hours=1)
        aligned_higher_slow = align_higher_timeframe_values(candles, higher_candles, higher_slow, hours=1)

        signals: list[Signal] = []
        in_position = False
        cooldown_remaining = 0
        previous_macd: float | None = None
        previous_signal: float | None = None
        previous_rsi: float | None = None

        for candle, rsi_value, atr_value, macd_value, signal_value, higher_fast_value, higher_slow_value in zip(
            candles,
            lower_rsi,
            lower_atr,
            macd_line,
            signal_line,
            aligned_higher_fast,
            aligned_higher_slow,
        ):
            action = "hold"
            reason = "waiting_for_indicators"
            in_session = is_in_session(candle.timestamp, self.session_start_hour, self.session_end_hour)

            if not in_session:
                if in_position:
                    action = "sell"
                    reason = "session_exit"
                    in_position = False
                    cooldown_remaining = self.cooldown_candles
                else:
                    reason = "outside_session"
                signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
                previous_macd = macd_value
                previous_signal = signal_value
                previous_rsi = rsi_value
                continue

            if cooldown_remaining > 0:
                cooldown_remaining -= 1
                reason = "cooldown"
                signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
                previous_macd = macd_value
                previous_signal = signal_value
                previous_rsi = rsi_value
                continue

            if None not in (rsi_value, atr_value, macd_value, signal_value, higher_fast_value, higher_slow_value):
                atr_pct = atr_value / candle.close if candle.close else 0.0
                trend_up = float(higher_fast_value) > float(higher_slow_value)
                volatility_ok = self.min_atr_pct <= atr_pct <= self.max_atr_pct
                crossed_up = (
                    previous_macd is not None
                    and previous_signal is not None
                    and previous_macd <= previous_signal
                    and float(macd_value) > float(signal_value)
                )
                crossed_down = (
                    previous_macd is not None
                    and previous_signal is not None
                    and previous_macd >= previous_signal
                    and float(macd_value) < float(signal_value)
                )
                rsi_recovered = previous_rsi is not None and previous_rsi <= self.entry_rsi_threshold < float(rsi_value)
                macd_supportive = float(macd_value) > float(signal_value)
                rsi_reasonable = float(rsi_value) <= self.exit_rsi
                momentum_reentry = previous_rsi is not None and previous_rsi < float(rsi_value) <= self.exit_rsi
                if not in_position:
                    reason = "mtf_entry_not_ready"
                    if trend_up and volatility_ok and ((crossed_up and rsi_reasonable) or (rsi_recovered and macd_supportive) or (momentum_reentry and macd_supportive)):
                        action = "buy"
                        reason = "mtf_trend_trigger_entry"
                        in_position = True
                else:
                    reason = "mtf_hold"
                    if crossed_down:
                        action = "sell"
                        reason = "trigger_cross_down"
                        in_position = False
                        cooldown_remaining = self.cooldown_candles
                    elif float(rsi_value) >= self.exit_rsi:
                        action = "sell"
                        reason = "rsi_exit"
                        in_position = False
                        cooldown_remaining = self.cooldown_candles
                    elif not trend_up:
                        action = "sell"
                        reason = "higher_timeframe_trend_lost"
                        in_position = False
                        cooldown_remaining = self.cooldown_candles
                    elif not volatility_ok:
                        action = "sell"
                        reason = "volatility_exit"
                        in_position = False
                        cooldown_remaining = self.cooldown_candles

            signals.append(Signal(timestamp=candle.timestamp, action=action, reason=reason))
            previous_macd = macd_value
            previous_signal = signal_value
            previous_rsi = rsi_value

        return signals


def build_strategy(name: str, args: object | None = None) -> Strategy:
    strategy_name = name.lower()
    args = args or object()
    if strategy_name == "ma_cross":
        return MovingAverageCrossStrategy(
            fast_window=getattr(args, "fast_window", 8),
            slow_window=getattr(args, "slow_window", 21),
        )
    if strategy_name == "rsi":
        return RSIMeanReversionStrategy(
            window=getattr(args, "rsi_window", 14),
            oversold=getattr(args, "rsi_oversold", 35.0),
            overbought=getattr(args, "rsi_overbought", 65.0),
        )
    if strategy_name == "macd":
        return MACDStrategy(
            fast_window=getattr(args, "macd_fast_window", 12),
            slow_window=getattr(args, "macd_slow_window", 26),
            signal_window=getattr(args, "macd_signal_window", 9),
        )
    if strategy_name == "breakout":
        return BreakoutStrategy(
            lookback=getattr(args, "breakout_lookback", 20),
            exit_lookback=getattr(args, "breakout_exit_lookback", 10),
        )
    if strategy_name == "okx_15m_intraday":
        return OKX15mIntradayStrategy(
            fast_window=getattr(args, "intraday_fast_window", 20),
            slow_window=getattr(args, "intraday_slow_window", 50),
            rsi_window=getattr(args, "intraday_rsi_window", 7),
            pullback_threshold=getattr(args, "intraday_pullback_threshold", 38.0),
            exit_rsi=getattr(args, "intraday_exit_rsi", 58.0),
            atr_window=getattr(args, "intraday_atr_window", 14),
            min_atr_pct=getattr(args, "intraday_min_atr_pct", 0.002),
            max_atr_pct=getattr(args, "intraday_max_atr_pct", 0.025),
            session_start_hour=getattr(args, "session_start_hour", 6),
            session_end_hour=getattr(args, "session_end_hour", 22),
            cooldown_candles=getattr(args, "intraday_cooldown_candles", 4),
        )
    if strategy_name == "okx_15m_mtf":
        return MultiTimeframe15mStrategy(
            trend_fast_window=getattr(args, "mtf_trend_fast_window", 6),
            trend_slow_window=getattr(args, "mtf_trend_slow_window", 12),
            trigger_fast_window=getattr(args, "mtf_trigger_fast_window", 8),
            trigger_slow_window=getattr(args, "mtf_trigger_slow_window", 21),
            trigger_signal_window=getattr(args, "mtf_trigger_signal_window", 5),
            entry_rsi_window=getattr(args, "mtf_entry_rsi_window", 7),
            entry_rsi_threshold=getattr(args, "mtf_entry_rsi_threshold", 55.0),
            exit_rsi=getattr(args, "mtf_exit_rsi", 68.0),
            atr_window=getattr(args, "mtf_atr_window", 10),
            min_atr_pct=getattr(args, "mtf_min_atr_pct", 0.002),
            max_atr_pct=getattr(args, "mtf_max_atr_pct", 0.02),
            session_start_hour=getattr(args, "session_start_hour", 6),
            session_end_hour=getattr(args, "session_end_hour", 22),
            cooldown_candles=getattr(args, "intraday_cooldown_candles", 2),
        )
    raise ValueError(f"Unknown strategy: {name}")


def available_strategies() -> list[str]:
    return ["ma_cross", "rsi", "macd", "breakout", "okx_15m_intraday", "okx_15m_mtf"]
