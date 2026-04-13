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
from eth_backtester.dashboard_server import build_dashboard_args, create_dashboard_server, start_dashboard_server
from eth_backtester.market_analysis import analyze_market
from eth_backtester.okx_private import OKXCredentials, OKXPrivateRESTClient
from eth_backtester.okx_ws_public import OKXPublicWebSocketClient, normalize_ws_channel_for_bar
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
    assert snapshot.market_regime in {"上涨趋势", "下跌趋势", "震荡"}
    assert snapshot.suggested_side in {"做多", "做空", "低吸做多", "高抛做空"}
    assert snapshot.suggested_stop_loss != snapshot.suggested_take_profit
    assert len(snapshot.recent_trades) <= 5


def test_build_okx_live_signal_snapshot_uses_live_data(monkeypatch) -> None:
    candles = _make_15m_candles([100 + i for i in range(120)])

    def fake_fetch_eth_ohlcv_from_okx(inst_id: str = "ETH-USDT-SWAP", bar: str = "15m", candles_limit: int = 300, request_limit: int = 100):
        assert inst_id == "ETH-USDT-SWAP"
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
    assert snapshot.market_regime in {"上涨趋势", "下跌趋势", "震荡"}


def test_market_analysis_supports_trend_and_range_regimes() -> None:
    uptrend = _make_15m_candles([100 + i for i in range(60)])
    rangebound = _make_15m_candles([100, 101, 99, 100, 102, 98] * 10)

    up = analyze_market(uptrend, "15m")
    rg = analyze_market(rangebound, "1H")

    assert up.regime == "上涨趋势"
    assert up.suggested_side == "做多"
    assert up.suggested_take_profit > up.suggested_entry > up.suggested_stop_loss

    assert rg.regime in {"震荡", "下跌趋势", "上涨趋势"}
    assert rg.strategy_label in {"区间震荡策略", "顺势回踩做多", "顺势反弹做空"}


def test_okx_ws_client_updates_ticker_and_candles() -> None:
    client = OKXPublicWebSocketClient("ETH-USDT-SWAP", "15m", max_candles=10)
    client.set_seed_candles(_make_15m_candles([100 + i for i in range(5)]))
    client._handle_message({
        "arg": {"channel": "tickers"},
        "data": [{"last": "1234.56", "ts": "1704067200000"}],
    })
    snap = client.get_snapshot()
    assert snap.latest_price == 1234.56
    assert snap.latest_price_ts == "2024-01-01T00:00:00"

    client._handle_message({
        "arg": {"channel": "candle15m"},
        "data": [["1704070800000", "101", "105", "99", "104", "88", "0", "0", "1"]],
    })
    snap = client.get_snapshot()
    assert snap.candles is not None
    assert snap.candles[-1].close == 104.0
    assert normalize_ws_channel_for_bar("15m") == "candle15m"


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


def test_create_dashboard_server_uses_dynamic_port_without_opening_browser() -> None:
    args = build_dashboard_args(["--no-browser", "--port", "0"])
    server, url = create_dashboard_server(args)
    try:
        assert url.startswith("http://127.0.0.1:")
        assert server.server_address[1] > 0
    finally:
        server.server_close()


def test_start_dashboard_server_serves_dashboard_payload(monkeypatch) -> None:
    candles = _make_15m_candles([100 + i for i in range(60)])

    class DummySnapshot:
        def to_dict(self):
            return {
                "latest_close": candles[-1].close,
                "latest_signal_action": "hold",
                "latest_signal_reason": "test",
                "recommendation": "stand_aside",
                "suggested_side": "做多",
                "suggested_entry": candles[-1].close - 1,
                "suggested_stop_loss": candles[-1].close - 5,
                "suggested_take_profit": candles[-1].close + 8,
                "market_regime": "上涨趋势",
                "market_bias": "偏多",
                "market_confidence": 0.8,
                "strategy_label": "顺势回踩做多",
                "strategy_description": "test",
                "current_position_state": "flat",
                "current_position_qty": 0.0,
                "equity": 10000.0,
                "cash": 10000.0,
                "latest_timestamp": candles[-1].timestamp.isoformat(),
                "recent_trades": [],
            }

    monkeypatch.setattr(
        "eth_backtester.dashboard_server.build_okx_live_dashboard_bundle",
        lambda args: (
            candles,
            DummySnapshot(),
            {
                "latest_price": candles[-1].close + 0.5,
                "latest_price_ts": candles[-1].timestamp.isoformat(),
                "latest_candle_close": candles[-1].close,
                "status": "connected",
                "last_error": None,
                "transport": "okx_ws_public",
            },
        ),
    )

    args = build_dashboard_args(["--no-browser", "--port", "0"])
    server, url, _thread = start_dashboard_server(args)
    try:
        from urllib.request import urlopen

        with urlopen(f"{url}api/dashboard?bar=1H", timeout=5) as response:
            payload = json.load(response)
        assert payload["meta"]["instrument"] == "ETH-USDT-SWAP"
        assert payload["meta"]["bar"] == "1H"
        assert payload["meta"]["stream_url"] == "/api/dashboard-stream?bar=1H"
        assert len(payload["candles"]) == len(candles)
        assert payload["snapshot"]["latest_close"] == candles[-1].close
        assert payload["realtime"]["status"] == "connected"
        assert payload["realtime"]["latest_price"] == candles[-1].close + 0.5

        with urlopen(f"{url}api/dashboard-stream?bar=1H", timeout=5) as response:
            chunk = response.read(4096).decode("utf-8")
        assert "event: dashboard" in chunk
        assert '"snapshot": {' in chunk
    finally:
        server.shutdown()
        server.server_close()


def test_okx_private_signing_is_stable() -> None:
    client = OKXPrivateRESTClient(
        OKXCredentials(api_key="key", api_secret="secret", passphrase="pass")
    )
    signature = client._sign(
        "2024-01-01T00:00:00.000Z",
        "GET",
        "/api/v5/account/balance",
        "",
    )
    assert signature == "dfI+ViVVBgfRPWcGyH3gM3bM/DTyiqUqZys/Y9UbsFQ="


def test_dashboard_okx_login_and_logout_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        "eth_backtester.okx_private.OKXPrivateRESTClient.fetch_account_snapshot",
        lambda self, inst_id: {
            "connected": True,
            "simulated": self.credentials.simulated,
            "equity": 12345.67,
            "cash": 3456.78,
            "current_position_state": "long",
            "current_position_qty": 2.5,
            "position_side_label": "持多",
            "updated_at": "2026-04-12T20:50:00.000Z",
            "api_key_hint": "abcd***wxyz",
            "inst_id": inst_id,
            "error": None,
        },
    )

    args = build_dashboard_args(["--no-browser", "--port", "0"])
    server, url, _thread = start_dashboard_server(args)
    try:
        from urllib.request import Request, urlopen

        login_req = Request(
            f"{url}api/okx-login",
            data=json.dumps(
                {
                    "api_key": "abcd1234wxyz",
                    "api_secret": "secret",
                    "passphrase": "pass",
                    "simulated": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(login_req, timeout=5) as response:
            payload = json.load(response)
        assert payload["ok"] is True
        assert payload["account"]["equity"] == 12345.67
        assert payload["auth"]["connected"] is True

        with urlopen(f"{url}api/okx-auth-status", timeout=5) as response:
            status = json.load(response)
        assert status["connected"] is True
        assert status["account"]["cash"] == 3456.78

        logout_req = Request(f"{url}api/okx-logout", data=b"{}", method="POST")
        with urlopen(logout_req, timeout=5) as response:
            logout_payload = json.load(response)
        assert logout_payload["ok"] is True
        assert logout_payload["auth"]["connected"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_launcher_runtime_assets_do_not_require_src_directory(tmp_path: Path) -> None:
    runtime_root = tmp_path / "bundle"
    (runtime_root / "web-dashboard").mkdir(parents=True)
    (runtime_root / "presets").mkdir(parents=True)
    (runtime_root / "web-dashboard" / "index.html").write_text("<html></html>", encoding="utf-8")
    (runtime_root / "presets" / "okx_15m_mtf_production_candidate.json").write_text("{}", encoding="utf-8")

    required_paths = [
        runtime_root / "web-dashboard" / "index.html",
        runtime_root / "presets" / "okx_15m_mtf_production_candidate.json",
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    assert missing == []
    assert not (runtime_root / "src").exists()
