from __future__ import annotations

import math
from dataclasses import dataclass

from .models import BacktestResult, Candle, EquityPoint, Metrics, Signal, Trade


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 0.0
    position_size_pct: float = 1.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_hold_candles: int | None = None

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps must be non-negative")
        if not 0 < self.position_size_pct <= 1.0:
            raise ValueError("position_size_pct must be between 0 and 1")
        if self.stop_loss_pct is not None and self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct must be positive when set")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive when set")
        if self.max_hold_candles is not None and self.max_hold_candles <= 0:
            raise ValueError("max_hold_candles must be positive when set")


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, candles: list[Candle], signals: list[Signal], force_final_exit: bool = True) -> BacktestResult:
        if len(candles) != len(signals):
            raise ValueError("candles and signals must have the same length")
        if not candles:
            raise ValueError("backtest requires at least one candle")

        cash = self.config.initial_cash
        position = 0.0
        entry_value = 0.0
        entry_price: float | None = None
        hold_candles = 0
        winning_round_trips = 0
        completed_round_trips = 0
        slippage_multiplier = self.config.slippage_bps / 10_000.0

        result = BacktestResult()

        for candle, signal in zip(candles, signals):
            exit_reason = self._risk_exit_reason(candle, entry_price, hold_candles, position)

            if position == 0.0 and signal.action == "buy":
                allocated_cash = cash * self.config.position_size_pct
                if allocated_cash > 0:
                    execution_price = candle.close * (1.0 + slippage_multiplier)
                    gross_to_spend = allocated_cash / (1.0 + self.config.fee_rate)
                    quantity = gross_to_spend / execution_price
                    fee = gross_to_spend * self.config.fee_rate
                    cash -= gross_to_spend + fee
                    position = quantity
                    entry_value = gross_to_spend + fee
                    entry_price = execution_price
                    hold_candles = 0
                    result.trades.append(
                        Trade(
                            side="buy",
                            timestamp=candle.timestamp,
                            price=execution_price,
                            quantity=quantity,
                            fee_paid=fee,
                            cash_after=cash,
                            position_after=position,
                            reason=signal.reason,
                        )
                    )
            elif position > 0.0 and (signal.action == "sell" or exit_reason is not None):
                quantity = position
                execution_price = candle.close * (1.0 - slippage_multiplier)
                gross_proceeds = quantity * execution_price
                fee = gross_proceeds * self.config.fee_rate
                net_proceeds = gross_proceeds - fee
                pnl = net_proceeds - entry_value
                completed_round_trips += 1
                if pnl > 0:
                    winning_round_trips += 1
                cash += net_proceeds
                position = 0.0
                entry_value = 0.0
                entry_price = None
                hold_candles = 0
                result.trades.append(
                    Trade(
                        side="sell",
                        timestamp=candle.timestamp,
                        price=execution_price,
                        quantity=quantity,
                        fee_paid=fee,
                        cash_after=cash,
                        position_after=position,
                        reason=exit_reason or signal.reason,
                    )
                )
            elif position > 0.0:
                hold_candles += 1

            equity = cash + position * candle.close
            result.equity_curve.append(
                EquityPoint(
                    timestamp=candle.timestamp,
                    equity=equity,
                    cash=cash,
                    position=position,
                    close=candle.close,
                )
            )

        if position > 0.0 and force_final_exit:
            final_candle = candles[-1]
            quantity = position
            execution_price = final_candle.close * (1.0 - slippage_multiplier)
            gross_proceeds = quantity * execution_price
            fee = gross_proceeds * self.config.fee_rate
            net_proceeds = gross_proceeds - fee
            pnl = net_proceeds - entry_value
            completed_round_trips += 1
            if pnl > 0:
                winning_round_trips += 1
            cash += net_proceeds
            position = 0.0
            result.trades.append(
                Trade(
                    side="sell",
                    timestamp=final_candle.timestamp,
                    price=execution_price,
                    quantity=quantity,
                    fee_paid=fee,
                    cash_after=cash,
                    position_after=position,
                    reason="forced_final_exit",
                )
            )
            result.equity_curve[-1] = EquityPoint(
                timestamp=final_candle.timestamp,
                equity=cash,
                cash=cash,
                position=position,
                close=final_candle.close,
            )

        result.metrics = self._compute_metrics(
            equity_curve=result.equity_curve,
            final_equity=cash,
            winning_round_trips=winning_round_trips,
            completed_round_trips=completed_round_trips,
        )
        return result

    def _risk_exit_reason(
        self,
        candle: Candle,
        entry_price: float | None,
        hold_candles: int,
        position: float,
    ) -> str | None:
        if position == 0.0 or entry_price is None:
            return None
        if self.config.stop_loss_pct is not None:
            stop_level = entry_price * (1.0 - self.config.stop_loss_pct)
            if candle.close <= stop_level:
                return "stop_loss"
        if self.config.take_profit_pct is not None:
            take_profit_level = entry_price * (1.0 + self.config.take_profit_pct)
            if candle.close >= take_profit_level:
                return "take_profit"
        if self.config.max_hold_candles is not None and hold_candles >= self.config.max_hold_candles:
            return "max_hold_exit"
        return None

    def _compute_metrics(
        self,
        equity_curve: list[EquityPoint],
        final_equity: float,
        winning_round_trips: int,
        completed_round_trips: int,
    ) -> Metrics:
        initial_cash = self.config.initial_cash
        total_return_pct = ((final_equity / initial_cash) - 1.0) * 100.0

        peak = equity_curve[0].equity
        max_drawdown_pct = 0.0
        returns: list[float] = []

        previous_equity = equity_curve[0].equity
        for point in equity_curve:
            peak = max(peak, point.equity)
            if peak > 0:
                drawdown = (point.equity - peak) / peak * 100.0
                max_drawdown_pct = min(max_drawdown_pct, drawdown)
            if previous_equity > 0:
                returns.append((point.equity / previous_equity) - 1.0)
            previous_equity = point.equity

        sharpe_ratio = 0.0
        if returns:
            mean_return = sum(returns) / len(returns)
            variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
            std_dev = math.sqrt(variance)
            if std_dev > 0:
                sharpe_ratio = (mean_return / std_dev) * math.sqrt(len(returns))

        win_rate_pct = 0.0
        if completed_round_trips > 0:
            win_rate_pct = winning_round_trips / completed_round_trips * 100.0

        return Metrics(
            total_return_pct=round(total_return_pct, 4),
            max_drawdown_pct=round(abs(max_drawdown_pct), 4),
            win_rate_pct=round(win_rate_pct, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            trades=completed_round_trips,
            final_equity=round(final_equity, 4),
        )
