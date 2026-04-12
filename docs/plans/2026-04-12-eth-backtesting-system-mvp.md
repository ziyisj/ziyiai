# ETH Backtesting System MVP Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: Build a Python MVP for researching and backtesting ETH spot strategies with CSV market data, a pluggable strategy interface, a working moving-average example, and a CLI report.

Architecture: Create a small standalone Python package under eth-strategy-system/ with clean boundaries between data loading, strategy generation, execution simulation, and reporting. Keep the execution model intentionally simple for MVP: long-only, single-position, close-price fills, configurable fees, and deterministic metrics so the system is easy to extend later into paper trading and live execution.

Tech Stack: Python 3.11+, standard library, pytest.

---

### Task 1: Create project skeleton

Objective: Establish a standalone package and test layout for the MVP.

Files:
- Create: `eth-strategy-system/pyproject.toml`
- Create: `eth-strategy-system/README.md`
- Create: `eth-strategy-system/src/eth_backtester/__init__.py`
- Create: `eth-strategy-system/tests/test_backtest.py`

Steps:
1. Create the package metadata and console script entrypoint.
2. Add a README that explains the scope and quickstart.
3. Add package `__init__` exports.
4. Add an initial pytest file so the project is test-first from the start.

### Task 2: Add market data and domain models

Objective: Define the basic data structures required by strategies and the backtest engine.

Files:
- Create: `eth-strategy-system/src/eth_backtester/models.py`
- Create: `eth-strategy-system/src/eth_backtester/data.py`
- Modify: `eth-strategy-system/tests/test_backtest.py`

Steps:
1. Define candle, signal, trade, equity-point, and result models.
2. Add CSV loading and sample CSV generation helpers.
3. Add tests covering parsing and sample data generation.

### Task 3: Add strategy interface and baseline strategy

Objective: Support pluggable strategies and ship one strategy that proves the full loop works.

Files:
- Create: `eth-strategy-system/src/eth_backtester/strategy.py`
- Create: `eth-strategy-system/src/eth_backtester/indicators.py`
- Modify: `eth-strategy-system/tests/test_backtest.py`

Steps:
1. Define a strategy protocol/base class.
2. Add reusable indicator helpers like SMA.
3. Implement a moving-average cross strategy.
4. Add tests validating generated signals.

### Task 4: Implement the backtest engine

Objective: Convert signals plus candles into deterministic fills, equity, and metrics.

Files:
- Create: `eth-strategy-system/src/eth_backtester/backtest.py`
- Create: `eth-strategy-system/src/eth_backtester/report.py`
- Modify: `eth-strategy-system/tests/test_backtest.py`

Steps:
1. Simulate long-only entries/exits using configured fees.
2. Record trades and equity curve points.
3. Compute metrics such as total return, max drawdown, win rate, and Sharpe ratio.
4. Add tests for a profitable sample path.

### Task 5: Add CLI and usage flow

Objective: Make the MVP runnable from the terminal with either a CSV file or generated sample data.

Files:
- Create: `eth-strategy-system/src/eth_backtester/cli.py`
- Modify: `eth-strategy-system/README.md`
- Modify: `eth-strategy-system/tests/test_backtest.py`

Steps:
1. Add CLI flags for CSV path, fees, initial cash, and strategy parameters.
2. Print a concise report and optional JSON output.
3. Add a no-data quickstart path using generated sample candles.
4. Verify the CLI works end-to-end in tests or smoke checks.

### Task 6: Verify and document extension points

Objective: Make it obvious how this MVP evolves into paper trading and live execution.

Files:
- Modify: `eth-strategy-system/README.md`
- Modify: `eth-strategy-system/docs/plans/2026-04-12-eth-backtesting-system-mvp.md`

Steps:
1. Document current assumptions and limitations.
2. Document next modules: real-time data ingest, risk engine, paper trader, execution service.
3. Add exact commands for running tests and the sample strategy.
