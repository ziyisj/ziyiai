from __future__ import annotations

import json
from pathlib import Path

from .models import BacktestResult
from .optimize import OptimizationResult
from .signals import SignalSnapshot
from .validation import WalkForwardSummary


def format_console_report(result: BacktestResult) -> str:
    if result.metrics is None:
        raise ValueError("result.metrics is required")

    metrics = result.metrics
    lines = [
        "ETH Backtest Report",
        "===================",
        f"Final equity: ${metrics.final_equity:,.2f}",
        f"Total return: {metrics.total_return_pct:.2f}%",
        f"Max drawdown: {metrics.max_drawdown_pct:.2f}%",
        f"Win rate: {metrics.win_rate_pct:.2f}%",
        f"Sharpe ratio: {metrics.sharpe_ratio:.2f}",
        f"Completed trades: {metrics.trades}",
    ]
    return "\n".join(lines)


def format_comparison_report(results: list[tuple[str, BacktestResult]]) -> str:
    lines = [
        "Strategy Comparison",
        "===================",
        "strategy     final_equity   return_pct   max_dd_pct   win_rate   sharpe   trades",
    ]
    for strategy_name, result in results:
        if result.metrics is None:
            raise ValueError(f"metrics missing for {strategy_name}")
        metrics = result.metrics
        lines.append(
            f"{strategy_name:<12}"
            f"${metrics.final_equity:>11,.2f}   "
            f"{metrics.total_return_pct:>9.2f}%   "
            f"{metrics.max_drawdown_pct:>9.2f}%   "
            f"{metrics.win_rate_pct:>7.2f}%   "
            f"{metrics.sharpe_ratio:>6.2f}   "
            f"{metrics.trades:>6}"
        )
    return "\n".join(lines)


def format_optimization_report(results: dict[str, list[OptimizationResult]]) -> str:
    lines = [
        "Strategy Optimization Rankings",
        "==============================",
    ]
    for strategy_name, entries in results.items():
        lines.append(f"\n[{strategy_name}]")
        if not entries:
            lines.append("  no valid parameter combinations")
            continue
        for rank, entry in enumerate(entries, start=1):
            metrics = entry.result.metrics
            if metrics is None:
                continue
            params = ", ".join(f"{key}={value}" for key, value in entry.parameters.items())
            lines.append(
                f"  {rank}. equity=${metrics.final_equity:,.2f} | return={metrics.total_return_pct:.2f}% | "
                f"max_dd={metrics.max_drawdown_pct:.2f}% | sharpe={metrics.sharpe_ratio:.2f} | {params}"
            )
    return "\n".join(lines)


def format_signal_snapshot_report(snapshot: SignalSnapshot) -> str:
    lines = [
        "Live Signal Snapshot",
        "====================",
        f"Strategy: {snapshot.strategy_name}",
        f"Latest candle: {snapshot.latest_timestamp}",
        f"Latest close: {snapshot.latest_close:,.4f}",
        f"Latest signal: {snapshot.latest_signal_action} ({snapshot.latest_signal_reason})",
        f"Position state: {snapshot.current_position_state}",
        f"Position qty: {snapshot.current_position_qty}",
        f"Cash: ${snapshot.cash:,.2f}",
        f"Equity: ${snapshot.equity:,.2f}",
        f"Recommendation: {snapshot.recommendation}",
    ]
    if snapshot.recent_trades:
        lines.append("")
        lines.append("Recent Trades")
        lines.append("-------------")
        for trade in snapshot.recent_trades:
            lines.append(
                f"{trade['timestamp']} | {trade['side']} | price={trade['price']:.4f} | qty={trade['quantity']:.6f} | reason={trade['reason']}"
            )
    return "\n".join(lines)


def format_walk_forward_report(summary: WalkForwardSummary) -> str:
    lines = [
        "Walk-Forward Validation",
        "=======================",
        f"Strategy: {summary.strategy_name}",
        f"Train candles per window: {summary.train_candles}",
        f"Test candles per window: {summary.test_candles}",
        f"Risk optimization included: {'yes' if summary.include_risk else 'no'}",
        f"Windows: {summary.total_test_windows}",
        f"Profitable test windows: {summary.profitable_test_windows}/{summary.total_test_windows}",
        f"Average train return: {summary.avg_train_return_pct:.2f}%",
        f"Average test return: {summary.avg_test_return_pct:.2f}%",
        f"Average test max drawdown: {summary.avg_test_max_drawdown_pct:.2f}%",
        f"Average test Sharpe: {summary.avg_test_sharpe_ratio:.2f}",
        f"Compounded test return: {summary.compounded_test_return_pct:.2f}%",
        "",
        "Window Details",
        "--------------",
    ]
    for window in summary.windows:
        train_metrics = window.train_result.metrics
        test_metrics = window.test_result.metrics
        lines.append(
            f"[{window.index}] train {window.train_start} -> {window.train_end} | "
            f"test {window.test_start} -> {window.test_end}"
        )
        lines.append(
            "    selected: " + ", ".join(f"{key}={value}" for key, value in window.selected_parameters.items())
        )
        if train_metrics is not None:
            lines.append(
                f"    train: return={train_metrics.total_return_pct:.2f}% | "
                f"max_dd={train_metrics.max_drawdown_pct:.2f}% | "
                f"sharpe={train_metrics.sharpe_ratio:.2f} | trades={train_metrics.trades}"
            )
        if test_metrics is not None:
            lines.append(
                f"    test:  return={test_metrics.total_return_pct:.2f}% | "
                f"max_dd={test_metrics.max_drawdown_pct:.2f}% | "
                f"sharpe={test_metrics.sharpe_ratio:.2f} | trades={test_metrics.trades}"
            )
    return "\n".join(lines)


def write_json_report(result: BacktestResult, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return output_path


def write_json_data(payload: dict, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path
