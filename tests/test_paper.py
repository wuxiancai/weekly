import sqlite3
import unittest

from app.main import HTML
from app.paper import (
    PAPER_DEFAULT_INITIAL_EQUITY,
    PaperEngine,
    init_paper_schema,
    paper_strategy_defaults,
)


class PaperTradingTests(unittest.TestCase):
    def test_paper_defaults_use_shared_1000_usdt_account_and_daily_4h_strategies(self) -> None:
        strategies = paper_strategy_defaults()

        self.assertEqual(PAPER_DEFAULT_INITIAL_EQUITY, 1000.0)
        self.assertEqual(
            [(s.symbol, s.interval) for s in strategies],
            [("BTCUSDT", "1d"), ("BTCUSDT", "4h"), ("ETHUSDT", "1d"), ("ETHUSDT", "4h")],
        )
        params_by_key = {(s.symbol, s.interval): s.params for s in strategies}
        self.assertFalse(params_by_key[("BTCUSDT", "1d")].regime_switch)
        self.assertEqual(params_by_key[("BTCUSDT", "1d")].ema_period, 8)
        self.assertEqual(params_by_key[("BTCUSDT", "1d")].take_atr, 13.0)
        self.assertFalse(params_by_key[("ETHUSDT", "1d")].regime_switch)
        self.assertEqual(params_by_key[("ETHUSDT", "1d")].ema_period, 15)
        self.assertEqual(params_by_key[("ETHUSDT", "1d")].take_atr, 6.5)
        self.assertTrue(params_by_key[("BTCUSDT", "4h")].regime_switch)
        self.assertTrue(params_by_key[("ETHUSDT", "4h")].regime_switch)

    def test_paper_engine_initializes_account_and_strategies_once(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)

        engine.initialize()
        engine.initialize()

        account = conn.execute("SELECT * FROM paper_accounts WHERE id = 1").fetchone()
        strategies = conn.execute("SELECT * FROM paper_strategies ORDER BY symbol, interval").fetchall()

        self.assertEqual(account["initial_equity"], 1000.0)
        self.assertEqual(account["equity"], 1000.0)
        self.assertEqual(len(strategies), 4)

    def test_process_closed_candles_is_idempotent_for_same_candle(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()
        candles = _sample_4h_candles(90)

        first = engine.process_strategy("BTCUSDT", "4h", candles)
        second = engine.process_strategy("BTCUSDT", "4h", candles)

        strategy = conn.execute(
            "SELECT * FROM paper_strategies WHERE symbol = ? AND interval = ?",
            ("BTCUSDT", "4h"),
        ).fetchone()
        curve_rows = conn.execute("SELECT COUNT(*) AS count FROM paper_equity_curve").fetchone()

        self.assertGreater(first.processed, 0)
        self.assertEqual(second.processed, 0)
        self.assertEqual(strategy["last_processed_open_time"], candles[-1]["open_time"])
        self.assertEqual(curve_rows["count"], first.processed)

    def test_web_page_links_to_paper_trading_status(self) -> None:
        self.assertIn('href="/paper">模拟交易</a>', HTML)


def _sample_4h_candles(count: int) -> list[dict]:
    rows = []
    price = 20000.0
    step = 4 * 60 * 60 * 1000
    start = 1636934400000
    for i in range(count):
        drift = 1.006 if i < count * 0.6 else 0.994
        open_price = price
        close = price * drift
        high = max(open_price, close) * 1.012
        low = min(open_price, close) * 0.988
        rows.append(
            {
                "symbol": "BTCUSDT",
                "interval": "4h",
                "open_time": start + i * step,
                "close_time": start + (i + 1) * step - 1,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000 + i,
                "quote_volume": (1000 + i) * close,
                "trades": 100 + i,
            }
        )
        price = close
    return rows


if __name__ == "__main__":
    unittest.main()
