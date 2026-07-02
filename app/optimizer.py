from __future__ import annotations

from itertools import product
from typing import Any

from .backtest import run_backtest
from .config import DEFAULTS
from .strategy import StrategyParams


def optimize(
    candles: list[dict[str, Any]],
    max_results: int = 20,
    start_trading_ms: int | None = None,
    initial_equity: float = DEFAULTS.initial_equity,
    leverage: float = DEFAULTS.leverage,
    fee_rate: float = DEFAULTS.fee_rate,
    slippage_rate: float = DEFAULTS.slippage_rate,
) -> list[dict[str, Any]]:
    grid = {
        "ema_period": [15],
        "ma_period": [40],
        "adx_min": [0.0, 14.0],
        "stop_atr": [1.8, 2.4, 3.0],
        "take_atr": [6.5, 7.5, 8.0],
        "take_atr_step": [1.0, 1.25],
        "take_atr_max": [20.0, 24.0, 32.0],
        "volume_mult": [1.0],
    }
    rsi_profiles = [
        {"long_rsi_min": 35.0, "long_rsi_max": 85.0, "short_rsi_min": 0.0, "short_rsi_max": 100.0},
        {"long_rsi_min": 55.0, "long_rsi_max": 75.0, "short_rsi_min": 0.0, "short_rsi_max": 100.0},
    ]
    results: list[dict[str, Any]] = []
    keys = list(grid.keys())
    for values in product(*(grid[key] for key in keys)):
        candidate = dict(zip(keys, values))
        if candidate["ema_period"] >= candidate["ma_period"]:
            continue
        for rsi_profile in rsi_profiles:
            params = StrategyParams(**candidate, **rsi_profile)
            result = run_backtest(
                candles,
                params,
                initial_equity=initial_equity,
                leverage=leverage,
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
                start_trading_ms=start_trading_ms,
            )
            metrics = result["metrics"]
            if metrics["trade_count"] < 2:
                continue
            score = (
                metrics["total_return_pct"]
                - metrics["max_drawdown_pct"] * 0.35
                + metrics["win_rate_pct"] * 0.05
                + min(metrics["trade_count"], 20) * 0.1
            )
            results.append({"params": params.to_dict(), "metrics": metrics, "score": round(score, 4)})
    results.sort(key=lambda item: (item["metrics"]["total_return_pct"], item["score"]), reverse=True)
    return results[:max_results]


def walk_forward_optimize(
    candles: list[dict[str, Any]],
    train_ratio: float = 0.7,
    max_results: int = 10,
) -> dict[str, Any]:
    if len(candles) < 90:
        raise ValueError("Walk-forward 至少需要 90 根 K 线")
    split_index = int(len(candles) * train_ratio)
    split_index = min(max(split_index, 60), len(candles) - 20)
    train = candles[:split_index]
    test_start_ms = int(candles[split_index]["open_time"])
    train_results = optimize(train, max_results=max(max_results * 3, 12))
    evaluated: list[dict[str, Any]] = []
    for candidate in train_results:
        params = StrategyParams(**candidate["params"])
        test_result = run_backtest(candles, params, start_trading_ms=test_start_ms)
        train_metrics = candidate["metrics"]
        test_metrics = test_result["metrics"]
        stability_score = _stability_score(train_metrics, test_metrics)
        evaluated.append(
            {
                "params": params.to_dict(),
                "train_metrics": train_metrics,
                "test_metrics": test_metrics,
                "score": stability_score,
            }
        )
    evaluated.sort(
        key=lambda item: (
            item["test_metrics"]["total_return_pct"],
            item["score"],
            -item["test_metrics"]["max_drawdown_pct"],
        ),
        reverse=True,
    )
    return {
        "train_count": len(train),
        "test_count": len(candles) - split_index,
        "train_start": int(candles[0]["open_time"]),
        "train_end": int(candles[split_index - 1]["open_time"]),
        "test_start": test_start_ms,
        "test_end": int(candles[-1]["open_time"]),
        "items": evaluated[:max_results],
    }


def _stability_score(train_metrics: dict[str, Any], test_metrics: dict[str, Any]) -> float:
    train_return = float(train_metrics["total_return_pct"])
    test_return = float(test_metrics["total_return_pct"])
    test_drawdown = float(test_metrics["max_drawdown_pct"])
    return round(test_return - test_drawdown * 0.5 - max(train_return - test_return, 0) * 0.1, 4)
