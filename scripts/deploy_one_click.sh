#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WEB_SERVICE="${WEB_SERVICE:-weekly-web}"
LEGACY_PAPER_SERVICE="${LEGACY_PAPER_SERVICE:-weekly-paper}"
SERVICE_USER="${SERVICE_USER:-$(whoami)}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
PAPER_POLL_SECONDS="${PAPER_POLL_SECONDS:-60}"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "当前系统没有 systemd，无法安装长期运行服务。请在 Ubuntu 云服务器上执行。"
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip curl ca-certificates
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python}"
else
  echo "未找到 Python，请先安装 python3 python3-venv。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ] && [ -x "$ROOT_DIR/.venv/bin/python3" ]; then
  VENV_PYTHON="$ROOT_DIR/.venv/bin/python3"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

chmod +x "$ROOT_DIR/start.sh" "$ROOT_DIR/scripts/start.sh" "$ROOT_DIR/scripts/run_paper.sh"

sudo tee "/etc/systemd/system/${WEB_SERVICE}.service" >/dev/null <<SERVICE
[Unit]
Description=Weekly BTCUSDT/ETHUSDT web backtest and paper runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${ROOT_DIR}
Environment=HOST=${HOST}
Environment=PORT=${PORT}
Environment=PAPER_POLL_SECONDS=${PAPER_POLL_SECONDS}
ExecStart=/usr/bin/env bash ${ROOT_DIR}/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

if systemctl list-unit-files "${LEGACY_PAPER_SERVICE}.service" >/dev/null 2>&1; then
  sudo systemctl stop "${LEGACY_PAPER_SERVICE}.service" 2>/dev/null || true
  sudo systemctl disable "${LEGACY_PAPER_SERVICE}.service" 2>/dev/null || true
fi
if [ -f "/etc/systemd/system/${LEGACY_PAPER_SERVICE}.service" ]; then
  sudo rm -f "/etc/systemd/system/${LEGACY_PAPER_SERVICE}.service"
fi

sudo systemctl daemon-reload
sudo systemctl enable "${WEB_SERVICE}.service"
sudo systemctl restart "${WEB_SERVICE}.service"

echo "部署完成"
echo "Web: http://服务器IP:${PORT}"
echo "模拟交易状态页: http://服务器IP:${PORT}/paper"
echo "所有服务由 start.sh 统一启动；查看日志: sudo journalctl -u ${WEB_SERVICE} -f"
sudo systemctl --no-pager --full status "${WEB_SERVICE}.service"
