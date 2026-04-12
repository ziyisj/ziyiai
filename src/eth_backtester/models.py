from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

SignalAction = Literal["buy", "sell", "hold"]


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    timestamp: datetime
    action: SignalAction
    reason: str = ""


@dataclass(frozen=True)
class Trade:
    side: Literal["buy", "sell"]
    timestamp: datetime
    price: float
    quantity: float
    fee_paid: float
    cash_after: float
    position_after: float
    reason: str = ""


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: float
    cash: float
    position: float
    close: float


@dataclass
class Metrics:
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    sharpe_ratio: float
    trades: int
    final_equity: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    metrics: Metrics | None = None

    def to_dict(self) -> dict:
        return {
            "equity_curve": [
                {
                    "timestamp": point.timestamp.isoformat(),
                    "equity": point.equity,
                    "cash": point.cash,
                    "position": point.position,
                    "close": point.close,
                }
                for point in self.equity_curve
            ],
            "trades": [
                {
                    "side": trade.side,
                    "timestamp": trade.timestamp.isoformat(),
                    "price": trade.price,
                    "quantity": trade.quantity,
                    "fee_paid": trade.fee_paid,
                    "cash_after": trade.cash_after,
                    "position_after": trade.position_after,
                    "reason": trade.reason,
                }
                for trade in self.trades
            ],
            "metrics": self.metrics.to_dict() if self.metrics else None,
        }
