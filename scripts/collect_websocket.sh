#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SYMBOL="${1:-BTCUSDT}"
INTERVAL="${2:-1w}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.websocket_collector "$SYMBOL" "$INTERVAL"

