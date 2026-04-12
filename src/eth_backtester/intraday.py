from __future__ import annotations

from datetime import datetime

from .models import Candle


def candle_minute_of_day(timestamp: datetime) -> int:
    return timestamp.hour * 60 + timestamp.minute


def is_in_session(timestamp: datetime, start_hour: int, end_hour: int) -> bool:
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        raise ValueError("session hours must be between 0 and 23")
    minute = candle_minute_of_day(timestamp)
    start_minute = start_hour * 60
    end_minute = end_hour * 60
    if start_hour <= end_hour:
        return start_minute <= minute <= end_minute
    return minute >= start_minute or minute <= end_minute


def aggregate_candles_by_hours(candles: list[Candle], hours: int = 1) -> list[Candle]:
    if hours <= 0:
        raise ValueError("hours must be positive")
    if not candles:
        return []

    buckets: dict[datetime, list[Candle]] = {}
    for candle in candles:
        bucket_hour = (candle.timestamp.hour // hours) * hours
        bucket_start = candle.timestamp.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket_start, []).append(candle)

    aggregated: list[Candle] = []
    for bucket_start in sorted(buckets.keys()):
        bucket = buckets[bucket_start]
        aggregated.append(
            Candle(
                timestamp=bucket_start,
                open=bucket[0].open,
                high=max(item.high for item in bucket),
                low=min(item.low for item in bucket),
                close=bucket[-1].close,
                volume=sum(item.volume for item in bucket),
            )
        )
    return aggregated


def align_higher_timeframe_values(
    lower_candles: list[Candle],
    higher_candles: list[Candle],
    higher_values: list[float | None],
    hours: int = 1,
) -> list[float | None]:
    if len(higher_candles) != len(higher_values):
        raise ValueError("higher_candles and higher_values must match in length")
    bucket_to_value = {
        candle.timestamp: value for candle, value in zip(higher_candles, higher_values)
    }
    aligned: list[float | None] = []
    for candle in lower_candles:
        bucket_hour = (candle.timestamp.hour // hours) * hours
        bucket_start = candle.timestamp.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)
        aligned.append(bucket_to_value.get(bucket_start))
    return aligned
