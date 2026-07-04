from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backtest import run_backtest
from app.db import load_candles
from app.strategy import StrategyParams
from app.timeutils import parse_date_ms


DAY_MS = 24 * 60 * 60 * 1000
DEFAULT_END = "2026-06-29"
WINDOWS = {
    "1m": "2026-06-02",
    "2m": "2026-05-01",
    "6m": "2026-01-02",
    "full": "2019-09-02",
}


@dataclass(frozen=True)
class Candidate:
    label: str
    params: StrategyParams


def main() -> None:
    parser = argparse.ArgumentParser(description="Segmented 1h parameter search for BTCUSDT/ETHUSDT.")
    parser.add_argument("--symbol", choices=["BTCUSDT", "ETHUSDT", "ALL"], default="ALL")
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--warmup-days", type=int, default=90)
    parser.add_argument("--out-dir", default="reports/1h_segmented")
    parser.add_argument("--windows", default="1m,2m,6m", help="Comma separated windows: 1m,2m,6m,full")
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    symbols = ["BTCUSDT", "ETHUSDT"] if args.symbol == "ALL" else [args.symbol]
    candidates = list(candidate_grid())
    selected_windows = [name.strip() for name in args.windows.split(",") if name.strip()]
    unknown_windows = [name for name in selected_windows if name not in WINDOWS]
    if unknown_windows:
        raise SystemExit(f"unknown windows: {','.join(unknown_windows)}")
    print(f"candidates={len(candidates)} windows={','.join(selected_windows)} symbols={','.join(symbols)}", flush=True)

    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "end": args.end,
        "warmup_days": args.warmup_days,
        "candidate_count": len(candidates),
        "symbols": {},
    }

    for symbol in symbols:
        symbol_summary: dict[str, Any] = {}
        for window_name in selected_windows:
            start_date = WINDOWS[window_name]
            rows = evaluate_window(
                symbol=symbol,
                start_date=start_date,
                end_date=args.end,
                warmup_days=args.warmup_days,
                candidates=candidates,
            )
            rows.sort(key=lambda row: row["metrics"]["total_return_pct"], reverse=True)
            raw_path = out_dir / f"{symbol}_1h_{window_name}_raw.csv"
            write_rows(raw_path, rows)
            leaders = build_leaders(rows, args.top_n)
            symbol_summary[window_name] = {
                "start": start_date,
                "raw_csv": str(raw_path),
                "leaders": leaders,
            }
            print(
                f"{symbol} {window_name} {start_date}->{args.end} "
                f"evaluated={len(rows)} top_return={leaders['return'][0]['total_return_pct'] if leaders['return'] else 'n/a'}",
                flush=True,
            )
        summary["symbols"][symbol] = symbol_summary

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary={summary_path}", flush=True)


def candidate_grid() -> list[Candidate]:
    trend_pairs = [(8, 35), (12, 35), (15, 50)]
    exit_profiles = [
        (1.8, 0.5, 4.0),
        (2.5, 0.5, 4.0),
        (3.5, 0.5, 8.0),
        (4.0, 1.0, 12.0),
    ]
    range_profiles = [
        (22.0, 0.05, 35.0, 65.0),
        (22.0, 0.12, 30.0, 65.0),
    ]
    rsi_profiles = [
        (50.0, 80.0),
        (55.0, 85.0),
    ]
    out: list[Candidate] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for (ema_period, ma_period), adx_min, stop_atr, exit_profile, volume_mult, range_profile, rsi_profile in product(
        trend_pairs,
        [18.0, 25.0, 35.0],
        [0.45, 0.8, 1.5],
        exit_profiles,
        [1.0, 1.25],
        range_profiles,
        rsi_profiles,
    ):
        take_atr, take_atr_step, take_atr_max = exit_profile
        range_adx_max, range_bb_width_max, range_low, range_high = range_profile
        long_min, long_max = rsi_profile
        for atr_period in [14]:
            params = StrategyParams(
                ema_period=ema_period,
                ma_period=ma_period,
                rsi_period=14,
                atr_period=atr_period,
                adx_period=14,
                adx_min=adx_min,
                long_rsi_min=long_min,
                long_rsi_max=long_max,
                short_rsi_min=0.0,
                short_rsi_max=100.0,
                stop_atr=stop_atr,
                take_atr=take_atr,
                take_atr_step=take_atr_step,
                take_atr_max=take_atr_max,
                volume_mult=volume_mult,
                regime_switch=True,
                trend_ma_gap_min=0.0,
                range_adx_max=range_adx_max,
                range_bb_width_max=range_bb_width_max,
                range_rsi_low=range_low,
                range_rsi_high=range_high,
            )
            fingerprint = tuple(sorted(params.to_dict().items()))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            out.append(Candidate(label=param_label(params), params=params))
    return out


def evaluate_window(
    symbol: str,
    start_date: str,
    end_date: str,
    warmup_days: int,
    candidates: list[Candidate],
) -> list[dict[str, Any]]:
    start_ms = parse_date_ms(start_date)
    end_ms = parse_date_ms(end_date)
    warmup_start = max(0, start_ms - warmup_days * DAY_MS)
    candles = load_candles(symbol, "1h", warmup_start, end_ms)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        result = run_backtest(
            candles,
            candidate.params,
            initial_equity=10000.0,
            leverage=0.0,
            compound=True,
            fee_rate=0.0005,
            slippage_rate=0.0005,
            start_trading_ms=start_ms,
        )
        metrics = result["metrics"]
        if metrics["trade_count"] < min_trade_count(start_date):
            continue
        rows.append(
            {
                "symbol": symbol,
                "window_start": start_date,
                "window_end": end_date,
                "label": candidate.label,
                "params": candidate.params.to_dict(),
                "metrics": metrics,
            }
        )
    return rows


def min_trade_count(start_date: str) -> int:
    if start_date == WINDOWS["1m"]:
        return 8
    if start_date == WINDOWS["2m"]:
        return 15
    if start_date == WINDOWS["6m"]:
        return 40
    return 300


def build_leaders(rows: list[dict[str, Any]], top_n: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "return": compact(sorted(rows, key=lambda row: row["metrics"]["total_return_pct"], reverse=True)[:top_n]),
        "win_rate": compact(sorted(rows, key=lambda row: (row["metrics"]["win_rate_pct"], row["metrics"]["total_return_pct"]), reverse=True)[:top_n]),
        "low_max_trade_drawdown": compact(sorted(rows, key=lambda row: (row["metrics"]["max_drawdown_pct"], -row["metrics"]["total_return_pct"]))[:top_n]),
        "profit_factor": compact(sorted(rows, key=lambda row: (row["metrics"]["profit_factor"], row["metrics"]["total_return_pct"]), reverse=True)[:top_n]),
        "return_drawdown_ratio": compact(sorted(rows, key=lambda row: (row["metrics"]["return_drawdown_ratio"], row["metrics"]["total_return_pct"]), reverse=True)[:top_n]),
    }


def compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        metrics = row["metrics"]
        out.append(
            {
                "label": row["label"],
                "total_return_pct": metrics["total_return_pct"],
                "max_trade_drawdown_pct": metrics["max_drawdown_pct"],
                "equity_max_drawdown_pct": metrics["equity_max_drawdown_pct"],
                "trade_count": metrics["trade_count"],
                "win_rate_pct": metrics["win_rate_pct"],
                "profit_factor": metrics["profit_factor"],
                "return_drawdown_ratio": metrics["return_drawdown_ratio"],
                "params": row["params"],
            }
        )
    return out


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "symbol",
        "window_start",
        "window_end",
        "label",
        "total_return_pct",
        "max_trade_drawdown_pct",
        "equity_max_drawdown_pct",
        "trade_count",
        "win_rate_pct",
        "profit_factor",
        "return_drawdown_ratio",
        "params_json",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            metrics = row["metrics"]
            writer.writerow(
                {
                    "symbol": row["symbol"],
                    "window_start": row["window_start"],
                    "window_end": row["window_end"],
                    "label": row["label"],
                    "total_return_pct": metrics["total_return_pct"],
                    "max_trade_drawdown_pct": metrics["max_drawdown_pct"],
                    "equity_max_drawdown_pct": metrics["equity_max_drawdown_pct"],
                    "trade_count": metrics["trade_count"],
                    "win_rate_pct": metrics["win_rate_pct"],
                    "profit_factor": metrics["profit_factor"],
                    "return_drawdown_ratio": metrics["return_drawdown_ratio"],
                    "params_json": json.dumps(row["params"], sort_keys=True),
                }
            )


def param_label(params: StrategyParams) -> str:
    return (
        f"EMA{params.ema_period}/MA{params.ma_period} "
        f"ADX>={params.adx_min:g} RSI{params.long_rsi_min:g}-{params.long_rsi_max:g} "
        f"SL{params.stop_atr:g} TP{params.take_atr:g}/{params.take_atr_step:g}/{params.take_atr_max:g} "
        f"VOL{params.volume_mult:g} R{params.range_adx_max:g}/{params.range_bb_width_max:g}/"
        f"{params.range_rsi_low:g}-{params.range_rsi_high:g}"
    )


if __name__ == "__main__":
    main()
