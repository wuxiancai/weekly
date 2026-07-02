from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import DEFAULTS
from .strategy import StrategyParams, enrich_candles


@dataclass
class Position:
    side: str
    signal_time: int
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
    start_trading_ms: int | None = None,
) -> dict[str, Any]:
    """Run a no-lookahead backtest.

    A signal is generated from a fully closed candle and can only be executed on
    the next candle open. Stop-loss and take-profit exits are confirmed by the
    current candle close, so intrabar wicks do not trigger exits.
    """
    enriched = enrich_candles(candles, params)
    equity = initial_equity
    peak = initial_equity
    max_drawdown = 0.0
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, float]] = []
    position: Position | None = None

    for i, row in enumerate(enriched):
        previous = enriched[i - 1] if i > 0 else None
        close = float(row["close"])
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        action_signal = previous["signal"] if previous is not None else "HOLD"
        signal_atr = previous.get("atr") if previous is not None else None

        if position is not None:
            exit_price, exit_reason = _exit_decision(position, high, low, close, action_signal, signal_price=open_price)
            if exit_price is not None:
                equity, trade = _close_position(position, row["open_time"], exit_price, equity, fee_rate, slippage_rate, exit_reason)
                trades.append(trade)
                position = None

        can_trade = start_trading_ms is None or int(row["open_time"]) >= start_trading_ms
        if can_trade and position is None and action_signal in ("LONG", "SHORT") and signal_atr and previous is not None:
            entry_price = open_price * (1 + slippage_rate if action_signal == "LONG" else 1 - slippage_rate)
            quantity = equity / entry_price
            fee = equity * fee_rate
            equity -= fee
            if action_signal == "LONG":
                stop_price = entry_price - params.stop_atr * signal_atr
                take_price = entry_price + params.take_atr * signal_atr
            else:
                stop_price = entry_price + params.stop_atr * signal_atr
                take_price = entry_price - params.take_atr * signal_atr
            position = Position(action_signal, int(previous["open_time"]), int(row["open_time"]), entry_price, quantity, stop_price, take_price, equity)
            same_bar_exit, same_bar_reason = _exit_decision(position, high, low, close, "HOLD")
            if same_bar_exit is not None:
                equity, trade = _close_position(position, row["open_time"], same_bar_exit, equity, fee_rate, slippage_rate, same_bar_reason)
                trades.append(trade)
                position = None

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


def _exit_decision(
    position: Position,
    high: float,
    low: float,
    close: float,
    signal: str,
    signal_price: float | None = None,
) -> tuple[float | None, str]:
    if position.side == "LONG":
        if close <= position.stop_price:
            return position.stop_price, "STOP_LOSS"
        if close >= position.take_price:
            return position.take_price, "TAKE_PROFIT"
        if signal == "SHORT":
            return signal_price if signal_price is not None else close, "REVERSE_SIGNAL"
    else:
        if close >= position.stop_price:
            return position.stop_price, "STOP_LOSS"
        if close <= position.take_price:
            return position.take_price, "TAKE_PROFIT"
        if signal == "LONG":
            return signal_price if signal_price is not None else close, "REVERSE_SIGNAL"
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
        "signal_time": position.signal_time,
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
