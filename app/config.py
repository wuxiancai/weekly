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
    start_date: str = "2021-11-15"
    end_date: str = "2026-07-02"
    initial_equity: float = 1000.0
    fee_rate: float = 0.0004
    slippage_rate: float = 0.0002


DEFAULTS = MarketDefaults()

