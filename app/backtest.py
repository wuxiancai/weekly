from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import DEFAULTS
from .strategy import StrategyParams, enrich_candles


@dataclass
class Position:
    side: str
    entry_time: int
    entry_price: float
    quantity: float
    stop_price: float
    take_price: float
    entry_equity: float


def run_backtest(
    candles: list[dict[str, Any]],
    params: StrategyParams,
    initial_equity: float = DEFAULTS.initial_equity,
    fee_rate: float = DEFAULTS.fee_rate,
    slippage_rate: float = DEFAULTS.slippage_rate,
) -> dict[str, Any]:
    enriched = enrich_candles(candles, params)
    equity = initial_equity
    peak = initial_equity
    max_drawdown = 0.0
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, float]] = []
    position: Position | None = None

    for row in enriched:
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        atr_value = row.get("atr")
        signal = row["signal"]

        if position is not None:
            exit_price, exit_reason = _exit_decision(position, high, low, close, signal)
            if exit_price is not None:
                equity, trade = _close_position(position, row["open_time"], exit_price, equity, fee_rate, slippage_rate, exit_reason)
                trades.append(trade)
                position = None

        if position is None and signal in ("LONG", "SHORT") and atr_value:
            entry_price = close * (1 + slippage_rate if signal == "LONG" else 1 - slippage_rate)
            quantity = equity / entry_price
            fee = equity * fee_rate
            equity -= fee
            if signal == "LONG":
                stop_price = entry_price - params.stop_atr * atr_value
                take_price = entry_price + params.take_atr * atr_value
            else:
                stop_price = entry_price + params.stop_atr * atr_value
                take_price = entry_price - params.take_atr * atr_value
            position = Position(signal, int(row["open_time"]), entry_price, quantity, stop_price, take_price, equity)

        mark_equity = _mark_to_market(equity, position, close) if position else equity
        peak = max(peak, mark_equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - mark_equity) / peak)
        equity_curve.append({"time": int(row["open_time"]), "equity": round(mark_equity, 4)})

    if position is not None and enriched:
        last = enriched[-1]
        equity, trade = _close_position(position, int(last["open_time"]), float(last["close"]), equity, fee_rate, slippage_rate, "END_OF_TEST")
        trades.append(trade)
        equity_curve[-1]["equity"] = round(equity, 4)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    metrics = {
        "initial_equity": round(initial_equity, 4),
        "final_equity": round(equity, 4),
        "total_return_pct": round((equity / initial_equity - 1) * 100, 4) if initial_equity else 0.0,
        "max_drawdown_pct": round(max_drawdown * 100, 4),
        "trade_count": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 4) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (round(gross_profit, 4) if gross_profit else 0.0),
        "return_drawdown_ratio": round(((equity / initial_equity - 1) * 100) / (max_drawdown * 100), 4) if max_drawdown else 0.0,
    }
    return {"metrics": metrics, "trades": trades, "equity_curve": equity_curve, "candles": enriched}


def _exit_decision(position: Position, high: float, low: float, close: float, signal: str) -> tuple[float | None, str]:
    if position.side == "LONG":
        if low <= position.stop_price:
            return position.stop_price, "STOP_LOSS"
        if high >= position.take_price:
            return position.take_price, "TAKE_PROFIT"
        if signal == "SHORT":
            return close, "REVERSE_SIGNAL"
    else:
        if high >= position.stop_price:
            return position.stop_price, "STOP_LOSS"
        if low <= position.take_price:
            return position.take_price, "TAKE_PROFIT"
        if signal == "LONG":
            return close, "REVERSE_SIGNAL"
    return None, ""


def _close_position(
    position: Position,
    exit_time: int,
    exit_price: float,
    equity: float,
    fee_rate: float,
    slippage_rate: float,
    exit_reason: str,
) -> tuple[float, dict[str, Any]]:
    adjusted_exit = exit_price * (1 - slippage_rate if position.side == "LONG" else 1 + slippage_rate)
    if position.side == "LONG":
        pnl = (adjusted_exit - position.entry_price) * position.quantity
    else:
        pnl = (position.entry_price - adjusted_exit) * position.quantity
    exit_notional = adjusted_exit * position.quantity
    fee = exit_notional * fee_rate
    final_equity = equity + pnl - fee
    trade = {
        "side": position.side,
        "entry_time": position.entry_time,
        "exit_time": exit_time,
        "entry_price": round(position.entry_price, 4),
        "exit_price": round(adjusted_exit, 4),
        "quantity": round(position.quantity, 8),
        "pnl": round(pnl - fee, 4),
        "pnl_pct": round((final_equity / position.entry_equity - 1) * 100, 4) if position.entry_equity else 0.0,
        "exit_reason": exit_reason,
    }
    return final_equity, trade


def _mark_to_market(equity: float, position: Position, close: float) -> float:
    if position.side == "LONG":
        return equity + (close - position.entry_price) * position.quantity
    return equity + (position.entry_price - close) * position.quantity

