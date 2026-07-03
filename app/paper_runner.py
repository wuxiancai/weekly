from __future__ import annotations

import os
import time

from .binance import BinanceClient
from .db import connect, init_db, load_candles, upsert_candles
from .paper import PaperEngine, init_paper_schema, paper_strategy_defaults


INTERVAL_MS = {
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}

WARMUP_CANDLES = int(os.getenv("PAPER_WARMUP_CANDLES", "500"))
POLL_SECONDS = int(os.getenv("PAPER_POLL_SECONDS", "60"))


def run_once() -> list[dict]:
    init_db()
    client = BinanceClient()
    results = []
    with connect() as conn:
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()
        for strategy in paper_strategy_defaults():
            try:
                rows = _fetch_closed_warmup(client, strategy.symbol, strategy.interval)
                stored = upsert_candles(rows)
                latest_open_time = rows[-1]["open_time"] if rows else None
                strategy_row = conn.execute(
                    "SELECT last_processed_open_time FROM paper_strategies WHERE symbol = ? AND interval = ?",
                    (strategy.symbol, strategy.interval),
                ).fetchone()
                if strategy_row is not None and strategy_row["last_processed_open_time"] is None:
                    primed = engine.prime_strategy(strategy.symbol, strategy.interval, rows)
                    result = {
                        "symbol": strategy.symbol,
                        "interval": strategy.interval,
                        "stored": stored,
                        "primed": primed,
                        "processed": 0,
                        "opened": 0,
                        "closed": 0,
                    }
                else:
                    candles = load_candles(strategy.symbol, strategy.interval, _warmup_start_ms(strategy.interval), int(time.time() * 1000))
                    processed = engine.process_strategy(strategy.symbol, strategy.interval, candles)
                    result = {
                        "symbol": strategy.symbol,
                        "interval": strategy.interval,
                        "stored": stored,
                        "latest_open_time": latest_open_time,
                        "processed": processed.processed,
                        "opened": processed.opened,
                        "closed": processed.closed,
                    }
                results.append(result)
                engine.record_event(strategy.symbol, strategy.interval, "RUN_ONCE", result)
            except Exception as exc:  # pragma: no cover - exercised by real service runtime
                payload = {"error": str(exc)}
                results.append({"symbol": strategy.symbol, "interval": strategy.interval, **payload})
                engine.record_event(strategy.symbol, strategy.interval, "ERROR", payload)
    return results


def run_forever() -> None:
    while True:
        results = run_once()
        print({"paper_results": results}, flush=True)
        time.sleep(POLL_SECONDS)


def _fetch_closed_warmup(client: BinanceClient, symbol: str, interval: str) -> list[dict]:
    now_ms = int(time.time() * 1000)
    rows = client.fetch_klines_ms(symbol, interval, _warmup_start_ms(interval), now_ms)
    return [row for row in rows if int(row["close_time"]) < now_ms]


def _warmup_start_ms(interval: str) -> int:
    now_ms = int(time.time() * 1000)
    return now_ms - INTERVAL_MS[interval] * WARMUP_CANDLES


if __name__ == "__main__":
    run_forever()
