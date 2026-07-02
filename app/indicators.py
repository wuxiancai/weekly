from __future__ import annotations


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    window_sum = 0.0
    for i, value in enumerate(values):
        window_sum += value
        if i >= period:
            window_sum -= values[i - period]
        out.append(window_sum / period if i + 1 >= period else None)
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    alpha = 2 / (period + 1)
    current: float | None = None
    for i, value in enumerate(values):
        if i + 1 < period:
            out.append(None)
            continue
        if current is None:
            current = sum(values[i + 1 - period : i + 1]) / period
        else:
            current = value * alpha + current * (1 - alpha)
        out.append(current)
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = abs(min(change, 0.0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    trs: list[float] = []
    for i, high in enumerate(highs):
        if i == 0:
            trs.append(high - lows[i])
        else:
            trs.append(max(high - lows[i], abs(high - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return wilder(trs, period)


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    line: list[float | None] = []
    compact: list[float] = []
    compact_indexes: list[int] = []
    for i, (f, s) in enumerate(zip(fast_ema, slow_ema)):
        if f is None or s is None:
            line.append(None)
        else:
            value = f - s
            line.append(value)
            compact.append(value)
            compact_indexes.append(i)
    signal_compact = ema(compact, signal)
    signal_line: list[float | None] = [None] * len(values)
    hist: list[float | None] = [None] * len(values)
    for compact_i, original_i in enumerate(compact_indexes):
        sig = signal_compact[compact_i]
        signal_line[original_i] = sig
        if sig is not None and line[original_i] is not None:
            hist[original_i] = line[original_i] - sig
    return line, signal_line, hist


def bollinger(values: list[float], period: int = 20, std_mult: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
    mid = sma(values, period)
    upper: list[float | None] = []
    lower: list[float | None] = []
    for i, center in enumerate(mid):
        if center is None:
            upper.append(None)
            lower.append(None)
            continue
        window = values[i + 1 - period : i + 1]
        variance = sum((value - center) ** 2 for value in window) / period
        stdev = variance ** 0.5
        upper.append(center + std_mult * stdev)
        lower.append(center - std_mult * stdev)
    return mid, upper, lower


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> tuple[list[float | None], list[float | None], list[float | None]]:
    plus_dm = [0.0]
    minus_dm = [0.0]
    tr = [highs[0] - lows[0]] if highs else []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr_values = wilder(tr, period)
    plus_smoothed = wilder(plus_dm, period)
    minus_smoothed = wilder(minus_dm, period)
    plus_di: list[float | None] = []
    minus_di: list[float | None] = []
    dx: list[float] = []
    dx_indexes: list[int] = []
    for i in range(len(highs)):
        if atr_values[i] is None or atr_values[i] == 0 or plus_smoothed[i] is None or minus_smoothed[i] is None:
            plus_di.append(None)
            minus_di.append(None)
            continue
        p = 100 * plus_smoothed[i] / atr_values[i]
        m = 100 * minus_smoothed[i] / atr_values[i]
        plus_di.append(p)
        minus_di.append(m)
        denom = p + m
        dx.append(100 * abs(p - m) / denom if denom else 0.0)
        dx_indexes.append(i)
    adx_compact = wilder(dx, period)
    adx_values: list[float | None] = [None] * len(highs)
    for compact_i, original_i in enumerate(dx_indexes):
        adx_values[original_i] = adx_compact[compact_i]
    return adx_values, plus_di, minus_di


def wilder(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    current: float | None = None
    for i, value in enumerate(values):
        if i + 1 < period:
            out.append(None)
            continue
        if current is None:
            current = sum(values[i + 1 - period : i + 1]) / period
        else:
            current = (current * (period - 1) + value) / period
        out.append(current)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

