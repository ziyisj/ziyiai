from __future__ import annotations

from argparse import Namespace

from .backtest import BacktestConfig
from .download import fetch_eth_ohlcv_from_okx
from .signals import build_signal_snapshot
from .strategy import build_strategy


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


def build_okx_live_signal_snapshot(args: Namespace):
    candles = fetch_eth_ohlcv_from_okx(
        inst_id=args.okx_inst_id,
        bar=args.okx_bar,
        candles_limit=args.okx_candles,
    )
    strategy = build_strategy(args.strategy, args)
    signals = strategy.generate_signals(candles)
    return build_signal_snapshot(
        strategy_name=strategy.name,
        candles=candles,
        signals=signals,
        config=_build_backtest_config(args),
        recent_trades=args.recent_trades,
    )
