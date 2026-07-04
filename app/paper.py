from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .backtest import (
    Position,
    _close_position,
    _exit_decision,
    _mark_to_market,
    _notional_multiplier,
    _update_position_adverse,
)
from .strategy import StrategyParams, enrich_candles, params_from_dict


PAPER_DEFAULT_INITIAL_EQUITY = 1000.0
PAPER_DEFAULT_COMPOUND = True
PAPER_DEFAULT_LEVERAGE = 0.0
PAPER_DEFAULT_FEE_RATE = 0.0005
PAPER_DEFAULT_SLIPPAGE_RATE = 0.0005


@dataclass(frozen=True)
class PaperStrategyConfig:
    symbol: str
    interval: str
    params: StrategyParams


@dataclass(frozen=True)
class ProcessResult:
    symbol: str
    interval: str
    processed: int
    opened: int
    closed: int
    last_processed_open_time: int | None


def paper_strategy_defaults() -> list[PaperStrategyConfig]:
    weekly = _weekly_params()
    btc_daily = StrategyParams(
        ema_period=8,
        ma_period=40,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=0,
        long_rsi_min=50,
        long_rsi_max=80,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=1.6,
        take_atr=13.0,
        take_atr_step=0.75,
        take_atr_max=18.0,
        take_atr_buffer_pct=0.0,
        volume_mult=0.75,
        regime_switch=False,
    )
    eth_daily = StrategyParams(
        ema_period=15,
        ma_period=40,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=0,
        long_rsi_min=35,
        long_rsi_max=85,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=1.8,
        take_atr=6.5,
        take_atr_step=1.25,
        take_atr_max=24.0,
        take_atr_buffer_pct=0.0,
        volume_mult=1.0,
        regime_switch=False,
    )
    four_hour = _intraday_regime_params()
    btc_one_hour = _btc_one_hour_params()
    eth_one_hour = _eth_one_hour_params()
    return [
        PaperStrategyConfig("BTCUSDT", "1w", weekly),
        PaperStrategyConfig("BTCUSDT", "1d", btc_daily),
        PaperStrategyConfig("BTCUSDT", "4h", four_hour),
        PaperStrategyConfig("BTCUSDT", "1h", btc_one_hour),
        PaperStrategyConfig("ETHUSDT", "1w", weekly),
        PaperStrategyConfig("ETHUSDT", "1d", eth_daily),
        PaperStrategyConfig("ETHUSDT", "4h", four_hour),
        PaperStrategyConfig("ETHUSDT", "1h", eth_one_hour),
    ]


def _weekly_params() -> StrategyParams:
    return StrategyParams(
        ema_period=15,
        ma_period=40,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=0,
        long_rsi_min=35,
        long_rsi_max=85,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=1.8,
        take_atr=7.5,
        take_atr_step=1.25,
        take_atr_max=32.0,
        take_atr_buffer_pct=0.0,
        volume_mult=1.0,
        regime_switch=False,
        trend_ma_gap_min=0.006,
        range_adx_max=18,
        range_bb_width_max=0.08,
        range_rsi_low=35,
        range_rsi_high=65,
    )


def _intraday_regime_params() -> StrategyParams:
    return StrategyParams(
        ema_period=8,
        ma_period=35,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=25,
        long_rsi_min=50,
        long_rsi_max=80,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=0.8,
        take_atr=3.5,
        take_atr_step=0.5,
        take_atr_max=8.0,
        take_atr_buffer_pct=0.0,
        volume_mult=1.0,
        regime_switch=True,
        trend_ma_gap_min=0.0,
        range_adx_max=18,
        range_bb_width_max=0.08,
        range_rsi_low=30,
        range_rsi_high=65,
    )


def _btc_one_hour_params() -> StrategyParams:
    return StrategyParams(
        ema_period=12,
        ma_period=35,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=18,
        long_rsi_min=55,
        long_rsi_max=85,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=0.45,
        take_atr=4.0,
        take_atr_step=1.0,
        take_atr_max=12.0,
        take_atr_buffer_pct=0.0,
        volume_mult=1.25,
        regime_switch=True,
        trend_ma_gap_min=0.0,
        range_adx_max=22,
        range_bb_width_max=0.05,
        range_rsi_low=35,
        range_rsi_high=65,
    )


def _eth_one_hour_params() -> StrategyParams:
    return StrategyParams(
        ema_period=15,
        ma_period=50,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=25,
        long_rsi_min=50,
        long_rsi_max=80,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=0.45,
        take_atr=1.8,
        take_atr_step=0.5,
        take_atr_max=4.0,
        take_atr_buffer_pct=0.0,
        volume_mult=1.0,
        regime_switch=True,
        trend_ma_gap_min=0.0,
        range_adx_max=22,
        range_bb_width_max=0.12,
        range_rsi_low=30,
        range_rsi_high=65,
    )


def init_paper_schema(conn: Any) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS paper_accounts (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            initial_equity REAL NOT NULL,
            equity REAL NOT NULL,
            compound INTEGER NOT NULL,
            leverage REAL NOT NULL,
            fee_rate REAL NOT NULL,
            slippage_rate REAL NOT NULL,
            started_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_strategies (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            params_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_processed_open_time INTEGER,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (symbol, interval)
        );

        CREATE TABLE IF NOT EXISTS paper_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            side TEXT NOT NULL,
            signal_time INTEGER NOT NULL,
            entry_time INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            quantity REAL NOT NULL,
            stop_price REAL NOT NULL,
            take_price REAL NOT NULL,
            entry_equity REAL NOT NULL,
            atr REAL,
            take_atr_start REAL NOT NULL,
            take_atr_step REAL NOT NULL,
            take_atr_max REAL NOT NULL,
            take_atr_buffer_pct REAL NOT NULL,
            take_profit_armed INTEGER NOT NULL,
            entry_margin REAL NOT NULL,
            risk_amount REAL NOT NULL,
            max_adverse_pct REAL NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(symbol, interval)
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            side TEXT NOT NULL,
            signal_time INTEGER NOT NULL,
            entry_time INTEGER NOT NULL,
            exit_time INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            quantity REAL NOT NULL,
            pnl REAL NOT NULL,
            pnl_pct REAL NOT NULL,
            reward_risk_ratio REAL NOT NULL,
            max_drawdown_pct REAL NOT NULL,
            return_drawdown_ratio REAL NOT NULL,
            exit_reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_equity_curve (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            equity REAL NOT NULL,
            price REAL NOT NULL,
            position_side TEXT,
            created_at INTEGER NOT NULL,
            UNIQUE(symbol, interval, open_time)
        );

        CREATE TABLE IF NOT EXISTS paper_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            event_time INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        """
    )


class PaperEngine:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def initialize(
        self,
        initial_equity: float = PAPER_DEFAULT_INITIAL_EQUITY,
        compound: bool = PAPER_DEFAULT_COMPOUND,
        leverage: float = PAPER_DEFAULT_LEVERAGE,
        fee_rate: float = PAPER_DEFAULT_FEE_RATE,
        slippage_rate: float = PAPER_DEFAULT_SLIPPAGE_RATE,
    ) -> None:
        now = _now_ms()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO paper_accounts(
                id, initial_equity, equity, compound, leverage, fee_rate,
                slippage_rate, started_at, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                initial_equity,
                initial_equity,
                int(compound),
                leverage,
                fee_rate,
                slippage_rate,
                now,
                now,
            ),
        )
        for config in paper_strategy_defaults():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO paper_strategies(symbol, interval, params_json, enabled, updated_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (config.symbol, config.interval, json.dumps(config.params.to_dict()), now),
            )
        self.conn.commit()

    def process_strategy(self, symbol: str, interval: str, candles: list[dict[str, Any]]) -> ProcessResult:
        self.initialize()
        symbol = symbol.upper()
        strategy = self._load_strategy(symbol, interval)
        if strategy is None or not int(strategy["enabled"]):
            return ProcessResult(symbol, interval, 0, 0, 0, None)
        if not candles:
            return ProcessResult(symbol, interval, 0, 0, 0, strategy["last_processed_open_time"])

        params = params_from_dict(json.loads(strategy["params_json"]))
        enriched = enrich_candles(candles, params)
        last_processed = strategy["last_processed_open_time"]
        account = self._load_account()
        position = self._load_position(symbol, interval)
        processed = 0
        opened = 0
        closed = 0

        for index, row in enumerate(enriched):
            open_time = int(row["open_time"])
            if last_processed is not None and open_time <= int(last_processed):
                continue

            previous = enriched[index - 1] if index > 0 else None
            action_signal = previous["signal"] if previous is not None else "HOLD"
            signal_atr = previous.get("atr") if previous is not None else None
            close = float(row["close"])
            open_price = float(row["open"])

            if position is not None:
                _update_position_adverse(position, close)
                exit_price, exit_reason = _exit_decision(
                    position,
                    float(row["high"]),
                    float(row["low"]),
                    close,
                    action_signal,
                    signal_price=open_price,
                )
                if exit_price is not None:
                    equity, trade = _close_position(
                        position,
                        open_time,
                        exit_price,
                        float(account["equity"]),
                        float(account["fee_rate"]),
                        float(account["slippage_rate"]),
                        exit_reason,
                    )
                    self._delete_position(symbol, interval)
                    self._record_trade(symbol, interval, trade)
                    account = self._update_account_equity(equity)
                    position = None
                    closed += 1

            if position is None and action_signal in ("LONG", "SHORT") and signal_atr and previous is not None:
                position = self._open_position(symbol, interval, action_signal, previous, row, float(signal_atr), params, account)
                account = self._load_account()
                opened += 1
                _update_position_adverse(position, close)
                same_bar_exit, same_bar_reason = _exit_decision(position, float(row["high"]), float(row["low"]), close, "HOLD")
                if same_bar_exit is not None:
                    equity, trade = _close_position(
                        position,
                        open_time,
                        same_bar_exit,
                        float(account["equity"]),
                        float(account["fee_rate"]),
                        float(account["slippage_rate"]),
                        same_bar_reason,
                    )
                    self._delete_position(symbol, interval)
                    self._record_trade(symbol, interval, trade)
                    account = self._update_account_equity(equity)
                    position = None
                    closed += 1
                else:
                    self._save_position(symbol, interval, position)

            if position is not None:
                self._save_position(symbol, interval, position)

            mark_equity = _mark_to_market(float(account["equity"]), position, close) if position else float(account["equity"])
            self._record_equity(symbol, interval, open_time, mark_equity, close, position.side if position else None)
            self._set_last_processed(symbol, interval, open_time)
            last_processed = open_time
            processed += 1

        self.conn.commit()
        return ProcessResult(symbol, interval, processed, opened, closed, last_processed)

    def prime_strategy(self, symbol: str, interval: str, candles: list[dict[str, Any]]) -> int | None:
        self.initialize()
        symbol = symbol.upper()
        if not candles:
            return None
        strategy = self._load_strategy(symbol, interval)
        if strategy is None or strategy["last_processed_open_time"] is not None:
            return strategy["last_processed_open_time"] if strategy is not None else None
        open_time = int(candles[-1]["open_time"])
        close = float(candles[-1]["close"])
        self._record_equity(symbol, interval, open_time, float(self._load_account()["equity"]), close, None)
        self._set_last_processed(symbol, interval, open_time)
        self._record_event(symbol, interval, "WARMUP_PRIMED", {"last_processed_open_time": open_time})
        self.conn.commit()
        return open_time

    def status(self) -> dict[str, Any]:
        self.initialize()
        account = dict(self._load_account())
        strategies = [dict(row) for row in self.conn.execute("SELECT * FROM paper_strategies ORDER BY symbol, interval")]
        positions = [dict(row) for row in self.conn.execute("SELECT * FROM paper_positions ORDER BY symbol, interval")]
        trades = [dict(row) for row in self.conn.execute("SELECT * FROM paper_trades ORDER BY id DESC LIMIT 20")]
        trade_records = [dict(row) for row in self.conn.execute("SELECT * FROM paper_trades ORDER BY id DESC")]
        events = [dict(row) for row in self.conn.execute("SELECT * FROM paper_events ORDER BY id DESC LIMIT 20")]
        curves = [dict(row) for row in self.conn.execute("SELECT * FROM paper_equity_curve ORDER BY open_time DESC LIMIT 50")]
        positions = [_enrich_position(row) for row in positions]
        for row in strategies:
            row["params"] = json.loads(row.pop("params_json"))
        for row in events:
            row["payload"] = json.loads(row.pop("payload_json"))
        return {
            "account": account,
            "strategies": strategies,
            "positions": positions,
            "trade_records": trade_records,
            "trades": trades,
            "events": events,
            "equity_curve": list(reversed(curves)),
        }

    def record_event(self, symbol: str, interval: str, event_type: str, payload: dict[str, Any]) -> None:
        now = _now_ms()
        self.conn.execute(
            """
            INSERT INTO paper_events(symbol, interval, event_time, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (symbol.upper(), interval, now, event_type, json.dumps(payload), now),
        )
        self.conn.commit()

    def _load_account(self) -> Any:
        return self.conn.execute("SELECT * FROM paper_accounts WHERE id = 1").fetchone()

    def _load_strategy(self, symbol: str, interval: str) -> Any:
        return self.conn.execute(
            "SELECT * FROM paper_strategies WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        ).fetchone()

    def _load_position(self, symbol: str, interval: str) -> Position | None:
        row = self.conn.execute(
            "SELECT * FROM paper_positions WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        ).fetchone()
        if row is None:
            return None
        return Position(
            side=row["side"],
            signal_time=int(row["signal_time"]),
            entry_time=int(row["entry_time"]),
            entry_price=float(row["entry_price"]),
            quantity=float(row["quantity"]),
            stop_price=float(row["stop_price"]),
            take_price=float(row["take_price"]),
            entry_equity=float(row["entry_equity"]),
            atr=float(row["atr"]) if row["atr"] is not None else None,
            take_atr_start=float(row["take_atr_start"]),
            take_atr_step=float(row["take_atr_step"]),
            take_atr_max=float(row["take_atr_max"]),
            take_atr_buffer_pct=float(row["take_atr_buffer_pct"]),
            take_profit_armed=bool(row["take_profit_armed"]),
            entry_margin=float(row["entry_margin"]),
            risk_amount=float(row["risk_amount"]),
            max_adverse_pct=float(row["max_adverse_pct"]),
        )

    def _open_position(
        self,
        symbol: str,
        interval: str,
        side: str,
        previous: dict[str, Any],
        row: dict[str, Any],
        signal_atr: float,
        params: StrategyParams,
        account: Any,
    ) -> Position:
        slippage_rate = float(account["slippage_rate"])
        fee_rate = float(account["fee_rate"])
        entry_price = float(row["open"]) * (1 + slippage_rate if side == "LONG" else 1 - slippage_rate)
        equity = float(account["equity"])
        initial_equity = float(account["initial_equity"])
        entry_base = equity if bool(account["compound"]) else min(equity, initial_equity)
        entry_notional = entry_base * _notional_multiplier(float(account["leverage"]))
        quantity = entry_notional / entry_price
        fee = entry_notional * fee_rate
        account = self._update_account_equity(equity - fee)
        if side == "LONG":
            stop_price = entry_price - params.stop_atr * signal_atr
            take_price = entry_price + params.take_atr * signal_atr
        else:
            stop_price = entry_price + params.stop_atr * signal_atr
            take_price = entry_price - params.take_atr * signal_atr
        position = Position(
            side=side,
            signal_time=int(previous["open_time"]),
            entry_time=int(row["open_time"]),
            entry_price=entry_price,
            quantity=quantity,
            stop_price=stop_price,
            take_price=take_price,
            entry_equity=float(account["equity"]),
            atr=signal_atr,
            take_atr_start=params.take_atr,
            take_atr_step=params.take_atr_step,
            take_atr_max=params.take_atr_max,
            take_atr_buffer_pct=params.take_atr_buffer_pct,
            entry_margin=entry_base,
            risk_amount=abs(entry_price - stop_price) * quantity,
        )
        self._record_event(symbol, interval, "OPEN", {"side": side, "entry_time": int(row["open_time"]), "entry_price": entry_price})
        return position

    def _save_position(self, symbol: str, interval: str, position: Position) -> None:
        now = _now_ms()
        self.conn.execute(
            """
            INSERT INTO paper_positions(
                symbol, interval, side, signal_time, entry_time, entry_price, quantity,
                stop_price, take_price, entry_equity, atr, take_atr_start, take_atr_step,
                take_atr_max, take_atr_buffer_pct, take_profit_armed, entry_margin,
                risk_amount, max_adverse_pct, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, interval) DO UPDATE SET
                side=excluded.side,
                signal_time=excluded.signal_time,
                entry_time=excluded.entry_time,
                entry_price=excluded.entry_price,
                quantity=excluded.quantity,
                stop_price=excluded.stop_price,
                take_price=excluded.take_price,
                entry_equity=excluded.entry_equity,
                atr=excluded.atr,
                take_atr_start=excluded.take_atr_start,
                take_atr_step=excluded.take_atr_step,
                take_atr_max=excluded.take_atr_max,
                take_atr_buffer_pct=excluded.take_atr_buffer_pct,
                take_profit_armed=excluded.take_profit_armed,
                entry_margin=excluded.entry_margin,
                risk_amount=excluded.risk_amount,
                max_adverse_pct=excluded.max_adverse_pct,
                updated_at=excluded.updated_at
            """,
            (
                symbol,
                interval,
                position.side,
                position.signal_time,
                position.entry_time,
                position.entry_price,
                position.quantity,
                position.stop_price,
                position.take_price,
                position.entry_equity,
                position.atr,
                position.take_atr_start,
                position.take_atr_step,
                position.take_atr_max,
                position.take_atr_buffer_pct,
                int(position.take_profit_armed),
                position.entry_margin,
                position.risk_amount,
                position.max_adverse_pct,
                now,
                now,
            ),
        )

    def _delete_position(self, symbol: str, interval: str) -> None:
        self.conn.execute("DELETE FROM paper_positions WHERE symbol = ? AND interval = ?", (symbol, interval))

    def _record_trade(self, symbol: str, interval: str, trade: dict[str, Any]) -> None:
        now = _now_ms()
        self.conn.execute(
            """
            INSERT INTO paper_trades(
                symbol, interval, side, signal_time, entry_time, exit_time, entry_price,
                exit_price, quantity, pnl, pnl_pct, reward_risk_ratio,
                max_drawdown_pct, return_drawdown_ratio, exit_reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                interval,
                trade["side"],
                trade["signal_time"],
                trade["entry_time"],
                trade["exit_time"],
                trade["entry_price"],
                trade["exit_price"],
                trade["quantity"],
                trade["pnl"],
                trade["pnl_pct"],
                trade["reward_risk_ratio"],
                trade["max_drawdown_pct"],
                trade["return_drawdown_ratio"],
                trade["exit_reason"],
                now,
            ),
        )
        self._record_event(symbol, interval, "CLOSE", trade)

    def _record_equity(self, symbol: str, interval: str, open_time: int, equity: float, price: float, side: str | None) -> None:
        now = _now_ms()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO paper_equity_curve(symbol, interval, open_time, equity, price, position_side, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (symbol, interval, open_time, round(equity, 4), price, side, now),
        )

    def _set_last_processed(self, symbol: str, interval: str, open_time: int) -> None:
        self.conn.execute(
            "UPDATE paper_strategies SET last_processed_open_time = ?, updated_at = ? WHERE symbol = ? AND interval = ?",
            (open_time, _now_ms(), symbol, interval),
        )

    def _update_account_equity(self, equity: float) -> Any:
        self.conn.execute("UPDATE paper_accounts SET equity = ?, updated_at = ? WHERE id = 1", (equity, _now_ms()))
        return self._load_account()

    def _record_event(self, symbol: str, interval: str, event_type: str, payload: dict[str, Any]) -> None:
        now = _now_ms()
        self.conn.execute(
            """
            INSERT INTO paper_events(symbol, interval, event_time, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (symbol, interval, now, event_type, json.dumps(payload), now),
        )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _enrich_position(row: dict[str, Any]) -> dict[str, Any]:
    row["initial_take_price"] = _initial_take_price(row)
    row["latest_take_price"] = row["take_price"]
    row["liquidation_price"] = _liquidation_price(row)
    return row


def _initial_take_price(row: dict[str, Any]) -> float | None:
    entry_price = _finite_float(row.get("entry_price"))
    atr = _finite_float(row.get("atr"))
    take_atr_start = _finite_float(row.get("take_atr_start"))
    if entry_price is None or atr is None or take_atr_start is None or atr <= 0 or take_atr_start <= 0:
        return _finite_float(row.get("take_price"))
    if row.get("side") == "SHORT":
        return entry_price - take_atr_start * atr
    return entry_price + take_atr_start * atr


def _liquidation_price(row: dict[str, Any]) -> float | None:
    entry_price = _finite_float(row.get("entry_price"))
    quantity = _finite_float(row.get("quantity"))
    entry_margin = _finite_float(row.get("entry_margin"))
    if entry_price is None or quantity is None or entry_margin is None or quantity <= 0 or entry_margin <= 0:
        return None
    margin_per_unit = entry_margin / quantity
    if row.get("side") == "SHORT":
        return entry_price + margin_per_unit
    return max(0.0, entry_price - margin_per_unit)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result
