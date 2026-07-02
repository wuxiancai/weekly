from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "trading.db"


@dataclass(frozen=True)
class MarketDefaults:
    symbol: str = "BTCUSDT"
    interval: str = "1w"
    start_date: str = "2019-09-02"
    end_date: str = "2026-06-29"
    initial_equity: float = 10000.0
    leverage: float = 0.0
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0002


DEFAULTS = MarketDefaults()
