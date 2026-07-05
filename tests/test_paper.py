import json
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
    def test_paper_defaults_use_shared_1000_usdt_account_and_all_strategy_intervals(self) -> None:
        strategies = paper_strategy_defaults()

        self.assertEqual(PAPER_DEFAULT_INITIAL_EQUITY, 1000.0)
        self.assertEqual(
            [(s.symbol, s.interval) for s in strategies],
            [
                ("BTCUSDT", "1w"),
                ("BTCUSDT", "1d"),
                ("BTCUSDT", "4h"),
                ("BTCUSDT", "1h"),
                ("ETHUSDT", "1w"),
                ("ETHUSDT", "1d"),
                ("ETHUSDT", "4h"),
                ("ETHUSDT", "1h"),
            ],
        )
        params_by_key = {(s.symbol, s.interval): s.params for s in strategies}
        self.assertFalse(params_by_key[("BTCUSDT", "1w")].regime_switch)
        self.assertEqual(params_by_key[("BTCUSDT", "1w")].ema_period, 15)
        self.assertEqual(params_by_key[("BTCUSDT", "1w")].take_atr_max, 32.0)
        self.assertFalse(params_by_key[("ETHUSDT", "1w")].regime_switch)
        self.assertEqual(params_by_key[("ETHUSDT", "1w")].take_atr, 7.5)
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
        self.assertEqual(len(strategies), 8)

    def test_paper_engine_syncs_existing_strategy_params_to_code_defaults(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()

        stale_params = paper_strategy_defaults()[3].params.to_dict()
        stale_params["ema_period"] = 99
        conn.execute(
            """
            UPDATE paper_strategies
            SET params_json = ?, enabled = 0, last_processed_open_time = ?
            WHERE symbol = ? AND interval = ?
            """,
            (json.dumps(stale_params), 0, "BTCUSDT", "1h"),
        )
        conn.commit()

        engine.initialize()

        strategy = conn.execute(
            "SELECT * FROM paper_strategies WHERE symbol = ? AND interval = ?",
            ("BTCUSDT", "1h"),
        ).fetchone()
        params = json.loads(strategy["params_json"])
        expected = paper_strategy_defaults()[3].params
        self.assertEqual(params["ema_period"], expected.ema_period)
        self.assertEqual(params["take_atr_max"], expected.take_atr_max)
        self.assertEqual(strategy["enabled"], 0)
        self.assertEqual(strategy["last_processed_open_time"], 0)

    def test_paper_defaults_include_capital_allocations_by_symbol_and_interval(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()

        status = engine.status()

        allocation = status["capital_allocation"]
        self.assertEqual(allocation["symbols"], {"BTCUSDT": 80.0, "ETHUSDT": 20.0})
        self.assertEqual(allocation["intervals"], {"1h": 30.0, "4h": 40.0, "1d": 20.0, "1w": 10.0})
        slots = {(row["symbol"], row["interval"]): row for row in allocation["slots"]}
        self.assertEqual(slots[("BTCUSDT", "4h")]["allocated_margin"], 320.0)
        self.assertEqual(slots[("ETHUSDT", "4h")]["allocated_margin"], 80.0)

    def test_paper_open_position_uses_remaining_capital_allocation_slot(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()

        account = conn.execute("SELECT * FROM paper_accounts WHERE id = 1").fetchone()
        params = paper_strategy_defaults()[2].params
        previous = {"open_time": 1000}
        row = {"open_time": 2000, "open": 100.0}

        position = engine._open_position("ETHUSDT", "4h", "LONG", previous, row, 4.0, params, account)

        self.assertIsNotNone(position)
        self.assertAlmostEqual(position.entry_margin, 80.0)
        self.assertAlmostEqual(position.quantity, 80.0 / (100.0 * (1 + 0.0005)))

    def test_paper_allocation_update_keeps_existing_margin_until_position_closes(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()
        conn.execute(
            """
            INSERT INTO paper_positions(
                symbol, interval, side, signal_time, entry_time, entry_price, quantity,
                stop_price, take_price, entry_equity, atr, take_atr_start, take_atr_step,
                take_atr_max, take_atr_buffer_pct, take_profit_armed, entry_margin,
                risk_amount, max_adverse_pct, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ETHUSDT",
                "4h",
                "LONG",
                1000,
                2000,
                100.0,
                2.0,
                90.0,
                124.0,
                999.0,
                4.0,
                5.0,
                1.0,
                12.0,
                0.0,
                1,
                80.0,
                20.0,
                0.0,
                3000,
                3000,
            ),
        )
        conn.commit()

        engine.update_capital_allocation({"BTCUSDT": 70.0, "ETHUSDT": 30.0}, {"1h": 30.0, "4h": 40.0, "1d": 20.0, "1w": 10.0})

        slot = next(row for row in engine.status()["capital_allocation"]["slots"] if row["symbol"] == "ETHUSDT" and row["interval"] == "4h")
        self.assertEqual(slot["allocated_margin"], 120.0)
        self.assertEqual(slot["used_margin"], 80.0)
        self.assertEqual(slot["available_margin"], 40.0)

    def test_paper_status_returns_full_trade_records_separate_from_recent_trades(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()

        for i in range(25):
            conn.execute(
                """
                INSERT INTO paper_trades(
                    symbol, interval, side, signal_time, entry_time, exit_time, entry_price,
                    exit_price, quantity, pnl, pnl_pct, reward_risk_ratio,
                    max_drawdown_pct, return_drawdown_ratio, exit_reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "BTCUSDT",
                    "1h",
                    "LONG",
                    1000 + i,
                    2000 + i,
                    3000 + i,
                    100.0,
                    101.0,
                    1.0,
                    float(i),
                    float(i),
                    1.0,
                    0.5,
                    2.0,
                    "TEST",
                    4000 + i,
                ),
            )
        conn.commit()

        status = engine.status()

        self.assertEqual(len(status["trades"]), 20)
        self.assertEqual(len(status["trade_records"]), 25)
        self.assertGreater(status["trade_records"][0]["id"], status["trade_records"][-1]["id"])

    def test_paper_status_enriches_positions_with_initial_take_and_liquidation_price(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_paper_schema(conn)
        engine = PaperEngine(conn)
        engine.initialize()
        conn.execute(
            """
            INSERT INTO paper_positions(
                symbol, interval, side, signal_time, entry_time, entry_price, quantity,
                stop_price, take_price, entry_equity, atr, take_atr_start, take_atr_step,
                take_atr_max, take_atr_buffer_pct, take_profit_armed, entry_margin,
                risk_amount, max_adverse_pct, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ETHUSDT",
                "4h",
                "LONG",
                1000,
                2000,
                100.0,
                2.0,
                90.0,
                124.0,
                999.0,
                4.0,
                5.0,
                1.0,
                12.0,
                0.0,
                1,
                80.0,
                20.0,
                0.0,
                3000,
                3000,
            ),
        )
        conn.commit()

        status = engine.status()

        position = status["positions"][0]
        self.assertEqual(position["initial_take_price"], 120.0)
        self.assertEqual(position["latest_take_price"], 124.0)
        self.assertEqual(position["liquidation_price"], 60.0)

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
        self.assertIn("<h1>币安合约交易系统</h1>", PAPER_HTML)
        self.assertNotIn("<h1>BTCUSDT / ETHUSDT U本位永续合约模拟交易</h1>", PAPER_HTML)
        self.assertIn('id="marketTicker"', PAPER_HTML)
        self.assertIn('id="tickerBtc"', PAPER_HTML)
        self.assertIn('id="tickerEth"', PAPER_HTML)
        self.assertIn('id="utc8Clock"', PAPER_HTML)
        self.assertIn("BTC 永续", PAPER_HTML)
        self.assertIn("ETH 永续", PAPER_HTML)
        self.assertIn("UTC+8", PAPER_HTML)
        self.assertEqual(PAPER_HTML.count('class="ticker-row"'), 1)
        self.assertNotIn('class="clock-row"', PAPER_HTML)
        self.assertIn("openMarketTickerStream()", PAPER_HTML)
        self.assertIn("wss://fstream.binance.com/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker", PAPER_HTML)
        self.assertIn("dataset.streamState = 'open';", PAPER_HTML)
        self.assertIn("dataset.streamUpdates", PAPER_HTML)
        self.assertIn("setInterval(loadMarketTicker, 60000);", PAPER_HTML)
        self.assertNotIn("setInterval(loadMarketTicker, 10000);", PAPER_HTML)

    def test_paper_page_shows_scrollable_trade_records_before_recent_closed_trades(self) -> None:
        self.assertLess(PAPER_HTML.index("<h2>交易记录</h2>"), PAPER_HTML.index("<h2>最近平仓</h2>"))
        self.assertIn('class="trade-records-scroll"', PAPER_HTML)
        self.assertIn('id="tradeRecords"', PAPER_HTML)
        self.assertIn("fillTradeRecords(data.trade_records || data.trades || []);", PAPER_HTML)
        self.assertIn("function fillTradeRecords(items)", PAPER_HTML)

    def test_paper_trade_rows_color_return_rate_by_profit_or_loss(self) -> None:
        self.assertIn('<td class="${t.pnl_pct >= 0 ? \'pos\' : \'neg\'}">${Number(t.pnl_pct).toFixed(2)}%</td>', PAPER_HTML)

    def test_paper_page_shows_intervals_amounts_and_formatted_log_times(self) -> None:
        self.assertIn("<th>交易对</th><th>周期</th><th>方向</th>", PAPER_HTML)
        self.assertIn("<th>入场价</th><th>强平价格</th><th>数量</th><th>保证金</th>", PAPER_HTML)
        self.assertIn("<th>止损</th><th>保护/止盈</th><th>最新止盈</th>", PAPER_HTML)
        self.assertIn("formatAmount(p.entry_margin)", PAPER_HTML)
        self.assertIn("formatPrice(p.liquidation_price)", PAPER_HTML)
        self.assertIn('<td class="neg">${formatPrice(p.stop_price)}</td>', PAPER_HTML)
        self.assertIn('<td class="pos">${formatPrice(p.initial_take_price)}</td>', PAPER_HTML)
        self.assertIn('<td class="pos">${formatPrice(p.latest_take_price)}</td>', PAPER_HTML)
        self.assertIn("symbolClass(value)", PAPER_HTML)
        self.assertIn("intervalClass(value)", PAPER_HTML)
        self.assertIn("function symbolCell(value)", PAPER_HTML)
        self.assertIn("function intervalCell(value)", PAPER_HTML)
        self.assertIn("function formatDateTime(ms)", PAPER_HTML)
        self.assertIn("function formatPayload(payload)", PAPER_HTML)
        self.assertIn("entry_time", PAPER_HTML)
        self.assertIn("event_time", PAPER_HTML)
        self.assertIn("interval-1w", PAPER_HTML)
        self.assertIn("interval-1d", PAPER_HTML)
        self.assertIn("interval-4h", PAPER_HTML)
        self.assertIn("interval-1h", PAPER_HTML)

    def test_paper_page_derives_strategy_intervals_from_status(self) -> None:
        self.assertIn('id="strategyIntervals"', PAPER_HTML)
        self.assertIn("updateStrategyIntervals(data.strategies || []);", PAPER_HTML)
        self.assertIn("function updateStrategyIntervals(strategies)", PAPER_HTML)
        self.assertIn("intervalOrder = ['1w', '1d', '4h', '1h'];", PAPER_HTML)
        self.assertNotIn("<strong>1d / 4h / 1h</strong>", PAPER_HTML)

    def test_paper_page_allows_capital_allocation_edits_and_explains_params_on_hover(self) -> None:
        self.assertIn('id="capitalAllocation"', PAPER_HTML)
        self.assertIn('id="allocSymbolBTCUSDT"', PAPER_HTML)
        self.assertIn('id="allocSymbolETHUSDT"', PAPER_HTML)
        self.assertIn('id="allocInterval4h"', PAPER_HTML)
        self.assertIn("saveCapitalAllocation()", PAPER_HTML)
        self.assertIn("fetch('/api/paper/capital-allocation'", PAPER_HTML)
        self.assertIn("function parameterExplanation(p)", PAPER_HTML)
        self.assertIn('title="${parameterExplanation(s.params)}"', PAPER_HTML)

    def test_paper_summary_grid_uses_adaptive_widths_for_capital_allocation(self) -> None:
        self.assertNotIn(".grid { display:grid; grid-template-columns:repeat(5,1fr);", PAPER_HTML)
        self.assertIn("grid-template-columns:minmax(150px,max-content) minmax(140px,max-content) minmax(92px,max-content) minmax(560px,1fr) minmax(210px,max-content)", PAPER_HTML)
        self.assertIn(".allocation-controls { display:flex; flex-wrap:nowrap;", PAPER_HTML)
        self.assertIn(".allocation-controls input { width:64px;", PAPER_HTML)
        self.assertIn(".allocation-controls button { flex:0 0 auto;", PAPER_HTML)

    def test_runtime_api_exposes_commit_and_paper_page_markers(self) -> None:
        data = main.system_runtime()

        self.assertIn("pid", data)
        self.assertIn("cwd", data)
        self.assertIn("app_version", data)
        self.assertIn("git_commit", data)
        self.assertTrue(data["paper_html_markers"]["dynamic_strategy_intervals"])
        self.assertTrue(data["paper_html_markers"]["new_title"])
        self.assertFalse(data["paper_html_markers"]["hardcoded_old_intervals"])

    def test_market_tickers_api_returns_utc_day_price_changes(self) -> None:
        class FakeClient:
            def fetch_utc_day_tickers(self, symbols: list[str]) -> list[dict]:
                self.symbols = symbols
                return [
                    {"symbol": "BTCUSDT", "lastPrice": "62445.50", "utcOpenPrice": "62560.50", "eventTime": 1783180800000},
                    {"symbol": "ETHUSDT", "lastPrice": "1758.71", "utcOpenPrice": "1743.53", "eventTime": 1783180801000},
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
        self.assertEqual(data["items"][0]["price"], 62445.5)
        self.assertEqual(data["items"][0]["utc_open_price"], 62560.5)
        self.assertEqual(data["items"][0]["change"], -115.0)
        self.assertEqual(data["items"][0]["change_pct"], -0.1838)
        self.assertEqual(data["items"][1]["symbol"], "ETHUSDT")
        self.assertEqual(data["items"][1]["price"], 1758.71)
        self.assertEqual(data["items"][1]["utc_open_price"], 1743.53)
        self.assertEqual(data["items"][1]["change"], 15.18)
        self.assertEqual(data["items"][1]["change_pct"], 0.8706)


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
