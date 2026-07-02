from __future__ import annotations

from itertools import product
from typing import Any

from .backtest import run_backtest
from .strategy import StrategyParams


def optimize(candles: list[dict[str, Any]], max_results: int = 20) -> list[dict[str, Any]]:
    grid = {
        "ema_period": [8, 13, 15, 21],
        "ma_period": [34, 50, 60],
        "adx_min": [14.0, 18.0, 22.0],
        "stop_atr": [1.8, 2.4, 3.0],
        "take_atr": [3.0, 4.2, 5.5],
        "volume_mult": [0.6, 0.75, 0.9],
    }
    results: list[dict[str, Any]] = []
    keys = list(grid.keys())
    for values in product(*(grid[key] for key in keys)):
        candidate = dict(zip(keys, values))
        if candidate["ema_period"] >= candidate["ma_period"]:
            continue
        params = StrategyParams(**candidate)
        result = run_backtest(candles, params)
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

