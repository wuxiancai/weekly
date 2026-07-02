import unittest

from app.backtest import Position, _exit_decision, run_backtest
from app.config import DEFAULTS
from app.main import ETH_HTML, HTML
from app.optimizer import walk_forward_optimize
from app.strategy import StrategyParams, enrich_candles, signal_for


class BacktestTests(unittest.TestCase):
    def test_enrich_candles_adds_default_indicators(self) -> None:
        candles = _sample_candles(90)
        rows = enrich_candles(candles, StrategyParams())
        self.assertIsNotNone(rows[-1]["ema"])
        self.assertIsNotNone(rows[-1]["ma"])
        self.assertIsNotNone(rows[-1]["atr"])

    def test_default_start_date_is_september_2019(self) -> None:
        self.assertEqual(DEFAULTS.start_date, "2019-09-02")

    def test_default_capital_and_leverage(self) -> None:
        self.assertEqual(DEFAULTS.initial_equity, 10000.0)
        self.assertEqual(DEFAULTS.leverage, 2.0)
        self.assertTrue(DEFAULTS.compound)
        self.assertEqual(DEFAULTS.fee_rate, 0.0005)
        self.assertEqual(DEFAULTS.slippage_rate, 0.0005)

    def test_page_names_usdt_margined_futures_pnl_units(self) -> None:
        self.assertIn("BTCUSDT U本位永续合约", HTML)
        self.assertIn("USDT 保证金 / USDT 结算", HTML)
        self.assertIn("收益(USDT)", HTML)
        self.assertIn("合约数量(BTC)", HTML)
        self.assertIn("多单收益 = (出场价 - 入场价) * 合约数量", HTML)

    def test_page_exposes_compound_toggle_defaulting_to_yes(self) -> None:
        self.assertIn("复利", HTML)
        self.assertIn('<select id="compound">', HTML)
        self.assertIn('<option value="false">NO</option>', HTML)
        self.assertIn('<option value="true" selected>YES</option>', HTML)

    def test_page_places_optimization_below_trades_and_shows_trade_metrics(self) -> None:
        self.assertLess(HTML.index("逐笔交易"), HTML.index("参数优化结果"))
        self.assertIn("收益率", HTML)
        self.assertIn("盈亏比", HTML)
        self.assertIn("最大回撤", HTML)
        self.assertIn("收益回撤比", HTML)

    def test_home_links_to_eth_daily_backtest_page(self) -> None:
        self.assertIn('href="/eth">ETH 回测</a>', HTML)
        self.assertIn("ETHUSDT U本位永续合约日线回测系统", ETH_HTML)
        self.assertIn('href="/">BTC 回测</a>', ETH_HTML)
        self.assertIn('value="ETHUSDT"', ETH_HTML)
        self.assertIn('const PAGE_SYMBOL = \'ETHUSDT\';', ETH_HTML)
        self.assertIn('const PAGE_INTERVAL = \'1d\';', ETH_HTML)
        self.assertIn('<option value="1d" selected>1d</option>', ETH_HTML)
        self.assertIn('id="takeAtr" type="number" step="0.1" value="6.5"', ETH_HTML)
        self.assertIn('id="takeAtrMax" type="number" step="0.5" value="24"', ETH_HTML)

    def test_page_has_independent_defaults_for_symbol_and_interval(self) -> None:
        self.assertIn('<select id="interval" onchange="applyIntervalDefaults()">', HTML)
        self.assertIn('<option value="1w" selected>1w</option>', HTML)
        self.assertIn('<option value="1d">1d</option>', HTML)
        self.assertIn("const STRATEGY_DEFAULTS = {", HTML)
        self.assertIn("BTCUSDT: {", HTML)
        self.assertIn("ETHUSDT: {", HTML)
        self.assertIn("takeAtr: 6.5", HTML)
        self.assertIn("takeAtrMax: 24", HTML)
        self.assertIn("takeAtrMax: 32", HTML)
        self.assertIn("BTCUSDT: {", ETH_HTML)
        self.assertIn("ETHUSDT: {", ETH_HTML)

    def test_ma40_blocks_signals_until_40_weekly_candles_exist(self) -> None:
        rows_before = enrich_candles(_sample_candles(39), StrategyParams())
        self.assertTrue(all(row["ma"] is None for row in rows_before))
        self.assertTrue(all(row["signal"] == "HOLD" for row in rows_before))

        rows_after = enrich_candles(_sample_candles(40), StrategyParams())
        self.assertIsNone(rows_after[-2]["ma"])
        self.assertIsNotNone(rows_after[-1]["ma"])

    def test_default_strategy_uses_optimized_weekly_params(self) -> None:
        params = StrategyParams()

        self.assertEqual(params.ema_period, 15)
        self.assertEqual(params.ma_period, 40)
        self.assertEqual(params.adx_min, 0.0)
        self.assertEqual(params.long_rsi_min, 35.0)
        self.assertEqual(params.long_rsi_max, 85.0)
        self.assertEqual(params.short_rsi_min, 0.0)
        self.assertEqual(params.short_rsi_max, 100.0)
        self.assertEqual(params.stop_atr, 1.8)
        self.assertEqual(params.take_atr, 7.5)
        self.assertEqual(params.take_atr_step, 1.25)
        self.assertEqual(params.take_atr_max, 32.0)
        self.assertEqual(params.take_atr_buffer_pct, 0.0)
        self.assertEqual(params.volume_mult, 1.0)

    def test_backtest_returns_metrics_and_trade_list(self) -> None:
        candles = _sample_candles(120)
        result = run_backtest(candles, StrategyParams(adx_min=5, volume_mult=0.0))
        self.assertIn("total_return_pct", result["metrics"])
        self.assertIsInstance(result["trades"], list)
        self.assertTrue(result["equity_curve"])

    def test_trade_records_include_return_risk_and_drawdown_metrics(self) -> None:
        candles = _sample_candles(140)
        result = run_backtest(
            candles,
            StrategyParams(
                adx_min=0,
                volume_mult=0.0,
                long_rsi_min=0,
                long_rsi_max=100,
                short_rsi_min=0,
                short_rsi_max=100,
                stop_atr=10.0,
                take_atr=10.0,
            ),
        )

        trade = result["trades"][0]

        self.assertIn("pnl_pct", trade)
        self.assertIn("reward_risk_ratio", trade)
        self.assertIn("max_drawdown_pct", trade)
        self.assertIn("return_drawdown_ratio", trade)

    def test_zero_leverage_matches_unleveraged_backtest(self) -> None:
        candles = _sample_candles(140)
        params = StrategyParams(
            adx_min=0,
            volume_mult=0.0,
            long_rsi_min=0,
            long_rsi_max=100,
            short_rsi_min=0,
            short_rsi_max=100,
            stop_atr=10.0,
            take_atr=10.0,
        )

        unleveraged = run_backtest(candles, params, initial_equity=10000.0, leverage=1.0, compound=False)
        zero_leverage = run_backtest(candles, params, initial_equity=10000.0, leverage=0.0, compound=False)

        zero_metrics = dict(zero_leverage["metrics"])
        one_metrics = dict(unleveraged["metrics"])
        zero_metrics.pop("leverage")
        one_metrics.pop("leverage")
        self.assertEqual(zero_metrics, one_metrics)
        self.assertEqual(zero_leverage["trades"], unleveraged["trades"])

    def test_compound_mode_increases_position_size_after_a_winning_trade(self) -> None:
        candles = _sample_candles(140)
        params = StrategyParams(
            adx_min=0,
            volume_mult=0.0,
            long_rsi_min=0,
            long_rsi_max=100,
            short_rsi_min=0,
            short_rsi_max=100,
            stop_atr=10.0,
            take_atr=10.0,
        )

        fixed = run_backtest(candles, params, initial_equity=10000.0, leverage=0.0, compound=False)
        compounded = run_backtest(candles, params, initial_equity=10000.0, leverage=0.0, compound=True)

        self.assertGreater(len(compounded["trades"]), 1)
        self.assertGreater(
            compounded["trades"][1]["quantity"],
            fixed["trades"][1]["quantity"],
        )
        self.assertGreater(
            compounded["metrics"]["final_equity"],
            fixed["metrics"]["final_equity"],
        )

    def test_positive_leverage_changes_fixed_principal_backtest_result(self) -> None:
        candles = _sample_candles(140)
        params = StrategyParams(
            adx_min=0,
            volume_mult=0.0,
            long_rsi_min=0,
            long_rsi_max=100,
            short_rsi_min=0,
            short_rsi_max=100,
            stop_atr=10.0,
            take_atr=10.0,
        )

        unleveraged = run_backtest(candles, params, initial_equity=10000.0, leverage=0.0, compound=False)
        leveraged = run_backtest(candles, params, initial_equity=10000.0, leverage=2.0, compound=False)

        self.assertNotEqual(leveraged["metrics"]["final_equity"], unleveraged["metrics"]["final_equity"])
        self.assertGreater(leveraged["metrics"]["total_return_pct"], unleveraged["metrics"]["total_return_pct"])

    def test_entries_execute_after_signal_candle_to_avoid_lookahead(self) -> None:
        candles = _sample_candles(140)
        result = run_backtest(
            candles,
            StrategyParams(
                adx_min=0,
                volume_mult=0.0,
                long_rsi_min=0,
                long_rsi_max=100,
                short_rsi_min=0,
                short_rsi_max=100,
                stop_atr=10.0,
                take_atr=10.0,
            ),
        )
        self.assertTrue(result["trades"])
        for trade in result["trades"]:
            self.assertGreater(trade["entry_time"], trade["signal_time"])

    def test_stop_loss_requires_close_confirmation_not_intrabar_wick(self) -> None:
        position = Position(
            side="LONG",
            signal_time=1,
            entry_time=2,
            entry_price=64925.68,
            quantity=1.0,
            stop_price=50177.89,
            take_price=90734.32,
            entry_equity=1000.0,
        )

        exit_price, exit_reason = _exit_decision(
            position,
            high=62737.20,
            low=48888.00,
            close=58693.10,
            signal="HOLD",
        )

        self.assertIsNone(exit_price)
        self.assertEqual(exit_reason, "")

    def test_dynamic_take_profit_ratchets_before_exit(self) -> None:
        position = Position(
            side="LONG",
            signal_time=1,
            entry_time=2,
            entry_price=100.0,
            quantity=1.0,
            stop_price=76.0,
            take_price=180.0,
            entry_equity=1000.0,
            atr=10.0,
            take_atr_step=0.5,
            take_atr_max=10.0,
        )

        exit_price, exit_reason = _exit_decision(position, high=190.0, low=170.0, close=190.0, signal="HOLD")

        self.assertIsNone(exit_price)
        self.assertEqual(exit_reason, "")
        self.assertEqual(position.take_price, 190.0)

        exit_price, exit_reason = _exit_decision(position, high=196.0, low=189.0, close=195.0, signal="HOLD")
        self.assertIsNone(exit_price)
        self.assertEqual(exit_reason, "")
        self.assertEqual(position.take_price, 195.0)

        exit_price, exit_reason = _exit_decision(position, high=196.0, low=180.0, close=194.0, signal="HOLD")

        self.assertEqual(exit_price, 195.0)
        self.assertEqual(exit_reason, "TRAIL_TAKE_PROFIT")

    def test_signal_allows_long_reentry_after_pullback_reclaims_trend(self) -> None:
        params = StrategyParams(volume_mult=1.0, long_rsi_min=35, long_rsi_max=85)
        previous = {
            "close": 96.0,
            "ema": 100.0,
            "ma": 90.0,
        }
        row = {
            "close": 106.0,
            "ema": 101.0,
            "ma": 91.0,
            "rsi": 60.0,
            "atr": 5.0,
            "macd_hist": -1.0,
            "bb_upper": 105.0,
            "bb_lower": 80.0,
            "adx": 20.0,
            "plus_di": 30.0,
            "minus_di": 20.0,
            "volume": 125.0,
            "volume_sma": 100.0,
        }

        self.assertEqual(signal_for(row, params, previous), "LONG")

    def test_walk_forward_reports_train_and_test_metrics(self) -> None:
        candles = _sample_candles(140)
        result = walk_forward_optimize(candles, train_ratio=0.7, max_results=3)
        self.assertGreater(result["train_count"], result["test_count"])
        self.assertLessEqual(len(result["items"]), 3)
        self.assertIn("train_metrics", result["items"][0])
        self.assertIn("test_metrics", result["items"][0])


def _sample_candles(count: int) -> list[dict]:
    rows = []
    price = 20000.0
    week = 7 * 24 * 60 * 60 * 1000
    start = 1636934400000
    for i in range(count):
        drift = 1.018 if i < count * 0.55 else 0.982
        open_price = price
        close = price * drift
        high = max(open_price, close) * 1.04
        low = min(open_price, close) * 0.96
        rows.append(
            {
                "symbol": "BTCUSDT",
                "interval": "1w",
                "open_time": start + i * week,
                "close_time": start + (i + 1) * week - 1,
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
