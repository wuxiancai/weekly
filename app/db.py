from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR, DB_PATH


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                close_time INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL NOT NULL,
                trades INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, interval, open_time)
            );

            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                params_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                side TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                exit_time INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                quantity REAL NOT NULL,
                pnl REAL NOT NULL,
                pnl_pct REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS optimization_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                params_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS live_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                event_time INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def upsert_candles(rows: Iterable[dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO candles (
                symbol, interval, open_time, close_time, open, high, low, close,
                volume, quote_volume, trades, updated_at
            )
            VALUES (
                :symbol, :interval, :open_time, :close_time, :open, :high, :low,
                :close, :volume, :quote_volume, :trades, CURRENT_TIMESTAMP
            )
            ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
                close_time=excluded.close_time,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                quote_volume=excluded.quote_volume,
                trades=excluded.trades,
                updated_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
    return len(rows)


def load_candles(symbol: str, interval: str, start_ms: int | None = None, end_ms: int | None = None) -> list[dict[str, Any]]:
    where = ["symbol = ?", "interval = ?"]
    args: list[Any] = [symbol, interval]
    if start_ms is not None:
        where.append("open_time >= ?")
        args.append(start_ms)
    if end_ms is not None:
        where.append("open_time <= ?")
        args.append(end_ms)
    sql = f"SELECT * FROM candles WHERE {' AND '.join(where)} ORDER BY open_time"
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, args)]


def insert_backtest_run(
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
    params: dict[str, Any],
    metrics: dict[str, Any],
    trades: list[dict[str, Any]],
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO backtest_runs(symbol, interval, start_date, end_date, params_json, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (symbol, interval, start_date, end_date, json.dumps(params), json.dumps(metrics)),
        )
        run_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO trades(
                run_id, side, entry_time, exit_time, entry_price, exit_price,
                quantity, pnl, pnl_pct, exit_reason
            )
            VALUES (
                :run_id, :side, :entry_time, :exit_time, :entry_price, :exit_price,
                :quantity, :pnl, :pnl_pct, :exit_reason
            )
            """,
            [dict(t, run_id=run_id) for t in trades],
        )
    return run_id


def insert_optimization_result(symbol: str, interval: str, params: dict[str, Any], metrics: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO optimization_results(symbol, interval, params_json, metrics_json)
            VALUES (?, ?, ?, ?)
            """,
            (symbol, interval, json.dumps(params), json.dumps(metrics)),
        )


def recent_backtests(limit: int = 10) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_decode_json_fields(dict(row)) for row in rows]


def recent_optimization(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM optimization_results ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_decode_json_fields(dict(row)) for row in rows]


def load_trades(run_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM trades WHERE run_id = ? ORDER BY id", (run_id,))]


def _decode_json_fields(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("params_json", "metrics_json"):
        if key in row:
            row[key.replace("_json", "")] = json.loads(row.pop(key))
    return row

