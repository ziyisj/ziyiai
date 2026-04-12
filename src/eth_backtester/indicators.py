from __future__ import annotations

from .models import Candle


def simple_moving_average(values: list[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    averages: list[float | None] = []
    running_sum = 0.0
    for index, value in enumerate(values):
        running_sum += value
        if index >= window:
            running_sum -= values[index - window]
        if index + 1 < window:
            averages.append(None)
        else:
            averages.append(running_sum / window)
    return averages


def exponential_moving_average(values: list[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    ema_values: list[float | None] = []
    multiplier = 2.0 / (window + 1)
    seed = simple_moving_average(values, window)
    previous_ema: float | None = None

    for index, value in enumerate(values):
        seed_value = seed[index]
        if seed_value is None:
            ema_values.append(None)
            continue
        if previous_ema is None:
            previous_ema = seed_value
        else:
            previous_ema = ((value - previous_ema) * multiplier) + previous_ema
        ema_values.append(previous_ema)
    return ema_values


def relative_strength_index(values: list[float], window: int = 14) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < 2:
        return [None for _ in values]

    rsi_values: list[float | None] = [None]
    gains: list[float] = []
    losses: list[float] = []
    average_gain: float | None = None
    average_loss: float | None = None

    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = abs(min(change, 0.0))
        gains.append(gain)
        losses.append(loss)

        if index < window:
            rsi_values.append(None)
            continue

        if index == window:
            average_gain = sum(gains) / window
            average_loss = sum(losses) / window
        else:
            assert average_gain is not None and average_loss is not None
            average_gain = ((average_gain * (window - 1)) + gain) / window
            average_loss = ((average_loss * (window - 1)) + loss) / window

        if average_loss == 0:
            rsi_values.append(100.0)
            continue

        relative_strength = average_gain / average_loss
        rsi = 100.0 - (100.0 / (1.0 + relative_strength))
        rsi_values.append(rsi)

    return rsi_values


def average_true_range(candles: list[Candle], window: int = 14) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    if not candles:
        return []

    true_ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        if previous_close is None:
            true_range = candle.high - candle.low
        else:
            true_range = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        true_ranges.append(true_range)
        previous_close = candle.close
    return simple_moving_average(true_ranges, window)


def rolling_high(values: list[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    highs: list[float | None] = []
    for index in range(len(values)):
        if index < window:
            highs.append(None)
        else:
            highs.append(max(values[index - window : index]))
    return highs


def rolling_low(values: list[float], window: int) -> list[float | None]:
    if window <= 0:
        raise ValueError("window must be positive")
    lows: list[float | None] = []
    for index in range(len(values)):
        if index < window:
            lows.append(None)
        else:
            lows.append(min(values[index - window : index]))
    return lows
