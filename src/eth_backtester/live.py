from __future__ import annotations

import threading
from argparse import Namespace
from datetime import datetime, timedelta

from .backtest import BacktestConfig
from .download import fetch_eth_ohlcv_from_okx
from .okx_ws_public import OKXPublicRealtimeFeed
from .signals import SignalSnapshot, build_signal_snapshot
from .strategy import build_strategy
from .models import Candle

_FEEDS: dict[tuple[str, str, int], OKXPublicRealtimeFeed] = {}
_FEEDS_LOCK = threading.Lock()


def _bar_multiplier(bar: str) -> int:
    value = bar.strip()
    if value.endswith("m"):
        return int(value[:-1])
    if value.endswith("H"):
        return int(value[:-1]) * 60
    if value.endswith("D"):
        return int(value[:-1]) * 1440
    raise ValueError(f"Unsupported bar interval: {bar}")


def _build_backtest_config(args: Namespace) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
        position_size_pct=args.position_size_pct,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        max_hold_candles=args.max_hold_candles,
    )


def _build_snapshot_from_candles(args: Namespace, candles: list[Candle]) -> SignalSnapshot:
    strategy = build_strategy(args.strategy, args)
    signals = strategy.generate_signals(candles)
    return build_signal_snapshot(
        strategy_name=strategy.name,
        candles=candles,
        signals=signals,
        config=_build_backtest_config(args),
        recent_trades=args.recent_trades,
        timeframe=getattr(args, "okx_bar", "15m"),
    )


def _bar_timedelta(bar: str) -> timedelta:
    value = bar.strip()
    if value.endswith("m"):
        return timedelta(minutes=int(value[:-1]))
    if value.endswith("H"):
        return timedelta(hours=int(value[:-1]))
    if value.endswith("D"):
        return timedelta(days=int(value[:-1]))
    raise ValueError(f"Unsupported bar interval: {bar}")


def _bucket_start(timestamp: datetime, bar: str) -> datetime:
    delta = _bar_timedelta(bar)
    epoch = datetime(1970, 1, 1)
    total_seconds = int((timestamp - epoch).total_seconds())
    bucket_seconds = int(delta.total_seconds())
    bucket_floor = total_seconds - (total_seconds % bucket_seconds)
    return epoch + timedelta(seconds=bucket_floor)


def _aggregate_candles_to_bar(candles: list[Candle], bar: str) -> list[Candle]:
    if not candles:
        return []
    aggregated: list[Candle] = []
    current: Candle | None = None
    current_bucket: datetime | None = None
    for candle in sorted(candles, key=lambda item: item.timestamp):
        bucket = _bucket_start(candle.timestamp, bar)
        if current is None or bucket != current_bucket:
            if current is not None:
                aggregated.append(current)
            current_bucket = bucket
            current = Candle(
                timestamp=bucket,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
            continue
        current = Candle(
            timestamp=current.timestamp,
            open=current.open,
            high=max(current.high, candle.high),
            low=min(current.low, candle.low),
            close=candle.close,
            volume=current.volume + candle.volume,
        )
    if current is not None:
        aggregated.append(current)
    return aggregated


def _overlay_current_bar_from_1m(candles: list[Candle], one_minute_candles: list[Candle], bar: str, candles_limit: int) -> list[Candle]:
    if not candles or not one_minute_candles or bar == "1m":
        return candles
    aggregated = _aggregate_candles_to_bar(one_minute_candles, bar)
    if not aggregated:
        return candles

    result = list(candles)
    latest = aggregated[-1]
    if result and latest.timestamp == result[-1].timestamp:
        result[-1] = latest
    elif result and latest.timestamp > result[-1].timestamp:
        result.append(latest)
        result = result[-candles_limit:]
    return result


def _tick_synced_candles(candles: list[Candle], latest_price: float | None, latest_price_ts: str | None, bar: str) -> list[Candle]:
    if not candles or latest_price is None:
        return candles
    tick_time = None
    if latest_price_ts:
        try:
            tick_time = datetime.fromisoformat(latest_price_ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            tick_time = None
    last_candle = candles[-1]
    bar_delta = _bar_timedelta(bar)
    next_bar_time = last_candle.timestamp + bar_delta
    if tick_time is not None and tick_time >= next_bar_time:
        provisional = Candle(
            timestamp=next_bar_time,
            open=last_candle.close,
            high=max(last_candle.close, latest_price),
            low=min(last_candle.close, latest_price),
            close=latest_price,
            volume=0.0,
        )
        return [*candles[1:], provisional] if len(candles) >= 300 else [*candles, provisional]
    merged = Candle(
        timestamp=last_candle.timestamp,
        open=last_candle.open,
        high=max(last_candle.high, latest_price),
        low=min(last_candle.low, latest_price),
        close=latest_price,
        volume=last_candle.volume,
    )
    return [*candles[:-1], merged]


def get_okx_realtime_feed(args: Namespace) -> OKXPublicRealtimeFeed:
    key = (args.okx_inst_id, args.okx_bar, args.okx_candles)
    with _FEEDS_LOCK:
        feed = _FEEDS.get(key)
        if feed is None:
            feed = OKXPublicRealtimeFeed(inst_id=args.okx_inst_id, bar=args.okx_bar, candles_limit=args.okx_candles)
            _FEEDS[key] = feed
        return feed


def _get_feed(inst_id: str, bar: str, candles_limit: int) -> OKXPublicRealtimeFeed:
    key = (inst_id, bar, candles_limit)
    with _FEEDS_LOCK:
        feed = _FEEDS.get(key)
        if feed is None:
            feed = OKXPublicRealtimeFeed(inst_id=inst_id, bar=bar, candles_limit=candles_limit)
            _FEEDS[key] = feed
        return feed


def build_okx_live_dashboard_bundle(args: Namespace) -> tuple[list[Candle], SignalSnapshot, dict]:
    feed = get_okx_realtime_feed(args)
    market_state = feed.snapshot()
    candles = market_state["candles"]
    if not candles:
        candles = fetch_eth_ohlcv_from_okx(
            inst_id=args.okx_inst_id,
            bar=args.okx_bar,
            candles_limit=args.okx_candles,
        )
        market_state = {
            **market_state,
            "candles": candles,
            "status": "fallback_rest",
            "transport": "okx_rest_seed",
        }
    latest_price = market_state.get("latest_price")
    latest_price_ts = market_state.get("latest_price_ts")
    chart_candles = candles
    if args.okx_bar != "1m":
        one_minute_limit = max(args.okx_candles * _bar_multiplier(args.okx_bar), 120)
        one_minute_feed = _get_feed(args.okx_inst_id, "1m", one_minute_limit)
        one_minute_state = one_minute_feed.snapshot()
        chart_candles = _overlay_current_bar_from_1m(candles, one_minute_state.get("candles") or [], args.okx_bar, args.okx_candles)
    chart_candles = _tick_synced_candles(chart_candles, latest_price, latest_price_ts, args.okx_bar)
    snapshot = _build_snapshot_from_candles(args, chart_candles)
    realtime = {
        "latest_price": chart_candles[-1].close if latest_price is None else latest_price,
        "latest_price_ts": candles[-1].timestamp.isoformat() if latest_price_ts is None else latest_price_ts,
        "latest_candle_close": candles[-1].close,
        "status": market_state.get("status") or "unknown",
        "last_error": market_state.get("last_error"),
        "transport": "okx_ws_public",
    }
    return chart_candles, snapshot, realtime


def build_okx_live_snapshot_bundle(args: Namespace) -> tuple[list[Candle], SignalSnapshot]:
    candles, snapshot, _realtime = build_okx_live_dashboard_bundle(args)
    return candles, snapshot


def build_okx_live_signal_snapshot(args: Namespace) -> SignalSnapshot:
    _, snapshot = build_okx_live_snapshot_bundle(args)
    return snapshot
