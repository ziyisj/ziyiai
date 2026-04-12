from __future__ import annotations

import io
import json
from datetime import datetime, timedelta
from pathlib import Path

from eth_backtester.backtest import BacktestConfig, BacktestEngine
from eth_backtester.cli import (
    apply_preset_args,
    build_parser,
    run_optimization,
    run_signal_snapshot,
    run_strategy_backtest,
    run_walk_forward,
)
from eth_backtester.data import generate_sample_eth_csv, load_candles_from_csv
from eth_backtester.download import (
    download_eth_csv_from_coingecko,
    download_eth_csv_from_okx,
    fetch_eth_ohlc_from_coingecko,
    fetch_eth_ohlcv_from_okx,
)
from eth_backtester.live import build_okx_live_signal_snapshot
from eth_backtester.indicators import average_true_range
from eth_backtester.intraday import aggregate_candles_by_hours, is_in_session
from eth_backtester.models import Candle, Signal
from eth_backtester.optimize import optimize_strategy
from eth_backtester.report import format_comparison_report
from eth_backtester.strategy import (
    BreakoutStrategy,
    MACDStrategy,
    MovingAverageCrossStrategy,
    MultiTimeframe15mStrategy,
    OKX15mIntradayStrategy,
    RSIMeanReversionStrategy,
    available_strategies,
)


def _make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2024, 1, 1)
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=start + timedelta(hours=index),
                open=close - 5,
                high=close + 5,
                low=close - 10,
                close=close,
                volume=1000 + index,
            )
        )
    return candles


def _make_15m_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2024, 1, 1)
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=start + timedelta(minutes=15 * index),
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=100 + index,
            )
        )
    return candles


def test_generate_sample_eth_csv_and_load(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "sample_eth.csv", periods=24)
    candles = load_candles_from_csv(csv_path)
    assert len(candles) == 24
    assert candles[0].timestamp.isoformat() == "2024-01-01T00:00:00"
    assert candles[-1].close > candles[0].close


def test_atr_and_session_helpers() -> None:
    candles = _make_candles([100, 102, 101, 105, 103, 106, 108, 110])
    atr = average_true_range(candles, window=3)
    assert len(atr) == len(candles)
    assert atr[-1] is not None
    assert is_in_session(candles[0].timestamp, 0, 23) is True
    assert is_in_session(candles[0].timestamp, 1, 23) is False


def test_aggregate_candles_by_hours_rolls_up_15m_data() -> None:
    candles = _make_15m_candles([100, 101, 102, 103, 104, 105, 106, 107])
    aggregated = aggregate_candles_by_hours(candles, hours=1)

    assert len(aggregated) == 2
    assert aggregated[0].timestamp == candles[0].timestamp.replace(minute=0, second=0, microsecond=0)
    assert aggregated[0].open == candles[0].open
    assert aggregated[0].close == candles[3].close
    assert aggregated[0].high == max(candle.high for candle in candles[:4])
    assert aggregated[0].volume == sum(candle.volume for candle in candles[:4])


def test_moving_average_strategy_produces_buy_and_sell_signals() -> None:
    candles = _make_candles([100, 99, 98, 97, 96, 100, 105, 110, 108, 100, 95, 90])
    strategy = MovingAverageCrossStrategy(fast_window=2, slow_window=4)
    signals = strategy.generate_signals(candles)
    actions = [signal.action for signal in signals]
    assert "buy" in actions
    assert "sell" in actions


def test_rsi_strategy_produces_buy_and_sell_signals() -> None:
    candles = _make_candles([100, 98, 96, 94, 92, 90, 91, 94, 98, 103, 108, 112, 115, 118])
    strategy = RSIMeanReversionStrategy(window=3, oversold=25, overbought=75)
    signals = strategy.generate_signals(candles)
    actions = [signal.action for signal in signals]
    assert "buy" in actions
    assert "sell" in actions


def test_macd_strategy_produces_buy_and_sell_signals() -> None:
    candles = _make_candles([100, 99, 98, 97, 96, 97, 99, 102, 106, 109, 111, 108, 104, 99, 95, 92, 90])
    strategy = MACDStrategy(fast_window=3, slow_window=6, signal_window=3)
    signals = strategy.generate_signals(candles)
    actions = [signal.action for signal in signals]
    assert "buy" in actions
    assert "sell" in actions


def test_breakout_strategy_produces_buy_and_sell_signals() -> None:
    candles = _make_candles([100, 101, 102, 103, 104, 110, 114, 112, 109, 107, 103, 99, 96])
    strategy = BreakoutStrategy(lookback=3, exit_lookback=2)
    signals = strategy.generate_signals(candles)
    actions = [signal.action for signal in signals]
    assert "buy" in actions
    assert "sell" in actions


def test_okx_15m_intraday_strategy_produces_buy_and_sell_signals() -> None:
    candles = _make_candles([
        100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
        110, 111, 112, 113, 114, 115, 116, 117, 118, 119,
        120, 121, 122, 123, 124, 125, 126, 127, 128, 129,
        130, 131, 132, 131, 130, 129, 128, 129, 131, 133,
        135, 136, 137, 138, 139, 140, 141, 142, 143, 144,
        145, 144, 143, 142, 141, 140, 139, 138, 137, 136,
        135, 134, 133, 132, 131, 130,
    ])
    strategy = OKX15mIntradayStrategy(
        fast_window=6,
        slow_window=12,
        rsi_window=5,
        pullback_threshold=45.0,
        exit_rsi=58.0,
        atr_window=5,
        min_atr_pct=0.001,
        max_atr_pct=0.2,
        session_start_hour=0,
        session_end_hour=23,
        cooldown_candles=1,
    )
    signals = strategy.generate_signals(candles)
    actions = [signal.action for signal in signals]
    assert "buy" in actions
    assert "sell" in actions


def test_multi_timeframe_strategy_produces_buy_and_sell_signals() -> None:
    candles = _make_15m_candles([
        100, 101, 102, 103, 104, 105, 106, 107,
        108, 109, 110, 111, 112, 113, 114, 115,
        116, 117, 118, 119, 120, 121, 122, 123,
        124, 125, 126, 127, 126, 125, 124, 123,
        122, 121, 120, 119, 118, 119, 120, 121,
        122, 123, 124, 125, 126, 127, 128, 129,
        130, 131, 132, 133, 132, 131, 130, 129,
        128, 127, 126, 125, 124, 123, 122, 121,
    ])
    strategy = MultiTimeframe15mStrategy(
        trend_fast_window=2,
        trend_slow_window=3,
        trigger_fast_window=4,
        trigger_slow_window=9,
        trigger_signal_window=3,
        entry_rsi_window=5,
        entry_rsi_threshold=52.0,
        exit_rsi=68.0,
        atr_window=5,
        min_atr_pct=0.001,
        max_atr_pct=0.2,
        session_start_hour=0,
        session_end_hour=23,
        cooldown_candles=1,
    )
    signals = strategy.generate_signals(candles)
    actions = [signal.action for signal in signals]
    assert "buy" in actions
    assert "sell" in actions


def test_backtest_engine_generates_positive_return_on_trending_sample() -> None:
    candles = _make_candles([100, 99, 98, 97, 98, 101, 104, 108, 113, 118, 123, 128])
    strategy = MovingAverageCrossStrategy(fast_window=2, slow_window=4)
    signals = strategy.generate_signals(candles)
    result = BacktestEngine(BacktestConfig(initial_cash=1000, fee_rate=0.001)).run(candles, signals)

    assert result.metrics is not None
    assert result.metrics.final_equity > 1000
    assert result.metrics.total_return_pct > 0
    assert result.metrics.trades >= 1
    assert result.trades[0].side == "buy"
    assert result.trades[-1].side == "sell"


def test_backtest_risk_controls_trigger_stop_loss_and_partial_position_sizing() -> None:
    candles = _make_candles([100, 95, 90, 89, 88, 87])
    signals = [
        Signal(timestamp=candle.timestamp, action="buy" if index == 0 else "hold", reason="test")
        for index, candle in enumerate(candles)
    ]
    result = BacktestEngine(
        BacktestConfig(
            initial_cash=1000,
            fee_rate=0.0,
            position_size_pct=0.5,
            stop_loss_pct=0.05,
        )
    ).run(candles, signals)

    assert result.metrics is not None
    assert result.metrics.final_equity == 975.0
    assert result.trades[0].side == "buy"
    assert result.trades[0].quantity == 5.0
    assert result.trades[1].side == "sell"
    assert result.trades[1].reason == "stop_loss"


def test_backtest_risk_controls_trigger_take_profit_and_max_hold() -> None:
    candles = _make_candles([100, 108, 109, 109, 109, 109])
    signals = [
        Signal(timestamp=candle.timestamp, action="buy" if index == 0 else "hold", reason="test")
        for index, candle in enumerate(candles)
    ]
    take_profit_result = BacktestEngine(
        BacktestConfig(
            initial_cash=1000,
            fee_rate=0.0,
            take_profit_pct=0.05,
        )
    ).run(candles, signals)
    assert take_profit_result.trades[1].reason == "take_profit"
    assert take_profit_result.metrics is not None
    assert take_profit_result.metrics.final_equity == 1080.0

    max_hold_result = BacktestEngine(
        BacktestConfig(
            initial_cash=1000,
            fee_rate=0.0,
            max_hold_candles=2,
        )
    ).run(candles, signals)
    assert max_hold_result.trades[1].reason == "max_hold_exit"


def test_backtest_slippage_reduces_returns() -> None:
    candles = _make_candles([100, 110])
    signals = [
        Signal(timestamp=candles[0].timestamp, action="buy", reason="entry"),
        Signal(timestamp=candles[1].timestamp, action="sell", reason="exit"),
    ]

    no_slippage = BacktestEngine(BacktestConfig(initial_cash=1000, fee_rate=0.0)).run(candles, signals)
    with_slippage = BacktestEngine(
        BacktestConfig(initial_cash=1000, fee_rate=0.0, slippage_bps=10)
    ).run(candles, signals)

    assert no_slippage.metrics is not None
    assert with_slippage.metrics is not None
    assert with_slippage.metrics.final_equity < no_slippage.metrics.final_equity
    assert with_slippage.trades[0].price > candles[0].close
    assert with_slippage.trades[1].price < candles[1].close


def test_fetch_eth_ohlc_from_coingecko_parses_response(monkeypatch) -> None:
    payload = [
        [1704067200000, 2200.0, 2210.0, 2195.0, 2205.0],
        [1704070800000, 2205.0, 2225.0, 2200.0, 2220.0],
    ]

    def fake_urlopen(request, timeout=30):
        return io.StringIO(json.dumps(payload))

    monkeypatch.setattr("eth_backtester.download.urlopen", fake_urlopen)

    candles = fetch_eth_ohlc_from_coingecko(days=30, vs_currency="usd")
    assert len(candles) == 2
    assert candles[0].close == 2205.0
    assert candles[0].volume == 0.0
    assert candles[0].timestamp.isoformat() == "2024-01-01T00:00:00"


def test_download_eth_csv_from_coingecko_writes_csv(tmp_path: Path, monkeypatch) -> None:
    payload = [
        [1704067200000, 2200.0, 2210.0, 2195.0, 2205.0],
        [1704070800000, 2205.0, 2225.0, 2200.0, 2220.0],
    ]

    def fake_urlopen(request, timeout=30):
        return io.StringIO(json.dumps(payload))

    monkeypatch.setattr("eth_backtester.download.urlopen", fake_urlopen)

    csv_path = download_eth_csv_from_coingecko(tmp_path / "eth.csv", days=30, vs_currency="usd")
    candles = load_candles_from_csv(csv_path)
    assert len(candles) == 2
    assert candles[1].open == 2205.0


def test_fetch_eth_ohlcv_from_okx_parses_response(monkeypatch) -> None:
    payload = {
        "code": "0",
        "msg": "",
        "data": [
            ["1704070800000", "2205.0", "2225.0", "2200.0", "2220.0", "123.4", "0", "0", "1"],
            ["1704067200000", "2200.0", "2210.0", "2195.0", "2205.0", "111.1", "0", "0", "1"],
        ],
    }

    def fake_urlopen(request, timeout=30):
        return io.StringIO(json.dumps(payload))

    monkeypatch.setattr("eth_backtester.download.urlopen", fake_urlopen)

    candles = fetch_eth_ohlcv_from_okx(candles_limit=2)
    assert len(candles) == 2
    assert candles[0].timestamp.isoformat() == "2024-01-01T00:00:00"
    assert candles[1].close == 2220.0
    assert candles[0].volume == 111.1


def test_download_eth_csv_from_okx_writes_csv(tmp_path: Path, monkeypatch) -> None:
    payload = {
        "code": "0",
        "msg": "",
        "data": [
            ["1704070800000", "2205.0", "2225.0", "2200.0", "2220.0", "123.4", "0", "0", "1"],
            ["1704067200000", "2200.0", "2210.0", "2195.0", "2205.0", "111.1", "0", "0", "1"],
        ],
    }

    def fake_urlopen(request, timeout=30):
        return io.StringIO(json.dumps(payload))

    monkeypatch.setattr("eth_backtester.download.urlopen", fake_urlopen)

    csv_path = download_eth_csv_from_okx(tmp_path / "okx_eth.csv", candles_limit=2)
    candles = load_candles_from_csv(csv_path)
    assert len(candles) == 2
    assert candles[0].open == 2200.0
    assert candles[1].volume == 123.4


def test_cli_comparison_helpers_run_all_strategies(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "sample.csv", periods=60)
    parser = build_parser()
    args = parser.parse_args(["--csv", str(csv_path), "--compare-all", "--macd-fast-window", "4", "--macd-slow-window", "8"])

    results = [run_strategy_backtest(args, name, csv_path) for name in available_strategies()]
    report = format_comparison_report(results)

    assert len(results) == 6
    assert "Strategy Comparison" in report
    assert "ma_cross" in report
    assert "macd" in report


def test_optimize_strategy_returns_ranked_results(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "opt_sample.csv", periods=90)
    candles = load_candles_from_csv(csv_path)
    parser = build_parser()
    args = parser.parse_args(["--csv", str(csv_path), "--top-n", "3"])

    ranked = optimize_strategy(candles, args, "ma_cross", top_n=3)

    assert len(ranked) == 3
    assert ranked[0].result.metrics is not None
    assert ranked[0].result.metrics.final_equity >= ranked[-1].result.metrics.final_equity
    assert "fast_window" in ranked[0].parameters


def test_cli_optimization_report_runs_all_strategies(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "sample.csv", periods=120)
    parser = build_parser()
    args = parser.parse_args(["--csv", str(csv_path), "--optimize-all", "--top-n", "2"])

    report = run_optimization(args, csv_path)

    assert "Strategy Optimization Rankings" in report
    assert "[ma_cross]" in report
    assert "[rsi]" in report
    assert "[macd]" in report
    assert "[breakout]" in report
    assert "[okx_15m_intraday]" in report
    assert "[okx_15m_mtf]" in report


def test_risk_optimization_includes_risk_parameters(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "risk_opt.csv", periods=120)
    parser = build_parser()
    args = parser.parse_args([
        "--csv",
        str(csv_path),
        "--strategy",
        "rsi",
        "--optimize",
        "--optimize-risk",
        "--top-n",
        "2",
    ])

    report = run_optimization(args, csv_path)

    assert "stop_loss_pct" in report or "take_profit_pct" in report or "position_size_pct" in report
    assert "[rsi]" in report


def test_apply_preset_args_overrides_defaults(tmp_path: Path) -> None:
    preset_path = tmp_path / "preset.json"
    preset_path.write_text(json.dumps({
        "strategy": "okx_15m_mtf",
        "mtf_trend_fast_window": 4,
        "mtf_trend_slow_window": 10,
        "session_start_hour": 6,
        "session_end_hour": 22,
        "slippage_bps": 5,
    }), encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(["--preset", str(preset_path)])

    applied = apply_preset_args(args)

    assert applied.strategy == "okx_15m_mtf"
    assert applied.mtf_trend_fast_window == 4
    assert applied.slippage_bps == 5


def test_signal_snapshot_reports_live_position_state(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "snapshot.csv", periods=120)
    parser = build_parser()
    args = parser.parse_args([
        "--csv",
        str(csv_path),
        "--strategy",
        "ma_cross",
        "--fast-window",
        "5",
        "--slow-window",
        "18",
        "--signal-snapshot",
    ])

    snapshot = run_signal_snapshot(args, csv_path)

    assert snapshot.strategy_name == "ma_cross"
    assert snapshot.recommendation in {"enter_long", "exit_long", "hold_long", "stand_aside"}
    assert snapshot.current_position_state in {"flat", "long"}
    assert snapshot.latest_signal_action in {"buy", "sell", "hold"}
    assert len(snapshot.recent_trades) <= 5


def test_build_okx_live_signal_snapshot_uses_live_data(monkeypatch) -> None:
    candles = _make_15m_candles([100 + i for i in range(120)])

    def fake_fetch_eth_ohlcv_from_okx(inst_id: str = "ETH-USDT", bar: str = "15m", candles_limit: int = 300, request_limit: int = 100):
        assert inst_id == "ETH-USDT"
        assert bar == "15m"
        assert candles_limit == 120
        return candles

    monkeypatch.setattr("eth_backtester.live.fetch_eth_ohlcv_from_okx", fake_fetch_eth_ohlcv_from_okx)
    parser = build_parser()
    args = parser.parse_args([
        "--strategy",
        "macd",
        "--macd-fast-window",
        "8",
        "--macd-slow-window",
        "21",
        "--macd-signal-window",
        "5",
        "--okx-bar",
        "15m",
        "--okx-candles",
        "120",
    ])

    snapshot = build_okx_live_signal_snapshot(args)

    assert snapshot.strategy_name == "macd"
    assert snapshot.latest_timestamp == candles[-1].timestamp.isoformat()
    assert snapshot.latest_close == candles[-1].close


def test_intraday_optimization_report_runs(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "intraday_opt.csv", periods=180)
    parser = build_parser()
    args = parser.parse_args([
        "--csv",
        str(csv_path),
        "--strategy",
        "okx_15m_intraday",
        "--optimize",
        "--top-n",
        "2",
    ])
    report = run_optimization(args, csv_path)
    assert "[okx_15m_intraday]" in report


def test_multi_timeframe_strategy_appears_in_optimization_report(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "mtf_opt.csv", periods=240)
    parser = build_parser()
    args = parser.parse_args([
        "--csv",
        str(csv_path),
        "--strategy",
        "okx_15m_mtf",
        "--optimize",
        "--top-n",
        "2",
    ])
    report = run_optimization(args, csv_path)
    assert "[okx_15m_mtf]" in report


def test_walk_forward_returns_windowed_summary(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "walk_forward.csv", periods=240)
    parser = build_parser()
    args = parser.parse_args([
        "--csv",
        str(csv_path),
        "--strategy",
        "macd",
        "--walk-forward",
        "--wf-train-candles",
        "120",
        "--wf-test-candles",
        "40",
        "--top-n",
        "1",
    ])

    summary = run_walk_forward(args, csv_path)

    assert summary.strategy_name == "macd"
    assert summary.total_test_windows == 3
    assert len(summary.windows) == 3
    assert summary.windows[0].test_result.metrics is not None
    assert "macd_fast_window" in summary.windows[0].selected_parameters


def test_walk_forward_requires_enough_candles(tmp_path: Path) -> None:
    csv_path = generate_sample_eth_csv(tmp_path / "too_short.csv", periods=100)
    parser = build_parser()
    args = parser.parse_args([
        "--csv",
        str(csv_path),
        "--strategy",
        "rsi",
        "--walk-forward",
        "--wf-train-candles",
        "80",
        "--wf-test-candles",
        "30",
    ])

    try:
        run_walk_forward(args, csv_path)
        raise AssertionError("expected ValueError for insufficient candles")
    except ValueError as exc:
        assert "not enough candles" in str(exc)
