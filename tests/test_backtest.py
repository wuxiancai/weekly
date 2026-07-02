import unittest

from app.backtest import Position, _exit_decision, run_backtest
from app.optimizer import walk_forward_optimize
from app.strategy import StrategyParams, enrich_candles


class BacktestTests(unittest.TestCase):
    def test_enrich_candles_adds_default_indicators(self) -> None:
        candles = _sample_candles(90)
        rows = enrich_candles(candles, StrategyParams())
        self.assertIsNotNone(rows[-1]["ema"])
        self.assertIsNotNone(rows[-1]["ma"])
        self.assertIsNotNone(rows[-1]["atr"])

    def test_backtest_returns_metrics_and_trade_list(self) -> None:
        candles = _sample_candles(120)
        result = run_backtest(candles, StrategyParams(adx_min=5, volume_mult=0.0))
        self.assertIn("total_return_pct", result["metrics"])
        self.assertIsInstance(result["trades"], list)
        self.assertTrue(result["equity_curve"])

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
