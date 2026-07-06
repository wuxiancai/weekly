#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORTS="${PORTS:-8788 8789}"

echo "Project: ${ROOT_DIR}"
echo "Expected commit: $(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo

for port in $PORTS; do
  echo "== Port ${port} =="
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN || true
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :${port}" || true
  else
    echo "No lsof or ss available."
  fi

  runtime="$(curl -fsS "http://${HOST}:${port}/api/system/runtime" 2>/dev/null || true)"
  if [ -n "$runtime" ]; then
    echo "$runtime"
  else
    echo "runtime API unavailable"
  fi

  paper_head="$(curl -fsS "http://${HOST}:${port}/paper" 2>/dev/null | sed -n '1,80p' || true)"
  if echo "$paper_head" | grep -q "BTCUSDT / ETHUSDT U本位永续合约模拟交易"; then
    echo "paper HTML: OLD hardcoded title"
  elif echo "$paper_head" | grep -q "币安合约交易系统"; then
    echo "paper HTML: new title"
  else
    echo "paper HTML: unknown or unavailable"
  fi
  if echo "$paper_head" | grep -q 'id="strategyIntervals"'; then
    echo "strategy intervals: dynamic element present"
  fi
  if echo "$paper_head" | grep -q "<strong>1d / 4h"; then
    echo "strategy intervals: OLD hardcoded text present"
  fi
  echo
done

if command -v systemctl >/dev/null 2>&1; then
  echo "== weekly-web unit =="
  systemctl --no-pager --full status weekly-web.service 2>/dev/null || true
  echo
  systemctl cat weekly-web.service 2>/dev/null || true
fi
