from __future__ import annotations

from dataclasses import dataclass

from .backtest import BacktestConfig, BacktestEngine
from .models import BacktestResult, Candle, Signal, Trade


@dataclass(frozen=True)
class SignalSnapshot:
    strategy_name: str
    latest_timestamp: str
    latest_close: float
    latest_signal_action: str
    latest_signal_reason: str
    current_position_state: str
    current_position_qty: float
    cash: float
    equity: float
    recommendation: str
    recent_trades: list[dict]

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "latest_timestamp": self.latest_timestamp,
            "latest_close": self.latest_close,
            "latest_signal_action": self.latest_signal_action,
            "latest_signal_reason": self.latest_signal_reason,
            "current_position_state": self.current_position_state,
            "current_position_qty": self.current_position_qty,
            "cash": self.cash,
            "equity": self.equity,
            "recommendation": self.recommendation,
            "recent_trades": self.recent_trades,
        }


def _serialize_trade(trade: Trade) -> dict:
    return {
        "side": trade.side,
        "timestamp": trade.timestamp.isoformat(),
        "price": trade.price,
        "quantity": trade.quantity,
        "fee_paid": trade.fee_paid,
        "cash_after": trade.cash_after,
        "position_after": trade.position_after,
        "reason": trade.reason,
    }


def build_signal_snapshot(
    strategy_name: str,
    candles: list[Candle],
    signals: list[Signal],
    config: BacktestConfig,
    recent_trades: int = 5,
) -> SignalSnapshot:
    if not candles or not signals:
        raise ValueError("candles and signals are required")
    latest_candle = candles[-1]
    latest_signal = signals[-1]
    live_result: BacktestResult = BacktestEngine(config).run(candles, signals, force_final_exit=False)
    latest_equity_point = live_result.equity_curve[-1]
    current_position_qty = latest_equity_point.position
    current_position_state = "long" if current_position_qty > 0 else "flat"

    if current_position_state == "long":
        recommendation = "exit_long" if latest_signal.action == "sell" else "hold_long"
    else:
        recommendation = "enter_long" if latest_signal.action == "buy" else "stand_aside"

    return SignalSnapshot(
        strategy_name=strategy_name,
        latest_timestamp=latest_candle.timestamp.isoformat(),
        latest_close=round(latest_candle.close, 6),
        latest_signal_action=latest_signal.action,
        latest_signal_reason=latest_signal.reason,
        current_position_state=current_position_state,
        current_position_qty=round(current_position_qty, 8),
        cash=round(latest_equity_point.cash, 6),
        equity=round(latest_equity_point.equity, 6),
        recommendation=recommendation,
        recent_trades=[_serialize_trade(trade) for trade in live_result.trades[-recent_trades:]],
    )
