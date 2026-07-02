#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

OS_NAME="$(uname -s)"
HOST="${HOST:-0.0.0.0}"
REQUESTED_PORT="${PORT:-8000}"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python}"
else
  echo "未找到 Python。macOS 请先安装 Xcode Command Line Tools 或 Python；Ubuntu 请执行 sudo apt-get install -y python3 python3-venv。"
  exit 1
fi

case "$OS_NAME" in
  Darwin)
    PLATFORM="macOS"
    ;;
  Linux)
    if [ -f /etc/os-release ] && grep -qi ubuntu /etc/os-release; then
      PLATFORM="Ubuntu"
    else
      PLATFORM="Linux"
    fi
    ;;
  *)
    PLATFORM="$OS_NAME"
    ;;
esac

if [ ! -d ".venv" ]; then
  if ! "$PYTHON_BIN" -m venv .venv; then
    echo "创建虚拟环境失败。Ubuntu 通常需要安装 python3-venv：sudo apt-get install -y python3-venv"
    exit 1
  fi
fi

. .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

PORT="$(python - "$REQUESTED_PORT" <<'PY'
import socket
import sys

start = int(sys.argv[1])
for port in range(start, start + 50):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        if sock.connect_ex(("127.0.0.1", port)) != 0:
            print(port)
            raise SystemExit(0)
raise SystemExit(f"No available port from {start} to {start + 49}")
PY
)"

echo "系统: ${PLATFORM}"
echo "监听: http://127.0.0.1:${PORT} 以及 http://0.0.0.0:${PORT}"
echo "停止: Ctrl+C"

exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT"

