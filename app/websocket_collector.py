from __future__ import annotations

import asyncio
import json
import sys

import websockets

from .binance import WS_BASE_URL, BinanceClient
from .db import init_db, upsert_candles


async def collect(symbol: str = "BTCUSDT", interval: str = "1w") -> None:
    init_db()
    stream = f"{symbol.lower()}@kline_{interval}"
    url = f"{WS_BASE_URL}/{stream}"
    async with websockets.connect(url, ping_interval=20, ping_timeout=60) as ws:
        async for raw in ws:
            event = json.loads(raw)
            kline = event.get("k", {})
            if not kline:
                continue
            row = {
                "symbol": symbol.upper(),
                "interval": interval,
                "open_time": int(kline["t"]),
                "close_time": int(kline["T"]),
                "open": float(kline["o"]),
                "high": float(kline["h"]),
                "low": float(kline["l"]),
                "close": float(kline["c"]),
                "volume": float(kline["v"]),
                "quote_volume": float(kline["q"]),
                "trades": int(kline["n"]),
            }
            upsert_candles([row])
            print(f"stored {symbol} {interval} {row['open_time']} close={row['close']}", flush=True)


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    interval = sys.argv[2] if len(sys.argv) > 2 else "1w"
    asyncio.run(collect(symbol, interval))


if __name__ == "__main__":
    main()

