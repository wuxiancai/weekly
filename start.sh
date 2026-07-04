#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

OS_NAME="$(uname -s)"
HOST="${HOST:-0.0.0.0}"
REQUESTED_PORT="${PORT:-8000}"
PAPER_POLL_SECONDS="${PAPER_POLL_SECONDS:-60}"

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
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
  if [ -x "$ROOT_DIR/.venv/bin/python3" ]; then
    VENV_PYTHON="$ROOT_DIR/.venv/bin/python3"
  else
    echo "虚拟环境里未找到 Python，请删除 .venv 后重新执行 start.sh。"
    exit 1
  fi
fi

"$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
"$VENV_PYTHON" -m pip install -r requirements.txt

stop_existing_project_processes() {
  local patterns=(
    "$ROOT_DIR/.venv/bin/python.*uvicorn app.main:app"
    "$ROOT_DIR/.venv/bin/python3.*uvicorn app.main:app"
    "$ROOT_DIR/.venv/bin/python.*app.paper_runner"
    "$ROOT_DIR/.venv/bin/python3.*app.paper_runner"
  )
  local pid
  local pids=()

  for pattern in "${patterns[@]}"; do
    while IFS= read -r pid; do
      [ -n "$pid" ] || continue
      [ "$pid" != "$$" ] || continue
      pids+=("$pid")
    done < <(pgrep -f "$pattern" 2>/dev/null || true)
  done

  if [ "${#pids[@]}" -gt 0 ]; then
    echo "发现本项目已有运行进程，先停止: ${pids[*]}"
    kill "${pids[@]}" 2>/dev/null || true
    sleep 2
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
  fi
}

stop_existing_project_processes

PORT="$("$VENV_PYTHON" - "$REQUESTED_PORT" <<'PY'
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
echo "回测系统: FastAPI Web/API"
echo "模拟交易系统: Paper runner，每 ${PAPER_POLL_SECONDS} 秒轮询已收盘 K 线"
echo "停止: Ctrl+C 或 systemctl stop weekly-web"

mkdir -p runtime/logs

PAPER_PID=""
WEB_PID=""

cleanup() {
  local status="${1:-0}"
  trap - EXIT INT TERM
  if [ -n "$WEB_PID" ] && kill -0 "$WEB_PID" 2>/dev/null; then
    kill "$WEB_PID" 2>/dev/null || true
  fi
  if [ -n "$PAPER_PID" ] && kill -0 "$PAPER_PID" 2>/dev/null; then
    kill "$PAPER_PID" 2>/dev/null || true
  fi
  wait "$WEB_PID" 2>/dev/null || true
  wait "$PAPER_PID" 2>/dev/null || true
  exit "$status"
}

trap 'cleanup 0' INT TERM
trap 'cleanup $?' EXIT

PAPER_POLL_SECONDS="$PAPER_POLL_SECONDS" "$VENV_PYTHON" -m app.paper_runner >> runtime/logs/paper_runner.log 2>&1 &
PAPER_PID="$!"
echo "模拟交易系统已启动: pid=${PAPER_PID}, log=runtime/logs/paper_runner.log"

"$VENV_PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" &
WEB_PID="$!"
echo "Web/回测系统已启动: pid=${WEB_PID}"

while true; do
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    set +e
    wait "$WEB_PID"
    status="$?"
    set -e
    cleanup "$status"
  fi
  if ! kill -0 "$PAPER_PID" 2>/dev/null; then
    set +e
    wait "$PAPER_PID"
    status="$?"
    set -e
    cleanup "$status"
  fi
  sleep 2
done
