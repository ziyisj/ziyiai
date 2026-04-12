# ETH Strategy System

A minimal but extensible ETH backtesting MVP.

Important: this is a research system, not a guaranteed-profitable trading bot. Any intraday strategy you promote to live trading should be validated out-of-sample, paper traded, and reviewed for fees/slippage/regime changes.

What this version includes:
- CSV candle loader
- Sample ETH-like data generator
- Real ETH OHLC downloader from CoinGecko
- Real ETH OHLCV downloader from OKX
- Strategy interface
- Six built-in strategies: moving-average cross, RSI mean reversion, MACD, breakout, OKX 15m intraday, OKX 15m multi-timeframe
- One productization candidate strategy: OKX 15m multi-timeframe trend-following entry model
- Long-only backtest engine
- Risk controls: position sizing, stop loss, take profit, max holding period
- Optional execution slippage model for intraday realism
- Live-style signal snapshot command for paper-trading/manual execution workflows
- Windows desktop launcher for the current production-candidate strategy
- TradingView Pine Script for chart-side monitoring
- Strategy comparison mode for batch backtests
- Parameter optimization / grid search with ranked best settings
- Metrics report and JSON output
- Walk-forward validation for out-of-sample intraday strategy checks
- CLI entrypoint

Quickstart

1. Create a virtualenv and install editable package:

   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev]

2. Run the sample backtest:

   python3 -m eth_backtester.cli

3. Compare all built-in strategies on the same sample dataset:

   PYTHONPATH=src python3 -m eth_backtester.cli --compare-all

4. Search the best MA-cross parameters on the sample dataset:

   PYTHONPATH=src python3 -m eth_backtester.cli --strategy ma_cross --optimize --top-n 5

5. Search the best parameters for every built-in strategy on real ETH data:

   PYTHONPATH=src python3 -m eth_backtester.cli --download-coingecko --days 30 --optimize-all --top-n 3

6. Download real ETH data from CoinGecko and backtest one strategy:

   PYTHONPATH=src python3 -m eth_backtester.cli --download-coingecko --days 30 --strategy macd --json-out out/coingecko_report.json

7. Download real ETH data from OKX and compare all strategies:

   PYTHONPATH=src python3 -m eth_backtester.cli --download-okx --okx-inst-id ETH-USDT --okx-bar 4H --okx-candles 300 --compare-all

8. Research an OKX 15m intraday strategy:

   PYTHONPATH=src python3 -m eth_backtester.cli --download-okx --download-out data/eth_okx_15m.csv --okx-bar 15m --okx-candles 300 --strategy okx_15m_intraday --optimize --top-n 5

9. Run the production-candidate 15m multi-timeframe preset:

   PYTHONPATH=src python3 -m eth_backtester.cli --preset presets/okx_15m_mtf_production_candidate.json

10. Tune the 15m multi-timeframe strategy manually:

   PYTHONPATH=src python3 -m eth_backtester.cli --csv data/eth_okx_15m.csv --strategy okx_15m_mtf --mtf-trend-fast-window 4 --mtf-trend-slow-window 10 --mtf-trigger-fast-window 8 --mtf-trigger-slow-window 21 --mtf-trigger-signal-window 7 --mtf-entry-rsi-window 7 --mtf-entry-rsi-threshold 50 --mtf-exit-rsi 65 --mtf-atr-window 10 --mtf-min-atr-pct 0.002 --mtf-max-atr-pct 0.02 --session-start-hour 6 --session-end-hour 22 --intraday-cooldown-candles 2 --slippage-bps 5

11. Build a live-style signal snapshot from the production-candidate preset:

   PYTHONPATH=src python3 -m eth_backtester.cli --preset presets/okx_15m_mtf_production_candidate.json --signal-snapshot --json-out out/okx_15m_mtf_signal_snapshot.json

12. Fetch a live OKX signal snapshot without relying on a local CSV:

   PYTHONPATH=src python3 -m eth_backtester.cli --preset presets/okx_15m_mtf_production_candidate.json --live-okx-snapshot --json-out out/okx_15m_mtf_live_okx_snapshot.json

13. Tune risk controls around a chosen OKX 15m intraday configuration:

   PYTHONPATH=src python3 -m eth_backtester.cli --csv data/eth_okx_15m.csv --strategy okx_15m_intraday --intraday-fast-window 16 --intraday-slow-window 40 --intraday-rsi-window 5 --intraday-pullback-threshold 38 --intraday-exit-rsi 55 --intraday-atr-window 10 --intraday-min-atr-pct 0.003 --intraday-max-atr-pct 0.015 --session-start-hour 6 --session-end-hour 22 --intraday-cooldown-candles 2 --optimize --optimize-risk --top-n 5

14. Run the best OKX RSI setup with a 5% stop loss:

   PYTHONPATH=src python3 -m eth_backtester.cli --download-okx --strategy rsi --rsi-window 10 --rsi-oversold 35 --rsi-overbought 75 --stop-loss-pct 0.05

15. Search OKX RSI strategy + risk controls together:

   PYTHONPATH=src python3 -m eth_backtester.cli --download-okx --strategy rsi --optimize --optimize-risk --top-n 5

16. Run walk-forward validation on a 15m MACD candidate:

   PYTHONPATH=src python3 -m eth_backtester.cli --csv data/eth_okx_15m.csv --strategy macd --walk-forward --optimize-risk --wf-train-candles 180 --wf-test-candles 60 --top-n 1 --json-out out/macd_15m_walk_forward.json

17. Stress the same 15m MACD candidate with 5 bps of slippage:

   PYTHONPATH=src python3 -m eth_backtester.cli --csv data/eth_okx_15m.csv --strategy macd --macd-fast-window 8 --macd-slow-window 26 --macd-signal-window 7 --max-hold-candles 18 --slippage-bps 5

18. Run against your own CSV:

   python3 -m eth_backtester.cli --csv path/to/eth_usd.csv --strategy breakout

Expected CSV columns:
- timestamp
- open
- high
- low
- close
- volume

Example:

   timestamp,open,high,low,close,volume
   2024-01-01T00:00:00,2280,2295,2275,2290,1250

Run tests:

   pytest

Windows desktop usage:

1. Copy the whole project folder to Windows.
2. Install Python 3.11+.
3. Double-click `windows-desktop/ETH_15M_Signal_Desktop.bat` to run the app directly.
4. To build a standalone `.exe` on Windows, run `windows-desktop/build_windows_exe.bat`.
5. The built executable will appear at `dist/ETH_15M_Signal_Desktop.exe`.
6. The desktop app will poll live OKX ETH-USDT 15m data and show the latest signal snapshot.

GitHub Actions Windows build:

- Workflow file: `.github/workflows/build-windows-exe.yml`
- After pushing to GitHub, run the `build-windows-exe` workflow or let it trigger automatically.
- Download the built `.exe` from the workflow artifacts.

TradingView usage:

1. Open `tradingview/eth_15m_mtf_product_candidate.pine`.
2. Paste it into the TradingView Pine editor.
3. Add it to a 15m ETHUSDT chart.
4. Create alerts from the built-in enter/exit alertconditions.

Project layout

- `src/eth_backtester/data.py` — CSV loading and sample data generation
- `src/eth_backtester/download.py` — CoinGecko historical ETH downloader
- `src/eth_backtester/indicators.py` — SMA, EMA, RSI, and breakout helper indicators
- `src/eth_backtester/strategy.py` — strategy registry plus MA cross, RSI, MACD, breakout, and multi-timeframe intraday strategies
- `src/eth_backtester/optimize.py` — parameter grid search and ranking logic
- `src/eth_backtester/validation.py` — walk-forward train/test validation
- `src/eth_backtester/signals.py` — live-style signal snapshot generation from strategy state
- `src/eth_backtester/live.py` — direct OKX live snapshot helper
- `src/eth_backtester/backtest.py` — execution engine
- `src/eth_backtester/report.py` — metrics, serialization, comparison, and optimization output
- `src/eth_backtester/cli.py` — terminal entrypoint
- `windows-desktop/eth_signal_desktop.pyw` — Windows Tkinter desktop app
- `windows-desktop/ETH_15M_Signal_Desktop.bat` — double-click launcher for Windows
- `tradingview/eth_15m_mtf_product_candidate.pine` — TradingView Pine Script v5 version of the product candidate logic

Current assumptions

- Spot ETH only in spirit; engine is generic OHLCV
- Long-only, one position at a time
- Orders fill at candle close, optionally adjusted by adverse slippage
- No leverage, shorting, funding, or multi-asset portfolios yet
- CoinGecko OHLC endpoint does not include volume, so downloaded rows use volume=0

Recommended next steps

1. Add slippage/spread modeling for 15m execution realism.
2. Add paper-trading with live websocket feeds.
3. Add execution adapters for centralized exchanges or DEXs.
4. Add a dashboard and strategy registry.
5. Add multi-regime validation and monitoring alerts.
