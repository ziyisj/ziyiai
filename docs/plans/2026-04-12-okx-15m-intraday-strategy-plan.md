# OKX 15m Intraday Strategy Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: Turn the current ETH backtesting project into a usable intraday strategy research workflow for OKX 15-minute candles, with session-aware filtering, volatility/trend features, tighter risk exits, and a dedicated intraday strategy that can be stress-tested on recent data.

Architecture: Extend the existing single-asset backtester rather than replacing it. Keep the current CSV/download/backtest pipeline, then add intraday-specific utilities in small modules: time/session helpers, ATR/volatility indicators, an OKX 15m preset path, and one dedicated intraday strategy combining trend filter + pullback/mean-reversion entry + hard risk exits. Finish by validating on OKX 15m ETH-USDT data with optimization enabled.

Tech Stack: Python 3.11+, standard library, pytest.

---

### Task 1: Add intraday plan and preset documentation

Objective: Capture the 15m intraday workflow in docs so implementation stays coherent.

Files:
- Create: `docs/plans/2026-04-12-okx-15m-intraday-strategy-plan.md`
- Modify: `README.md`

Steps:
1. Document the new target workflow: OKX, ETH-USDT, 15m candles, intraday trading.
2. Add CLI examples for downloading 15m candles.
3. Add a short note that profitable deployment is not guaranteed and requires out-of-sample validation.

### Task 2: Add time/session and ATR helpers

Objective: Give strategies intraday context and volatility awareness.

Files:
- Modify: `src/eth_backtester/indicators.py`
- Create: `src/eth_backtester/intraday.py`
- Modify: `tests/test_backtest.py`

Steps:
1. Add ATR indicator.
2. Add helper functions for hour/minute extraction and session inclusion.
3. Add tests for ATR and session filtering.

### Task 3: Add a dedicated 15m intraday strategy

Objective: Create a strategy specifically designed for intraday OKX 15m ETH trading.

Files:
- Modify: `src/eth_backtester/strategy.py`
- Modify: `tests/test_backtest.py`

Steps:
1. Add `okx_15m_intraday` strategy to the registry.
2. Use a trend filter + RSI pullback entry + volatility sanity checks + session filter.
3. Emit only long-side signals initially, consistent with the engine.
4. Add tests proving it can emit buy/sell signals on synthetic 15m data.

### Task 4: Add intraday-specific CLI options

Objective: Make the new strategy configurable from the terminal without editing code.

Files:
- Modify: `src/eth_backtester/cli.py`
- Modify: `README.md`

Steps:
1. Add session start/end hour flags.
2. Add ATR, RSI, and cooldown parameters for the intraday strategy.
3. Add examples for 15m comparison and optimization runs.

### Task 5: Add 15m OKX optimization workflow

Objective: Let the optimizer search both strategy and risk parameters for the intraday strategy.

Files:
- Modify: `src/eth_backtester/optimize.py`
- Modify: `src/eth_backtester/report.py`
- Modify: `tests/test_backtest.py`

Steps:
1. Add a parameter grid for `okx_15m_intraday`.
2. Support optimizing the strategy with `--optimize-risk`.
3. Add tests for report output and parameter validity.

### Task 6: Validate on OKX ETH-USDT 15m data

Objective: Produce a candidate intraday configuration and compare it against the existing RSI baseline.

Files:
- Use: `data/eth_okx_15m.csv`
- Modify: `README.md`

Steps:
1. Download recent OKX ETH-USDT 15m candles.
2. Run compare-all and optimizer flows.
3. Record the best candidate config and its drawdown/Sharpe tradeoff.
4. Document limitations: no slippage model, no shorts, no live execution yet.
