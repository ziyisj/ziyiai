from __future__ import annotations

from argparse import Namespace
from dataclasses import asdict, dataclass

from .backtest import BacktestConfig, BacktestEngine
from .models import BacktestResult, Candle
from .optimize import optimize_strategy
from .strategy import build_strategy


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    selected_parameters: dict[str, int | float | None]
    train_result: BacktestResult
    test_result: BacktestResult

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "selected_parameters": self.selected_parameters,
            "train_result": self.train_result.to_dict(),
            "test_result": self.test_result.to_dict(),
        }


@dataclass(frozen=True)
class WalkForwardSummary:
    strategy_name: str
    train_candles: int
    test_candles: int
    include_risk: bool
    windows: list[WalkForwardWindow]
    avg_train_return_pct: float
    avg_test_return_pct: float
    avg_test_max_drawdown_pct: float
    avg_test_sharpe_ratio: float
    profitable_test_windows: int
    total_test_windows: int
    compounded_test_return_pct: float

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "train_candles": self.train_candles,
            "test_candles": self.test_candles,
            "include_risk": self.include_risk,
            "windows": [window.to_dict() for window in self.windows],
            "avg_train_return_pct": self.avg_train_return_pct,
            "avg_test_return_pct": self.avg_test_return_pct,
            "avg_test_max_drawdown_pct": self.avg_test_max_drawdown_pct,
            "avg_test_sharpe_ratio": self.avg_test_sharpe_ratio,
            "profitable_test_windows": self.profitable_test_windows,
            "total_test_windows": self.total_test_windows,
            "compounded_test_return_pct": self.compounded_test_return_pct,
        }


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


def _merge_namespace(args: Namespace, overrides: dict[str, int | float | None]) -> Namespace:
    merged = vars(args).copy()
    merged.update(overrides)
    return Namespace(**merged)


def _run_backtest(candles: list[Candle], args: Namespace, strategy_name: str) -> BacktestResult:
    strategy = build_strategy(strategy_name, args)
    signals = strategy.generate_signals(candles)
    return BacktestEngine(_build_backtest_config(args)).run(candles, signals)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def walk_forward_validate(
    candles: list[Candle],
    base_args: Namespace,
    strategy_name: str,
    train_candles: int,
    test_candles: int,
    include_risk: bool = False,
    top_n: int = 1,
) -> WalkForwardSummary:
    if train_candles <= 0 or test_candles <= 0:
        raise ValueError("train_candles and test_candles must be positive")
    if len(candles) < train_candles + test_candles:
        raise ValueError("not enough candles for the requested walk-forward split")

    windows: list[WalkForwardWindow] = []
    start = 0
    compounded_growth = 1.0
    window_index = 1

    while start + train_candles + test_candles <= len(candles):
        train_slice = candles[start : start + train_candles]
        test_slice = candles[start + train_candles : start + train_candles + test_candles]
        ranked = optimize_strategy(
            train_slice,
            base_args,
            strategy_name,
            top_n=max(1, top_n),
            include_risk=include_risk,
        )
        if not ranked:
            break

        selected = ranked[0]
        selected_args = _merge_namespace(base_args, selected.parameters)
        train_result = _run_backtest(train_slice, selected_args, strategy_name)
        test_result = _run_backtest(test_slice, selected_args, strategy_name)
        test_metrics = test_result.metrics
        if test_metrics is not None:
            compounded_growth *= 1.0 + (test_metrics.total_return_pct / 100.0)

        windows.append(
            WalkForwardWindow(
                index=window_index,
                train_start=train_slice[0].timestamp.isoformat(),
                train_end=train_slice[-1].timestamp.isoformat(),
                test_start=test_slice[0].timestamp.isoformat(),
                test_end=test_slice[-1].timestamp.isoformat(),
                selected_parameters=selected.parameters,
                train_result=train_result,
                test_result=test_result,
            )
        )
        start += test_candles
        window_index += 1

    if not windows:
        raise ValueError("walk-forward validation produced no windows")

    train_returns = [window.train_result.metrics.total_return_pct for window in windows if window.train_result.metrics]
    test_returns = [window.test_result.metrics.total_return_pct for window in windows if window.test_result.metrics]
    test_drawdowns = [window.test_result.metrics.max_drawdown_pct for window in windows if window.test_result.metrics]
    test_sharpes = [window.test_result.metrics.sharpe_ratio for window in windows if window.test_result.metrics]
    profitable_windows = sum(
        1
        for window in windows
        if window.test_result.metrics is not None and window.test_result.metrics.total_return_pct > 0
    )

    return WalkForwardSummary(
        strategy_name=strategy_name,
        train_candles=train_candles,
        test_candles=test_candles,
        include_risk=include_risk,
        windows=windows,
        avg_train_return_pct=_average(train_returns),
        avg_test_return_pct=_average(test_returns),
        avg_test_max_drawdown_pct=_average(test_drawdowns),
        avg_test_sharpe_ratio=_average(test_sharpes),
        profitable_test_windows=profitable_windows,
        total_test_windows=len(windows),
        compounded_test_return_pct=round((compounded_growth - 1.0) * 100.0, 4),
    )
