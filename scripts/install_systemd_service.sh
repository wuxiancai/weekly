#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${SERVICE_NAME:-btc-auto-trader}"
USER_NAME="${SERVICE_USER:-$(whoami)}"
PORT="${PORT:-8000}"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd 不可用，当前系统不支持安装 service" >&2
  exit 1
fi

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<SERVICE
[Unit]
Description=BTCUSDT simulated auto trading web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${ROOT_DIR}
Environment=HOST=0.0.0.0
Environment=PORT=${PORT}
ExecStart=/usr/bin/env bash ${ROOT_DIR}/scripts/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"
sudo systemctl status "${SERVICE_NAME}.service" --no-pager

