from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backtest import BacktestConfig, BacktestEngine
from .data import generate_sample_eth_csv, load_candles_from_csv
from .download import download_eth_csv_from_coingecko, download_eth_csv_from_okx
from .live import build_okx_live_signal_snapshot
from .optimize import optimize_all_strategies, optimize_strategy
from .report import (
    format_comparison_report,
    format_console_report,
    format_optimization_report,
    format_signal_snapshot_report,
    format_walk_forward_report,
    write_json_data,
    write_json_report,
)
from .signals import build_signal_snapshot
from .strategy import available_strategies, build_strategy
from .validation import walk_forward_validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an ETH strategy backtest")
    parser.add_argument("--csv", type=Path, help="Path to OHLCV CSV file")
    parser.add_argument("--preset", type=Path, help="Optional JSON preset file with strategy and risk parameters")
    parser.add_argument(
        "--download-coingecko",
        action="store_true",
        help="Download real ETH OHLC data from CoinGecko before backtesting",
    )
    parser.add_argument(
        "--download-okx",
        action="store_true",
        help="Download real ETH OHLCV data from OKX before backtesting",
    )
    parser.add_argument(
        "--download-out",
        type=Path,
        help="Optional path for downloaded market data; defaults to a source-specific filename under data/",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="CoinGecko lookback window in days (1, 7, 14, 30, 90, 180, 365)",
    )
    parser.add_argument("--vs-currency", default="usd", help="Fiat quote currency for CoinGecko downloads")
    parser.add_argument("--okx-inst-id", default="ETH-USDT", help="OKX instrument id, e.g. ETH-USDT")
    parser.add_argument("--okx-bar", default="4H", help="OKX candle timeframe, e.g. 1H, 4H, 1D")
    parser.add_argument("--okx-candles", type=int, default=300, help="How many OKX candles to download")
    parser.add_argument(
        "--strategy",
        default="ma_cross",
        choices=available_strategies(),
        help="Strategy to run for a single backtest",
    )
    parser.add_argument(
        "--compare-all",
        action="store_true",
        help="Run all built-in strategies on the same dataset and print a comparison table",
    )
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Search parameter grids and print the top combinations",
    )
    parser.add_argument(
        "--optimize-all",
        action="store_true",
        help="Run parameter search for all built-in strategies",
    )
    parser.add_argument(
        "--optimize-risk",
        action="store_true",
        help="Include risk controls in the optimization search space",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Run walk-forward validation: optimize on each training window, then evaluate on the following test window",
    )
    parser.add_argument(
        "--signal-snapshot",
        action="store_true",
        help="Build a live-style signal snapshot without forcing the final position closed",
    )
    parser.add_argument(
        "--live-okx-snapshot",
        action="store_true",
        help="Fetch the latest OKX candles directly and build a signal snapshot without requiring a CSV file",
    )
    parser.add_argument(
        "--recent-trades",
        type=int,
        default=5,
        help="How many recent trades to include in signal snapshots",
    )
    parser.add_argument(
        "--wf-train-candles",
        type=int,
        default=180,
        help="Training window size for walk-forward validation",
    )
    parser.add_argument(
        "--wf-test-candles",
        type=int,
        default=60,
        help="Test window size for walk-forward validation",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="How many ranked parameter combinations to print during optimization",
    )
    parser.add_argument("--initial-cash", type=float, default=10_000.0)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=0.0,
        help="Adverse execution slippage in basis points applied to entries and exits",
    )
    parser.add_argument(
        "--position-size-pct",
        type=float,
        default=1.0,
        help="Fraction of available cash to allocate on each entry (0-1]",
    )
    parser.add_argument(
        "--stop-loss-pct",
        type=float,
        help="Optional stop loss as a decimal fraction, e.g. 0.05 for 5%%",
    )
    parser.add_argument(
        "--take-profit-pct",
        type=float,
        help="Optional take profit as a decimal fraction, e.g. 0.10 for 10%%",
    )
    parser.add_argument(
        "--max-hold-candles",
        type=int,
        help="Optional maximum holding period measured in candles",
    )
    parser.add_argument("--fast-window", type=int, default=8)
    parser.add_argument("--slow-window", type=int, default=21)
    parser.add_argument("--intraday-fast-window", type=int, default=20)
    parser.add_argument("--intraday-slow-window", type=int, default=50)
    parser.add_argument("--intraday-rsi-window", type=int, default=7)
    parser.add_argument("--intraday-pullback-threshold", type=float, default=38.0)
    parser.add_argument("--intraday-exit-rsi", type=float, default=58.0)
    parser.add_argument("--intraday-atr-window", type=int, default=14)
    parser.add_argument("--intraday-min-atr-pct", type=float, default=0.002)
    parser.add_argument("--intraday-max-atr-pct", type=float, default=0.025)
    parser.add_argument("--mtf-trend-fast-window", type=int, default=6)
    parser.add_argument("--mtf-trend-slow-window", type=int, default=12)
    parser.add_argument("--mtf-trigger-fast-window", type=int, default=8)
    parser.add_argument("--mtf-trigger-slow-window", type=int, default=21)
    parser.add_argument("--mtf-trigger-signal-window", type=int, default=5)
    parser.add_argument("--mtf-entry-rsi-window", type=int, default=7)
    parser.add_argument("--mtf-entry-rsi-threshold", type=float, default=55.0)
    parser.add_argument("--mtf-exit-rsi", type=float, default=68.0)
    parser.add_argument("--mtf-atr-window", type=int, default=10)
    parser.add_argument("--mtf-min-atr-pct", type=float, default=0.002)
    parser.add_argument("--mtf-max-atr-pct", type=float, default=0.02)
    parser.add_argument("--session-start-hour", type=int, default=6)
    parser.add_argument("--session-end-hour", type=int, default=22)
    parser.add_argument("--intraday-cooldown-candles", type=int, default=4)
    parser.add_argument("--rsi-window", type=int, default=14)
    parser.add_argument("--rsi-oversold", type=float, default=35.0)
    parser.add_argument("--rsi-overbought", type=float, default=65.0)
    parser.add_argument("--macd-fast-window", type=int, default=12)
    parser.add_argument("--macd-slow-window", type=int, default=26)
    parser.add_argument("--macd-signal-window", type=int, default=9)
    parser.add_argument("--breakout-lookback", type=int, default=20)
    parser.add_argument("--breakout-exit-lookback", type=int, default=10)
    parser.add_argument("--json-out", type=Path, help="Optional path to write JSON report")
    parser.add_argument(
        "--sample-out",
        type=Path,
        default=Path("data/sample_eth.csv"),
        help="Where to write generated sample data when neither --csv nor --download-coingecko is used",
    )
    return parser


def apply_preset_args(args: argparse.Namespace) -> argparse.Namespace:
    if getattr(args, "preset", None) is None:
        return args

    preset_path = Path(args.preset)
    payload = json.loads(preset_path.read_text(encoding="utf-8"))
    merged = vars(args).copy()
    for key, value in payload.items():
        if key == "preset":
            continue
        default_value = build_parser().get_default(key)
        if key not in merged or merged[key] == default_value or merged[key] is None:
            merged[key] = value
    return argparse.Namespace(**merged)


def resolve_csv_path(args: argparse.Namespace) -> Path:
    if args.csv is not None:
        return args.csv
    if args.download_okx:
        output_path = args.download_out or Path("data/eth_okx.csv")
        csv_path = download_eth_csv_from_okx(
            output_path,
            inst_id=args.okx_inst_id,
            bar=args.okx_bar,
            candles_limit=args.okx_candles,
        )
        print(
            f"Downloaded ETH OHLCV data from OKX to {csv_path} "
            f"({args.okx_inst_id}, {args.okx_bar}, candles={args.okx_candles})"
        )
        return csv_path
    if args.download_coingecko:
        output_path = args.download_out or Path("data/eth_coingecko.csv")
        csv_path = download_eth_csv_from_coingecko(
            output_path,
            days=args.days,
            vs_currency=args.vs_currency,
        )
        print(
            f"Downloaded ETH OHLC data from CoinGecko to {csv_path} "
            f"({args.days}d, {args.vs_currency.upper()})"
        )
        return csv_path

    csv_path = generate_sample_eth_csv(args.sample_out)
    print(f"Generated sample ETH-like data at {csv_path}")
    return csv_path


def build_backtest_config(args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
        position_size_pct=args.position_size_pct,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        max_hold_candles=args.max_hold_candles,
    )


def run_strategy_backtest(args: argparse.Namespace, strategy_name: str, csv_path: Path) -> tuple[str, object]:
    candles = load_candles_from_csv(csv_path)
    strategy = build_strategy(strategy_name, args)
    signals = strategy.generate_signals(candles)
    engine = BacktestEngine(build_backtest_config(args))
    result = engine.run(candles, signals)
    return strategy.name, result


def run_optimization(args: argparse.Namespace, csv_path: Path) -> str:
    candles = load_candles_from_csv(csv_path)
    if args.optimize_all:
        results = optimize_all_strategies(
            candles,
            args,
            top_n=args.top_n,
            include_risk=args.optimize_risk,
        )
    else:
        results = {
            args.strategy: optimize_strategy(
                candles,
                args,
                args.strategy,
                top_n=args.top_n,
                include_risk=args.optimize_risk,
            )
        }
    return format_optimization_report(results)


def run_walk_forward(args: argparse.Namespace, csv_path: Path):
    candles = load_candles_from_csv(csv_path)
    return walk_forward_validate(
        candles,
        args,
        args.strategy,
        train_candles=args.wf_train_candles,
        test_candles=args.wf_test_candles,
        include_risk=args.optimize_risk,
        top_n=args.top_n,
    )


def run_signal_snapshot(args: argparse.Namespace, csv_path: Path):
    candles = load_candles_from_csv(csv_path)
    strategy = build_strategy(args.strategy, args)
    signals = strategy.generate_signals(candles)
    return build_signal_snapshot(
        strategy_name=strategy.name,
        candles=candles,
        signals=signals,
        config=build_backtest_config(args),
        recent_trades=args.recent_trades,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args = apply_preset_args(args)

    if args.live_okx_snapshot:
        snapshot = build_okx_live_signal_snapshot(args)
        print(format_signal_snapshot_report(snapshot))
        if args.json_out is not None:
            path = write_json_data(snapshot.to_dict(), args.json_out)
            print(f"Wrote JSON report to {path}")
        return

    csv_path = resolve_csv_path(args)

    if args.optimize or args.optimize_all:
        print(run_optimization(args, csv_path))
        return

    if args.walk_forward:
        summary = run_walk_forward(args, csv_path)
        print(format_walk_forward_report(summary))
        if args.json_out is not None:
            path = write_json_data(summary.to_dict(), args.json_out)
            print(f"Wrote JSON report to {path}")
        return

    if args.signal_snapshot:
        snapshot = run_signal_snapshot(args, csv_path)
        print(format_signal_snapshot_report(snapshot))
        if args.json_out is not None:
            path = write_json_data(snapshot.to_dict(), args.json_out)
            print(f"Wrote JSON report to {path}")
        return

    if args.compare_all:
        comparison: list[tuple[str, object]] = []
        for strategy_name in available_strategies():
            comparison.append(run_strategy_backtest(args, strategy_name, csv_path))
        print(format_comparison_report(comparison))
        return

    strategy_name, result = run_strategy_backtest(args, args.strategy, csv_path)
    print(f"Strategy: {strategy_name}")
    print(format_console_report(result))

    if args.json_out is not None:
        path = write_json_report(result, args.json_out)
        print(f"Wrote JSON report to {path}")


if __name__ == "__main__":
    main()
