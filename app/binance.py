from __future__ import annotations

import time
from typing import Any

import requests

from .config import DEFAULTS
from .timeutils import parse_date_ms


BASE_URL = "https://fapi.binance.com"
WS_BASE_URL = "wss://fstream.binance.com/ws"


class BinanceClient:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_klines(
        self,
        symbol: str = DEFAULTS.symbol,
        interval: str = DEFAULTS.interval,
        start_date: str = DEFAULTS.start_date,
        end_date: str = DEFAULTS.end_date,
        limit: int = 1500,
    ) -> list[dict[str, Any]]:
        start_ms = parse_date_ms(start_date)
        end_ms = parse_date_ms(end_date)
        rows: list[dict[str, Any]] = []
        cursor = start_ms
        while cursor <= end_ms:
            payload = self._get_klines(symbol, interval, cursor, end_ms, limit)
            if not payload:
                break
            batch = [self._normalize_kline(symbol, interval, item) for item in payload]
            rows.extend(batch)
            next_cursor = int(payload[-1][0]) + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            time.sleep(0.15)
            if len(payload) < limit:
                break
        return [row for row in rows if start_ms <= row["open_time"] <= end_ms]

    def fetch_klines_ms(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int = 1500,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor = start_ms
        while cursor <= end_ms:
            payload = self._get_klines(symbol, interval, cursor, end_ms, limit)
            if not payload:
                break
            rows.extend(self._normalize_kline(symbol, interval, item) for item in payload)
            next_cursor = int(payload[-1][0]) + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            time.sleep(0.15)
            if len(payload) < limit:
                break
        return [row for row in rows if start_ms <= row["open_time"] <= end_ms]

    def fetch_24hr_tickers(self, symbols: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            response = requests.get(
                f"{self.base_url}/fapi/v1/ticker/24hr",
                params={"symbol": symbol.upper()},
                timeout=10,
            )
            response.raise_for_status()
            rows.append(response.json())
        return rows

    def fetch_utc_day_tickers(self, symbols: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            symbol = symbol.upper()
            price_response = requests.get(
                f"{self.base_url}/fapi/v1/ticker/price",
                params={"symbol": symbol},
                timeout=10,
            )
            price_response.raise_for_status()
            kline_response = requests.get(
                f"{self.base_url}/fapi/v1/klines",
                params={"symbol": symbol, "interval": "1d", "limit": 1},
                timeout=10,
            )
            kline_response.raise_for_status()
            price_payload = price_response.json()
            kline = kline_response.json()[0]
            rows.append(
                {
                    "symbol": symbol,
                    "lastPrice": price_payload["price"],
                    "utcOpenPrice": kline[1],
                    "eventTime": int(price_payload.get("time") or kline[6]),
                }
            )
        return rows

    def _get_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int) -> list[list[Any]]:
        response = requests.get(
            f"{self.base_url}/fapi/v1/klines",
            params={
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": limit,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _normalize_kline(symbol: str, interval: str, item: list[Any]) -> dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "open_time": int(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
            "close_time": int(item[6]),
            "quote_volume": float(item[7]),
            "trades": int(item[8]),
        }
