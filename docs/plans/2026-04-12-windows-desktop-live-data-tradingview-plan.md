# Windows Desktop + Live Data + TradingView Plan

> For Hermes: implement this with strict TDD. Add failing tests first, then minimal code, then run the full suite.

Goal: ship a Windows-friendly desktop app that polls live ETH-USDT 15m data from OKX, shows the current signal snapshot for the production-candidate strategy, and include a TradingView Pine script based on the same multi-timeframe logic.

Architecture:
- Add a reusable live-data helper that fetches OKX candles and builds the existing signal snapshot from live data.
- Build a Tkinter desktop UI around that helper, plus a Windows .bat launcher so the user can run it as a desktop file.
- Add a TradingView Pine Script v5 file that mirrors the 1H trend filter + 15m trigger logic as closely as Pine allows.

Implementation steps:
1. Add failing tests for live OKX signal snapshot helper.
2. Run targeted tests to confirm failure.
3. Implement live snapshot helper.
4. Implement Windows desktop app (.pyw) and Windows launcher (.bat).
5. Add TradingView Pine script file.
6. Update README with Windows and TradingView usage.
7. Run pytest.
8. Run real live snapshot command against OKX.
