from __future__ import annotations

import threading
from argparse import Namespace

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
    snapshot = _build_snapshot_from_candles(args, candles)
    latest_price = market_state.get("latest_price")
    latest_price_ts = market_state.get("latest_price_ts")
    realtime = {
        "latest_price": candles[-1].close if latest_price is None else latest_price,
        "latest_price_ts": candles[-1].timestamp.isoformat() if latest_price_ts is None else latest_price_ts,
        "latest_candle_close": candles[-1].close,
        "status": market_state.get("status") or "unknown",
        "last_error": market_state.get("last_error"),
        "transport": "okx_ws_public",
    }
    return candles, snapshot, realtime


def build_okx_live_snapshot_bundle(args: Namespace) -> tuple[list[Candle], SignalSnapshot]:
    candles, snapshot, _realtime = build_okx_live_dashboard_bundle(args)
    return candles, snapshot


def build_okx_live_signal_snapshot(args: Namespace) -> SignalSnapshot:
    _, snapshot = build_okx_live_snapshot_bundle(args)
    return snapshot
