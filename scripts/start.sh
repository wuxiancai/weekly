#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host "$HOST" --port "$PORT"

