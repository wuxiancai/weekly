from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .indicators import adx, atr, bollinger, ema, macd, rsi, sma


@dataclass(frozen=True)
class StrategyParams:
    ema_period: int = 15
    ma_period: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    adx_period: int = 14
    adx_min: float = 18.0
    long_rsi_min: float = 42.0
    long_rsi_max: float = 72.0
    short_rsi_min: float = 28.0
    short_rsi_max: float = 58.0
    stop_atr: float = 2.4
    take_atr: float = 4.2
    volume_mult: float = 0.75

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def enrich_candles(candles: list[dict[str, Any]], params: StrategyParams) -> list[dict[str, Any]]:
    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]
    ema_values = ema(closes, params.ema_period)
    ma_values = sma(closes, params.ma_period)
    rsi_values = rsi(closes, params.rsi_period)
    atr_values = atr(highs, lows, closes, params.atr_period)
    macd_line, macd_signal, macd_hist = macd(closes)
    bb_mid, bb_upper, bb_lower = bollinger(closes)
    adx_values, plus_di, minus_di = adx(highs, lows, closes, params.adx_period)
    vol_sma = sma(volumes, 20)

    out: list[dict[str, Any]] = []
    for i, candle in enumerate(candles):
        item = dict(candle)
        item.update(
            {
                "ema": ema_values[i],
                "ma": ma_values[i],
                "rsi": rsi_values[i],
                "atr": atr_values[i],
                "macd": macd_line[i],
                "macd_signal": macd_signal[i],
                "macd_hist": macd_hist[i],
                "bb_mid": bb_mid[i],
                "bb_upper": bb_upper[i],
                "bb_lower": bb_lower[i],
                "adx": adx_values[i],
                "plus_di": plus_di[i],
                "minus_di": minus_di[i],
                "volume_sma": vol_sma[i],
            }
        )
        previous = out[-1] if out else None
        item["signal"] = signal_for(item, params, previous)
        out.append(item)
    return out


def signal_for(row: dict[str, Any], params: StrategyParams, previous: dict[str, Any] | None = None) -> str:
    required = ["ema", "ma", "rsi", "atr", "macd_hist", "bb_upper", "bb_lower", "adx", "volume_sma"]
    if any(row.get(key) is None for key in required):
        return "HOLD"

    close = float(row["close"])
    volume_ok = float(row["volume"]) >= float(row["volume_sma"]) * params.volume_mult
    trend_long = row["ema"] > row["ma"] and close > row["ema"]
    trend_short = row["ema"] < row["ma"] and close < row["ema"]
    momentum_long = row["macd_hist"] > 0 and row["plus_di"] is not None and row["plus_di"] > row["minus_di"]
    momentum_short = row["macd_hist"] < 0 and row["minus_di"] is not None and row["minus_di"] > row["plus_di"]
    strong_trend = row["adx"] >= params.adx_min
    long_rsi_ok = params.long_rsi_min <= row["rsi"] <= params.long_rsi_max
    short_rsi_ok = params.short_rsi_min <= row["rsi"] <= params.short_rsi_max
    not_upper_chase = close <= row["bb_upper"] * 1.01
    not_lower_chase = close >= row["bb_lower"] * 0.99

    if trend_long and momentum_long and strong_trend and long_rsi_ok and not_upper_chase and volume_ok:
        return "LONG"
    if _long_trend_reentry(row, previous) and strong_trend and long_rsi_ok and volume_ok:
        return "LONG"
    if trend_short and momentum_short and strong_trend and short_rsi_ok and not_lower_chase and volume_ok:
        return "SHORT"
    return "HOLD"


def _long_trend_reentry(row: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if previous is None or previous.get("ema") is None or previous.get("ma") is None:
        return False
    close = float(row["close"])
    previous_close = float(previous["close"])
    reclaimed_ema = previous_close <= float(previous["ema"]) and close > float(row["ema"])
    reclaimed_ma = previous_close <= float(previous["ma"]) and close > float(row["ma"])
    trend_still_long = row["ema"] > row["ma"] and close > row["ema"]
    direction_ok = row["plus_di"] is not None and row["minus_di"] is not None and row["plus_di"] > row["minus_di"]
    return trend_still_long and direction_ok and (reclaimed_ema or reclaimed_ma)


def params_from_dict(data: dict[str, Any]) -> StrategyParams:
    allowed = StrategyParams().__dict__.keys()
    clean = {key: data[key] for key in allowed if key in data and data[key] is not None}
    return StrategyParams(**clean)
