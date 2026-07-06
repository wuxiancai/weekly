from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
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
from .strategy import StrategyParams, enrich_candles, market_regime_for, params_from_dict


PAPER_DEFAULT_INITIAL_EQUITY = 1000.0
PAPER_DEFAULT_COMPOUND = True
PAPER_DEFAULT_LEVERAGE = 2.0
PAPER_INITIAL_SETTINGS_PASSWORD = "123456"
PAPER_DEFAULT_FEE_RATE = 0.0005
PAPER_DEFAULT_SLIPPAGE_RATE = 0.0005
PAPER_DEFAULT_SYMBOL_ALLOCATIONS = {"BTCUSDT": 80.0, "ETHUSDT": 20.0}
PAPER_DEFAULT_INTERVAL_ALLOCATIONS = {"15m": 0.0, "1h": 30.0, "4h": 40.0, "1d": 20.0, "1w": 10.0}
INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}


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


def last_processed_close_boundary_time(open_time: int | None, interval: str | None) -> int | None:
    if open_time is None or interval is None:
        return None
    duration_ms = INTERVAL_MS.get(interval)
    if duration_ms is None:
        return int(open_time)
    return int(open_time) + duration_ms


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
    btc_fifteen_min = _btc_fifteen_min_params()
    eth_fifteen_min = _eth_fifteen_min_params()
    return [
        PaperStrategyConfig("BTCUSDT", "1w", weekly),
        PaperStrategyConfig("BTCUSDT", "1d", btc_daily),
        PaperStrategyConfig("BTCUSDT", "4h", four_hour),
        PaperStrategyConfig("BTCUSDT", "1h", btc_one_hour),
        PaperStrategyConfig("BTCUSDT", "15m", btc_fifteen_min),
        PaperStrategyConfig("ETHUSDT", "1w", weekly),
        PaperStrategyConfig("ETHUSDT", "1d", eth_daily),
        PaperStrategyConfig("ETHUSDT", "4h", four_hour),
        PaperStrategyConfig("ETHUSDT", "1h", eth_one_hour),
        PaperStrategyConfig("ETHUSDT", "15m", eth_fifteen_min),
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


def _btc_fifteen_min_params() -> StrategyParams:
    return StrategyParams(
        ema_period=34,
        ma_period=89,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=45,
        long_rsi_min=55,
        long_rsi_max=85,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=0.8,
        take_atr=10.0,
        take_atr_step=2.0,
        take_atr_max=24.0,
        take_atr_buffer_pct=0.0,
        volume_mult=1.75,
        regime_switch=True,
        trend_ma_gap_min=0.003,
        range_adx_max=18,
        range_bb_width_max=0.04,
        range_rsi_low=25,
        range_rsi_high=70,
    )


def _eth_fifteen_min_params() -> StrategyParams:
    return StrategyParams(
        ema_period=21,
        ma_period=60,
        rsi_period=14,
        atr_period=14,
        adx_period=14,
        adx_min=35,
        long_rsi_min=45,
        long_rsi_max=80,
        short_rsi_min=0,
        short_rsi_max=100,
        stop_atr=0.8,
        take_atr=10.0,
        take_atr_step=2.0,
        take_atr_max=24.0,
        take_atr_buffer_pct=0.0,
        volume_mult=1.25,
        regime_switch=True,
        trend_ma_gap_min=0.003,
        range_adx_max=18,
        range_bb_width_max=0.04,
        range_rsi_low=25,
        range_rsi_high=70,
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

        CREATE TABLE IF NOT EXISTS paper_capital_allocations (
            scope TEXT NOT NULL,
            key TEXT NOT NULL,
            pct REAL NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (scope, key)
        );

        CREATE TABLE IF NOT EXISTS paper_security_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            password_hash TEXT NOT NULL,
            password_is_default INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
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
            params_json = json.dumps(config.params.to_dict())
            self.conn.execute(
                """
                INSERT OR IGNORE INTO paper_strategies(symbol, interval, params_json, enabled, updated_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (config.symbol, config.interval, params_json, now),
            )
            self.conn.execute(
                """
                UPDATE paper_strategies
                SET params_json = ?, updated_at = ?
                WHERE symbol = ? AND interval = ? AND params_json != ?
                """,
                (params_json, now, config.symbol, config.interval, params_json),
            )
        for symbol, pct in PAPER_DEFAULT_SYMBOL_ALLOCATIONS.items():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO paper_capital_allocations(scope, key, pct, updated_at)
                VALUES ('symbol', ?, ?, ?)
                """,
                (symbol, pct, now),
            )
        for interval, pct in PAPER_DEFAULT_INTERVAL_ALLOCATIONS.items():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO paper_capital_allocations(scope, key, pct, updated_at)
                VALUES ('interval', ?, ?, ?)
                """,
                (interval, pct, now),
            )
        security_insert = self.conn.execute(
            """
            INSERT OR IGNORE INTO paper_security_settings(id, password_hash, password_is_default, updated_at)
            VALUES (1, ?, 1, ?)
            """,
            (_password_hash(PAPER_INITIAL_SETTINGS_PASSWORD), now),
        )
        if security_insert.rowcount == 1:
            self.conn.execute(
                "UPDATE paper_accounts SET leverage = ?, updated_at = ? WHERE id = 1 AND leverage = 0",
                (PAPER_DEFAULT_LEVERAGE, now),
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
                if position is not None:
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
        trigger_conditions = [self._strategy_trigger_condition(row) for row in strategies]
        for row in strategies:
            row["last_processed_close_time"] = last_processed_close_boundary_time(
                row.get("last_processed_open_time"),
                row.get("interval"),
            )
            row["params"] = json.loads(row.pop("params_json"))
        for row in events:
            row["payload"] = json.loads(row.pop("payload_json"))
        return {
            "account": account,
            "strategies": strategies,
            "trigger_conditions": trigger_conditions,
            "positions": positions,
            "trade_records": trade_records,
            "trades": trades,
            "events": events,
            "equity_curve": list(reversed(curves)),
            "capital_allocation": self._capital_allocation_status(account, strategies),
            "security": self.security_status(),
        }

    def security_status(self) -> dict[str, Any]:
        self.initialize()
        row = self.conn.execute("SELECT password_is_default FROM paper_security_settings WHERE id = 1").fetchone()
        return {"password_change_required": bool(row["password_is_default"]) if row is not None else True}

    def update_capital_allocation(self, symbols: dict[str, float], intervals: dict[str, float]) -> None:
        symbol_values = self._validated_allocation("symbol", symbols, PAPER_DEFAULT_SYMBOL_ALLOCATIONS)
        interval_values = self._validated_allocation("interval", intervals, PAPER_DEFAULT_INTERVAL_ALLOCATIONS)
        now = _now_ms()
        for key, pct in symbol_values.items():
            self.conn.execute(
                """
                INSERT INTO paper_capital_allocations(scope, key, pct, updated_at)
                VALUES ('symbol', ?, ?, ?)
                ON CONFLICT(scope, key) DO UPDATE SET pct=excluded.pct, updated_at=excluded.updated_at
                """,
                (key, pct, now),
            )
        for key, pct in interval_values.items():
            self.conn.execute(
                """
                INSERT INTO paper_capital_allocations(scope, key, pct, updated_at)
                VALUES ('interval', ?, ?, ?)
                ON CONFLICT(scope, key) DO UPDATE SET pct=excluded.pct, updated_at=excluded.updated_at
                """,
                (key, pct, now),
            )
        self.conn.commit()

    def update_capital_settings(self, symbols: dict[str, float], intervals: dict[str, float], leverage: float) -> None:
        leverage_value = self._validated_leverage(leverage)
        self.update_capital_allocation(symbols, intervals)
        self.conn.execute("UPDATE paper_accounts SET leverage = ?, updated_at = ? WHERE id = 1", (leverage_value, _now_ms()))
        self.conn.commit()

    def save_capital_settings_with_password(
        self,
        symbols: dict[str, float],
        intervals: dict[str, float],
        leverage: float,
        password: str,
        new_password: str | None = None,
    ) -> None:
        self._verify_settings_password(password)
        if self.security_status()["password_change_required"]:
            if not new_password:
                raise ValueError("首次保存必须修改初始密码")
            self._set_settings_password(new_password)
        elif new_password:
            self._set_settings_password(new_password)
        self.update_capital_settings(symbols, intervals, leverage)

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

    def _verify_settings_password(self, password: str) -> None:
        row = self.conn.execute("SELECT password_hash FROM paper_security_settings WHERE id = 1").fetchone()
        if row is None or not hmac.compare_digest(str(row["password_hash"]), _password_hash(password or "")):
            raise ValueError("密码错误")

    def _set_settings_password(self, password: str) -> None:
        normalized = str(password or "")
        if len(normalized) < 6:
            raise ValueError("新密码至少 6 位")
        if normalized == PAPER_INITIAL_SETTINGS_PASSWORD:
            raise ValueError("新密码不能继续使用初始密码")
        self.conn.execute(
            "UPDATE paper_security_settings SET password_hash = ?, password_is_default = 0, updated_at = ? WHERE id = 1",
            (_password_hash(normalized), _now_ms()),
        )
        self.conn.commit()

    def _load_strategy(self, symbol: str, interval: str) -> Any:
        return self.conn.execute(
            "SELECT * FROM paper_strategies WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        ).fetchone()

    def _strategy_trigger_condition(self, strategy: dict[str, Any]) -> dict[str, Any]:
        symbol = str(strategy["symbol"])
        interval = str(strategy["interval"])
        if not int(strategy["enabled"]):
            return _trigger_condition(symbol, interval, "DISABLED", "HOLD", None, None, "策略停用")

        params = params_from_dict(json.loads(strategy["params_json"]))
        candles = self._recent_candles(symbol, interval, _warmup_count(params))
        if not candles:
            return _trigger_condition(symbol, interval, "NO_DATA", "HOLD", None, None, "暂无本地 K 线数据")

        enriched = enrich_candles(candles, params)
        current = enriched[-1]
        previous = enriched[-2] if len(enriched) >= 2 else None
        signal = str(current.get("signal") or "HOLD")
        open_time = int(current["open_time"])
        close_time = int(current["close_time"])
        if _missing_signal_inputs(current, params, previous):
            return _trigger_condition(symbol, interval, "DATA_INSUFFICIENT", "HOLD", open_time, close_time, "指标预热不足")
        if signal in ("LONG", "SHORT"):
            return _trigger_condition(symbol, interval, "SATISFIED", signal, open_time, close_time, f"满足 {signal} 触发条件")
        failed_checks = _unsatisfied_trigger_checks(current, params, previous)
        return _trigger_condition(
            symbol,
            interval,
            "UNSATISFIED",
            "HOLD",
            open_time,
            close_time,
            "未满足触发条件",
            failed_checks,
        )

    def _recent_candles(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self.conn.execute(
                """
                SELECT * FROM candles
                WHERE symbol = ? AND interval = ?
                ORDER BY open_time DESC
                LIMIT ?
                """,
                (symbol, interval, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in reversed(rows)]

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
    ) -> Position | None:
        slippage_rate = float(account["slippage_rate"])
        fee_rate = float(account["fee_rate"])
        entry_price = float(row["open"]) * (1 + slippage_rate if side == "LONG" else 1 - slippage_rate)
        equity = float(account["equity"])
        initial_equity = float(account["initial_equity"])
        entry_base = equity if bool(account["compound"]) else min(equity, initial_equity)
        slot_available = self._available_allocation_margin(symbol, interval, account)
        entry_base = min(entry_base, slot_available)
        if entry_base <= 0:
            self._record_event(
                symbol,
                interval,
                "SKIP_OPEN_NO_CAPITAL",
                {"side": side, "entry_time": int(row["open_time"]), "available_margin": slot_available},
            )
            return None
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

    def _capital_allocation_status(self, account: dict[str, Any], strategies: list[dict[str, Any]]) -> dict[str, Any]:
        symbols = self._allocation_map("symbol", PAPER_DEFAULT_SYMBOL_ALLOCATIONS)
        intervals = self._allocation_map("interval", PAPER_DEFAULT_INTERVAL_ALLOCATIONS)
        equity = float(account["equity"])
        leverage = float(account["leverage"])
        used = {
            (row["symbol"], row["interval"]): float(row["used_margin"] or 0)
            for row in self.conn.execute(
                """
                SELECT symbol, interval, SUM(entry_margin) AS used_margin
                FROM paper_positions
                GROUP BY symbol, interval
                """
            )
        }
        slots = []
        for strategy in strategies:
            symbol = strategy["symbol"]
            interval = strategy["interval"]
            allocated = equity * symbols.get(symbol, 0.0) / 100 * intervals.get(interval, 0.0) / 100
            used_margin = used.get((symbol, interval), 0.0)
            slots.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "symbol_pct": symbols.get(symbol, 0.0),
                    "interval_pct": intervals.get(interval, 0.0),
                    "allocated_margin": round(allocated, 4),
                    "used_margin": round(used_margin, 4),
                    "available_margin": round(max(0.0, allocated - used_margin), 4),
                }
            )
        return {"symbols": symbols, "intervals": intervals, "leverage": leverage, "slots": slots}

    def _available_allocation_margin(self, symbol: str, interval: str, account: Any) -> float:
        symbols = self._allocation_map("symbol", PAPER_DEFAULT_SYMBOL_ALLOCATIONS)
        intervals = self._allocation_map("interval", PAPER_DEFAULT_INTERVAL_ALLOCATIONS)
        allocated = float(account["equity"]) * symbols.get(symbol, 0.0) / 100 * intervals.get(interval, 0.0) / 100
        row = self.conn.execute(
            "SELECT SUM(entry_margin) AS used_margin FROM paper_positions WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        ).fetchone()
        used_margin = float(row["used_margin"] or 0) if row is not None else 0.0
        return max(0.0, allocated - used_margin)

    def _allocation_map(self, scope: str, defaults: dict[str, float]) -> dict[str, float]:
        rows = self.conn.execute("SELECT key, pct FROM paper_capital_allocations WHERE scope = ?", (scope,)).fetchall()
        values = dict(defaults)
        for row in rows:
            values[row["key"]] = float(row["pct"])
        return values

    def _validated_leverage(self, leverage: float) -> float:
        try:
            value = float(leverage)
        except (TypeError, ValueError) as exc:
            raise ValueError("杠杆不是数字") from exc
        if value < 0 or value > 125:
            raise ValueError("杠杆必须在 0-125")
        return value

    def _validated_allocation(self, scope: str, values: dict[str, float], defaults: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key in defaults:
            try:
                pct = float(values[key])
            except KeyError as exc:
                raise ValueError(f"缺少{scope}资金配置：{key}") from exc
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{scope}资金配置不是数字：{key}") from exc
            if pct < 0 or pct > 100:
                raise ValueError(f"{scope}资金配置必须在 0-100：{key}")
            normalized[key] = pct
        total = sum(normalized.values())
        if total > 100.0001:
            raise ValueError(f"{scope}资金配置总和不能超过 100")
        return normalized


def _now_ms() -> int:
    return int(time.time() * 1000)


def _password_hash(password: str) -> str:
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def _warmup_count(params: StrategyParams) -> int:
    periods = [
        params.ema_period,
        params.ma_period,
        params.rsi_period,
        params.atr_period,
        params.adx_period,
        26,
        20,
    ]
    return max(max(int(value or 0) for value in periods) + 5, 60)


def _missing_signal_inputs(row: dict[str, Any], params: StrategyParams, previous: dict[str, Any] | None) -> bool:
    required = ["ema", "ma", "rsi", "atr", "macd_hist", "bb_upper", "bb_lower", "adx", "volume_sma"]
    if any(row.get(key) is None for key in required):
        return True
    if params.regime_switch and row.get("bb_mid") is None:
        return True
    if previous is None:
        return True
    return False


def _unsatisfied_trigger_checks(
    row: dict[str, Any],
    params: StrategyParams,
    previous: dict[str, Any] | None,
) -> list[str]:
    if params.regime_switch:
        regime = market_regime_for(row, params)
        if regime == "RANGE":
            return _range_trigger_checks(row, params)
        if regime != "TREND":
            return [f"市场状态 {regime}，未达到趋势或震荡开仓条件"]
    return _trend_trigger_checks(row, params, previous)


def _trend_trigger_checks(row: dict[str, Any], params: StrategyParams, previous: dict[str, Any] | None) -> list[str]:
    close = float(row["close"])
    ema_value = float(row["ema"])
    ma_value = float(row["ma"])
    rsi_value = float(row["rsi"])
    adx_value = float(row["adx"])
    volume_value = float(row["volume"])
    volume_required = float(row["volume_sma"]) * params.volume_mult
    checks: list[str] = []

    if adx_value < params.adx_min:
        checks.append(f"ADX {_fmt(adx_value)} < 最小值 {_fmt(params.adx_min)}")
    if volume_value < volume_required:
        checks.append(f"成交量 {_fmt(volume_value)} < 均量要求 {_fmt(volume_required)}")

    if ema_value >= ma_value:
        if close <= ema_value:
            checks.append(f"收盘价 {_fmt(close)} 未站上 EMA {_fmt(ema_value)}")
        if not (params.long_rsi_min <= rsi_value <= params.long_rsi_max):
            checks.append(
                f"多头 RSI {_fmt(rsi_value)} 不在 {_fmt(params.long_rsi_min)}-{_fmt(params.long_rsi_max)}"
            )
        if row.get("plus_di") is None or row.get("minus_di") is None or float(row["plus_di"]) <= float(row["minus_di"]):
            checks.append("多头方向指标未占优")
        if float(row["macd_hist"]) <= 0 and not _long_reentry_candidate(row, previous):
            checks.append("MACD 动能未支持多头，且未形成趋势内再入场")
        if close > float(row["bb_upper"]) * 1.01:
            checks.append("收盘价高于布林上轨追涨过滤")
    else:
        if close >= ema_value:
            checks.append(f"收盘价 {_fmt(close)} 未跌破 EMA {_fmt(ema_value)}")
        if not (params.short_rsi_min <= rsi_value <= params.short_rsi_max):
            checks.append(
                f"空头 RSI {_fmt(rsi_value)} 不在 {_fmt(params.short_rsi_min)}-{_fmt(params.short_rsi_max)}"
            )
        if row.get("plus_di") is None or row.get("minus_di") is None or float(row["minus_di"]) <= float(row["plus_di"]):
            checks.append("空头方向指标未占优")
        if float(row["macd_hist"]) >= 0:
            checks.append("MACD 动能未支持空头")
        if close < float(row["bb_lower"]) * 0.99:
            checks.append("收盘价低于布林下轨追空过滤")

    if not checks:
        checks.append("趋势、动能、RSI、成交量未同时满足")
    return checks


def _range_trigger_checks(row: dict[str, Any], params: StrategyParams) -> list[str]:
    close = float(row["close"])
    rsi_value = float(row["rsi"])
    lower_entry = float(row["bb_lower"]) * 1.01
    upper_entry = float(row["bb_upper"]) * 0.99
    checks: list[str] = []
    if close > lower_entry and close < upper_entry:
        checks.append("价格未触及震荡区间上下轨")
    if rsi_value > params.range_rsi_low and rsi_value < params.range_rsi_high:
        checks.append(
            f"震荡 RSI {_fmt(rsi_value)} 未低于 {_fmt(params.range_rsi_low)} 或高于 {_fmt(params.range_rsi_high)}"
        )
    if not checks:
        checks.append("震荡开仓条件未同时满足")
    return checks


def _long_reentry_candidate(row: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if previous is None or previous.get("ema") is None or previous.get("ma") is None:
        return False
    close = float(row["close"])
    previous_close = float(previous["close"])
    return previous_close <= float(previous["ema"]) and close > float(row["ema"]) or (
        previous_close <= float(previous["ma"]) and close > float(row["ma"])
    )


def _fmt(value: float) -> str:
    return f"{float(value):.2f}"


def _trigger_condition(
    symbol: str,
    interval: str,
    status: str,
    signal: str,
    open_time: int | None,
    close_time: int | None,
    message: str,
    failed_checks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "interval": interval,
        "status": status,
        "signal": signal,
        "current_open_time": open_time,
        "current_close_time": close_time,
        "message": message,
        "failed_checks": failed_checks or [],
    }


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
