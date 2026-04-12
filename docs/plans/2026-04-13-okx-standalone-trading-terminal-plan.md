# OKX Standalone Trading Terminal Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: Build a single standalone desktop trading application that runs the full OKX ETH perpetual strategy workflow without requiring the user to open an external browser or other software.

Architecture: Replace the current browser-oriented dashboard flow with an embedded desktop terminal that contains: OKX realtime market stream ingestion, local strategy signal engine, side/top signal panel, risk controls, and OKX trade execution. The desktop shell remains self-contained and the app connects directly to OKX public/private APIs.

Tech Stack: Python 3.11, pywebview desktop shell, local embedded web UI, OKX WebSocket (public + private), OKX REST fallback/order operations, existing strategy engine in src/eth_backtester.

---

## Product requirements locked

1. Single software window, no dependence on external browser tabs.
2. Realtime market data from OKX, not 5-second polling snapshots.
3. Signal does not need to be drawn on the chart; it can appear in top/side panels.
4. Show recommended entry, stop loss, take profit, position state, and account state.
5. Support automated trading on OKX.
6. Keep a safe paper/simulated mode before real trading mode.
7. Target instrument first: ETH-USDT-SWAP.
8. Keep Windows EXE delivery.

---

## Task 1: Add OKX connection settings model

Objective: Define a single typed configuration source for realtime data and trading execution.

Files:
- Create: src/eth_backtester/okx_config.py
- Modify: src/eth_backtester/cli.py
- Test: tests/test_okx_config.py

Step 1: Write failing test for config parsing and safe defaults.
Step 2: Implement config object with fields for api_key, secret_key, passphrase, paper_mode, inst_id, bar, websocket_url_public, websocket_url_private.
Step 3: Add CLI/env loading helpers.
Step 4: Run targeted tests.
Step 5: Commit.

## Task 2: Add OKX public WebSocket client

Objective: Replace snapshot polling with realtime feed ingestion.

Files:
- Create: src/eth_backtester/okx_ws_public.py
- Modify: src/eth_backtester/live.py
- Test: tests/test_okx_ws_public.py

Step 1: Write failing tests for message normalization into internal candle/ticker events.
Step 2: Implement WebSocket client with reconnect, heartbeat, and subscription for ETH-USDT-SWAP candles/ticker.
Step 3: Normalize incoming messages into app events.
Step 4: Keep REST polling only as fallback.
Step 5: Run targeted tests.
Step 6: Commit.

## Task 3: Add realtime strategy engine loop

Objective: Turn incoming OKX stream data into continuous signal state.

Files:
- Create: src/eth_backtester/realtime_engine.py
- Modify: src/eth_backtester/signals.py
- Test: tests/test_realtime_engine.py

Step 1: Write failing tests for incremental candle updates and signal transitions.
Step 2: Implement in-memory state machine that maintains last candles, active signal, suggested entry, stop loss, and take profit.
Step 3: Reuse current strategy code where possible.
Step 4: Run tests.
Step 5: Commit.

## Task 4: Add OKX private API trade executor

Objective: Support paper mode and live mode order execution.

Files:
- Create: src/eth_backtester/okx_trader.py
- Create: src/eth_backtester/risk.py
- Test: tests/test_okx_trader.py

Step 1: Write failing tests for order payload construction, paper mode guardrails, and risk checks.
Step 2: Implement private signing/auth helpers.
Step 3: Implement place order, close position, fetch balance, fetch position.
Step 4: Implement hard guards: max position size, kill switch, no live trading unless explicitly enabled.
Step 5: Run tests.
Step 6: Commit.

## Task 5: Add terminal-side control API

Objective: Expose the realtime engine + trade executor to the embedded desktop UI.

Files:
- Create: src/eth_backtester/terminal_server.py
- Modify: src/eth_backtester/dashboard_server.py or replace it
- Test: tests/test_terminal_server.py

Step 1: Write failing tests for endpoints/state responses.
Step 2: Add endpoints for:
- current signal state
- latest realtime candle/ticker
- suggested entry/SL/TP
- account/position state
- recent fills/orders
- trading mode (paper/live)
- enable/disable strategy
- manual flatten
Step 3: Wire terminal server to realtime engine and trader.
Step 4: Run tests.
Step 5: Commit.

## Task 6: Replace current dashboard UI with standalone terminal UI

Objective: Make the app self-contained and operational without external browser windows.

Files:
- Modify: web-dashboard/index.html
- Modify: web-dashboard/app.js
- Modify: web-dashboard/styles.css
- Modify: windows-desktop/eth_web_dashboard_launcher.py
- Test: manual browser/webview validation + optional JS smoke tests

Step 1: Change the UI layout to emphasize terminal controls instead of chart overlays.
Step 2: Keep chart area, but move critical strategy outputs into side/top cards:
- 当前信号
- 建议开仓价
- 建议止损
- 建议止盈
- 当前仓位
- 账户权益
- 连接状态
- 自动交易状态
Step 3: Add controls:
- 连接 OKX
- 启动/暂停策略
- 纸面交易/实盘模式
- 一键平仓
Step 4: Ensure pywebview launches only the embedded window.
Step 5: Validate manually.
Step 6: Commit.

## Task 7: Add execution journal and safety logs

Objective: Make the software operable and debuggable in real use.

Files:
- Create: src/eth_backtester/journal.py
- Modify: windows-desktop/eth_web_dashboard_launcher.py
- Test: tests/test_journal.py

Step 1: Write failing tests for event logging.
Step 2: Log signal transitions, order requests, responses, errors, reconnects.
Step 3: Show latest execution logs in side panel.
Step 4: Run tests.
Step 5: Commit.

## Task 8: Add Windows packaging updates

Objective: Deliver the standalone OKX trading terminal as a Windows EXE.

Files:
- Modify: windows-desktop/ETH_15M_Web_Dashboard.spec
- Modify: windows-desktop/build_web_dashboard_exe.bat
- Modify: requirements-desktop.txt
- Modify: .github/workflows/build-windows-exe.yml

Step 1: Ensure all new runtime files and dependencies are bundled.
Step 2: Add OKX-related deps if needed.
Step 3: Build in GitHub Actions.
Step 4: Download artifact and smoke test.
Step 5: Commit.

## Task 9: Add staged rollout modes

Objective: Avoid going straight from prototype to dangerous live trading.

Files:
- Modify: src/eth_backtester/okx_trader.py
- Modify: src/eth_backtester/terminal_server.py
- Modify: web-dashboard/app.js
- Test: tests/test_okx_trader.py

Step 1: Support three modes:
- observe_only
- paper_trade
- live_trade
Step 2: Make live_trade require explicit enable flag + visible red warning.
Step 3: Block live order placement if config is incomplete.
Step 4: Run tests.
Step 5: Commit.

## Verification checklist

- App opens as a single desktop window.
- No external browser window is required.
- Realtime data updates arrive from OKX WebSocket.
- Signal panel updates in realtime.
- Suggested entry / SL / TP are shown clearly.
- Paper mode can simulate order flow.
- Live mode stays disabled by default.
- Windows EXE builds successfully in GitHub Actions.

## Immediate next implementation order

1. Task 1: OKX config
2. Task 2: public WebSocket
3. Task 3: realtime engine
4. Task 5: terminal server
5. Task 6: embedded UI refresh
6. Task 4: trader
7. Task 7: journal
8. Task 9: rollout modes
9. Task 8: final packaging
