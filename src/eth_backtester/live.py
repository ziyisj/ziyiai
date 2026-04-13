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
    chart_candles = _tick_synced_candles(candles, latest_price, latest_price_ts, args.okx_bar)
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
