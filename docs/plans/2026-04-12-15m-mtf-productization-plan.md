# 15m Multi-Timeframe Productization Plan

> For Hermes: implement this with strict TDD. Add failing tests first, then the smallest working code, then run the full suite.

Goal: turn the current 15m day-trading research setup into a more production-oriented package by adding a 1H trend filter + 15m trigger strategy, preset configs, and a reusable skill/workflow.

Architecture:
- Add aggregation helpers that derive 1H candles from 15m candles in-memory.
- Add a new strategy that trades only when 1H trend is aligned and 15m trigger conditions confirm entry.
- Keep execution model simple and explicit: long-only, close execution, optional slippage, session filter, cooldown, ATR filter, max-hold.
- Package proven configs as presets and document the repeatable validation workflow.

Implementation steps:
1. Add tests for 1H aggregation and the new strategy signal generation.
2. Run the targeted tests and confirm they fail.
3. Implement intraday aggregation helpers and the new strategy.
4. Add CLI flags and optimizer support for the new strategy.
5. Add preset output/docs for aggressive vs production-candidate configurations.
6. Run pytest.
7. Run real OKX 15m compare/optimize/walk-forward commands.
8. Save the workflow as a Hermes skill.
