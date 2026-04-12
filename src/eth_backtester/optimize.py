from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from itertools import product

from .backtest import BacktestConfig, BacktestEngine
from .models import BacktestResult, Candle
from .strategy import available_strategies, build_strategy


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


@dataclass(frozen=True)
class OptimizationResult:
    strategy_name: str
    parameters: dict[str, int | float]
    result: BacktestResult


def _parameter_grid(strategy_name: str, include_risk: bool = False) -> dict[str, list[int | float | None]]:
    if strategy_name == "ma_cross":
        grid: dict[str, list[int | float | None]] = {
            "fast_window": [5, 8, 10, 12],
            "slow_window": [18, 21, 30, 40],
        }
    elif strategy_name == "rsi":
        grid = {
            "rsi_window": [7, 10, 14],
            "rsi_oversold": [25.0, 30.0, 35.0],
            "rsi_overbought": [65.0, 70.0, 75.0],
        }
    elif strategy_name == "macd":
        grid = {
            "macd_fast_window": [6, 8, 12],
            "macd_slow_window": [17, 21, 26],
            "macd_signal_window": [5, 7, 9],
        }
    elif strategy_name == "breakout":
        grid = {
            "breakout_lookback": [10, 15, 20, 30],
            "breakout_exit_lookback": [5, 10, 15],
        }
    elif strategy_name == "okx_15m_intraday":
        grid = {
            "intraday_fast_window": [16, 20, 24],
            "intraday_slow_window": [40, 50, 60],
            "intraday_rsi_window": [5, 7, 9],
            "intraday_pullback_threshold": [32.0, 35.0, 38.0],
            "intraday_exit_rsi": [55.0, 58.0, 62.0],
            "intraday_atr_window": [10, 14],
            "intraday_min_atr_pct": [0.0015, 0.002, 0.003],
            "intraday_max_atr_pct": [0.015, 0.02, 0.03],
            "session_start_hour": [6, 7, 8],
            "session_end_hour": [20, 22, 23],
            "intraday_cooldown_candles": [2, 4, 6],
        }
    elif strategy_name == "okx_15m_mtf":
        grid = {
            "mtf_trend_fast_window": [4, 6],
            "mtf_trend_slow_window": [10, 12],
            "mtf_trigger_fast_window": [6, 8],
            "mtf_trigger_slow_window": [17, 21],
            "mtf_trigger_signal_window": [5, 7],
            "mtf_entry_rsi_window": [7],
            "mtf_entry_rsi_threshold": [50.0, 55.0],
            "mtf_exit_rsi": [65.0, 68.0],
            "mtf_atr_window": [10],
            "mtf_min_atr_pct": [0.002],
            "mtf_max_atr_pct": [0.02],
            "session_start_hour": [6],
            "session_end_hour": [22],
            "intraday_cooldown_candles": [2],
        }
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    if include_risk:
        grid.update(
            {
                "position_size_pct": [0.5, 0.75, 1.0],
                "stop_loss_pct": [None, 0.03, 0.05, 0.08],
                "take_profit_pct": [None, 0.08, 0.12, 0.2],
                "max_hold_candles": [None, 12, 18, 24],
            }
        )
    return grid


def _valid_parameters(strategy_name: str, params: dict[str, int | float | None]) -> bool:
    if strategy_name == "ma_cross":
        if int(params["fast_window"]) >= int(params["slow_window"]):
            return False
    elif strategy_name == "rsi":
        if not 0 < float(params["rsi_oversold"]) < float(params["rsi_overbought"]) < 100:
            return False
    elif strategy_name == "macd":
        if int(params["macd_fast_window"]) >= int(params["macd_slow_window"]):
            return False
    elif strategy_name == "breakout":
        if int(params["breakout_exit_lookback"]) >= int(params["breakout_lookback"]):
            return False
    elif strategy_name == "okx_15m_intraday":
        if int(params["intraday_fast_window"]) >= int(params["intraday_slow_window"]):
            return False
        if not 0 < float(params["intraday_pullback_threshold"]) < float(params["intraday_exit_rsi"]) < 100:
            return False
        if not 0 <= float(params["intraday_min_atr_pct"]) < float(params["intraday_max_atr_pct"]):
            return False
    elif strategy_name == "okx_15m_mtf":
        if int(params["mtf_trend_fast_window"]) >= int(params["mtf_trend_slow_window"]):
            return False
        if int(params["mtf_trigger_fast_window"]) >= int(params["mtf_trigger_slow_window"]):
            return False
        if not 0 < float(params["mtf_entry_rsi_threshold"]) < float(params["mtf_exit_rsi"]) < 100:
            return False
        if not 0 <= float(params["mtf_min_atr_pct"]) < float(params["mtf_max_atr_pct"]):
            return False
    if "position_size_pct" in params and not 0 < float(params["position_size_pct"]) <= 1.0:
        return False
    stop_loss = params.get("stop_loss_pct")
    if stop_loss is not None and float(stop_loss) <= 0:
        return False
    take_profit = params.get("take_profit_pct")
    if take_profit is not None and float(take_profit) <= 0:
        return False
    max_hold = params.get("max_hold_candles")
    if max_hold is not None and int(max_hold) <= 0:
        return False
    return True


def _merge_namespace(args: Namespace, overrides: dict[str, int | float]) -> Namespace:
    merged = vars(args).copy()
    merged.update(overrides)
    return Namespace(**merged)


def optimize_strategy(
    candles: list[Candle],
    base_args: Namespace,
    strategy_name: str,
    top_n: int = 5,
    include_risk: bool = False,
) -> list[OptimizationResult]:
    if include_risk and strategy_name == "okx_15m_intraday":
        grid = {
            "intraday_fast_window": [base_args.intraday_fast_window],
            "intraday_slow_window": [base_args.intraday_slow_window],
            "intraday_rsi_window": [base_args.intraday_rsi_window],
            "intraday_pullback_threshold": [base_args.intraday_pullback_threshold],
            "intraday_exit_rsi": [base_args.intraday_exit_rsi],
            "intraday_atr_window": [base_args.intraday_atr_window],
            "intraday_min_atr_pct": [base_args.intraday_min_atr_pct],
            "intraday_max_atr_pct": [base_args.intraday_max_atr_pct],
            "session_start_hour": [base_args.session_start_hour],
            "session_end_hour": [base_args.session_end_hour],
            "intraday_cooldown_candles": [base_args.intraday_cooldown_candles],
            "position_size_pct": [0.5, 0.75, 1.0],
            "stop_loss_pct": [None, 0.02, 0.03, 0.05],
            "take_profit_pct": [None, 0.03, 0.05, 0.08],
            "max_hold_candles": [None, 8, 12, 16],
        }
    else:
        grid = _parameter_grid(strategy_name, include_risk=include_risk)
    keys = list(grid.keys())
    candidates: list[OptimizationResult] = []

    for values in product(*(grid[key] for key in keys)):
        params = dict(zip(keys, values))
        if not _valid_parameters(strategy_name, params):
            continue
        args = _merge_namespace(base_args, params)
        strategy = build_strategy(strategy_name, args)
        signals = strategy.generate_signals(candles)
        result = BacktestEngine(_build_backtest_config(args)).run(candles, signals)
        candidates.append(
            OptimizationResult(
                strategy_name=strategy_name,
                parameters=params,
                result=result,
            )
        )

    candidates.sort(
        key=lambda item: (
            item.result.metrics.final_equity if item.result.metrics else float("-inf"),
            -(item.result.metrics.max_drawdown_pct if item.result.metrics else float("inf")),
        ),
        reverse=True,
    )
    return candidates[:top_n]


def optimize_all_strategies(
    candles: list[Candle],
    base_args: Namespace,
    top_n: int = 3,
    include_risk: bool = False,
) -> dict[str, list[OptimizationResult]]:
    return {
        strategy_name: optimize_strategy(
            candles,
            base_args,
            strategy_name,
            top_n=top_n,
            include_risk=include_risk,
        )
        for strategy_name in available_strategies()
    }
