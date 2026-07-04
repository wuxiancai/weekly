import sqlite3
import unittest

import app.main as main
from app.main import HTML, PAPER_HTML
from app.paper import (
    PAPER_DEFAULT_INITIAL_EQUITY,
    PaperEngine,
    init_paper_schema,
    paper_strategy_defaults,
)


class PaperTradingTests(unittest.TestCase):
    def test_paper_defaults_use_shared_1000_usdt_account_and_daily_4h_1h_strategies(self) -> None:
        strategies = paper_strategy_defaults()

        self.assertEqual(PAPER_DEFAULT_INITIAL_EQUITY, 1000.0)
        self.assertEqual(
            [(s.symbol, s.interval) for s in strategies],
            [
                ("BTCUSDT", "1d"),
                ("BTCUSDT", "4h"),
                ("BTCUSDT", "1h"),
                ("ETHUSDT", "1d"),
                ("ETHUSDT", "4h"),
                ("ETHUSDT", "1h"),
            ],
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
        self.assertTrue(params_by_key[("BTCUSDT", "1h")].regime_switch)
        self.assertTrue(params_by_key[("ETHUSDT", "1h")].regime_switch)
        self.assertEqual(params_by_key[("BTCUSDT", "1h")].ema_period, 12)
        self.assertEqual(params_by_key[("BTCUSDT", "1h")].adx_min, 18)
        self.assertEqual(params_by_key[("BTCUSDT", "1h")].stop_atr, 0.45)
        self.assertEqual(params_by_key[("BTCUSDT", "1h")].take_atr_max, 12.0)
        self.assertEqual(params_by_key[("ETHUSDT", "1h")].ma_period, 50)
        self.assertEqual(params_by_key[("ETHUSDT", "1h")].take_atr, 1.8)
        self.assertEqual(params_by_key[("ETHUSDT", "1h")].range_bb_width_max, 0.12)

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
        self.assertEqual(len(strategies), 6)

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

    def test_paper_page_shows_realtime_futures_ticker_and_utc8_clock(self) -> None:
        self.assertIn('id="marketTicker"', PAPER_HTML)
        self.assertIn('id="tickerBtc"', PAPER_HTML)
        self.assertIn('id="tickerEth"', PAPER_HTML)
        self.assertIn('id="utc8Clock"', PAPER_HTML)
        self.assertIn("BTC 永续", PAPER_HTML)
        self.assertIn("ETH 永续", PAPER_HTML)
        self.assertIn("UTC+8", PAPER_HTML)

    def test_market_tickers_api_returns_btc_eth_futures_price_changes(self) -> None:
        class FakeClient:
            def fetch_24hr_tickers(self, symbols: list[str]) -> list[dict]:
                self.symbols = symbols
                return [
                    {"symbol": "BTCUSDT", "lastPrice": "62498.30", "priceChangePercent": "1.23", "closeTime": 1783180800000},
                    {"symbol": "ETHUSDT", "lastPrice": "3420.10", "priceChangePercent": "-0.45", "closeTime": 1783180801000},
                ]

        original_client = main.BinanceClient
        fake = FakeClient()
        main.BinanceClient = lambda: fake
        try:
            data = main.market_tickers()
        finally:
            main.BinanceClient = original_client

        self.assertEqual(fake.symbols, ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(data["timezone"], "UTC+0")
        self.assertEqual(data["items"][0]["symbol"], "BTCUSDT")
        self.assertEqual(data["items"][0]["price"], 62498.3)
        self.assertEqual(data["items"][0]["change_pct"], 1.23)
        self.assertEqual(data["items"][1]["symbol"], "ETHUSDT")
        self.assertEqual(data["items"][1]["price"], 3420.1)
        self.assertEqual(data["items"][1]["change_pct"], -0.45)


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
