from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from threading import Lock

from .backtest import BacktestConfig
from .download import fetch_eth_ohlcv_from_okx
from .okx_ws_public import OKXPublicWebSocketClient
from .signals import SignalSnapshot, build_signal_snapshot
from .strategy import build_strategy
from .models import Candle


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


_WS_CLIENTS: dict[tuple[str, str, int], OKXPublicWebSocketClient] = {}
_WS_LOCK = Lock()


def _get_or_create_ws_client(args: Namespace, seed_candles: list[Candle]) -> OKXPublicWebSocketClient:
    key = (args.okx_inst_id, args.okx_bar, args.okx_candles)
    with _WS_LOCK:
        client = _WS_CLIENTS.get(key)
        if client is None:
            client = OKXPublicWebSocketClient(args.okx_inst_id, args.okx_bar, max_candles=args.okx_candles)
            client.set_seed_candles(seed_candles)
            client.start()
            _WS_CLIENTS[key] = client
        else:
            if not (client.get_snapshot().candles or []):
                client.set_seed_candles(seed_candles)
        return client


def _merge_realtime_price(candles: list[Candle], latest_price: float | None) -> list[Candle]:
    if not candles or latest_price is None:
        return candles
    last = candles[-1]
    merged_last = Candle(
        timestamp=last.timestamp,
        open=last.open,
        high=max(last.high, latest_price),
        low=min(last.low, latest_price),
        close=latest_price,
        volume=last.volume,
    )
    return [*candles[:-1], merged_last]


def build_okx_live_snapshot_bundle(args: Namespace) -> tuple[list[Candle], SignalSnapshot]:
    rest_candles = fetch_eth_ohlcv_from_okx(
        inst_id=args.okx_inst_id,
        bar=args.okx_bar,
        candles_limit=args.okx_candles,
    )
    client = _get_or_create_ws_client(args, rest_candles)
    ws_snapshot = client.get_snapshot()
    candles = ws_snapshot.candles or rest_candles
    candles = _merge_realtime_price(candles, ws_snapshot.latest_price)
    strategy = build_strategy(args.strategy, args)
    signals = strategy.generate_signals(candles)
    snapshot = build_signal_snapshot(
        strategy_name=strategy.name,
        candles=candles,
        signals=signals,
        config=_build_backtest_config(args),
        recent_trades=args.recent_trades,
        timeframe=getattr(args, "okx_bar", "15m"),
    )
    if ws_snapshot.latest_price is not None:
        snapshot = replace(snapshot, latest_close=round(ws_snapshot.latest_price, 6))
    return candles, snapshot


def build_okx_live_signal_snapshot(args: Namespace) -> SignalSnapshot:
    _, snapshot = build_okx_live_snapshot_bundle(args)
    return snapshot
