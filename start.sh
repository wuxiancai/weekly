#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

START_MODE="${START_MODE:-daemon}"
WEB_SERVICE="${WEB_SERVICE:-weekly-web}"
LEGACY_PAPER_SERVICE="${LEGACY_PAPER_SERVICE:-weekly-paper}"
SERVICE_USER="${SERVICE_USER:-$(whoami)}"
HOST="${HOST:-0.0.0.0}"
REQUESTED_PORT="${PORT:-8001}"
PAPER_POLL_SECONDS="${PAPER_POLL_SECONDS:-60}"
APP_VERSION="${APP_VERSION:-unknown}"
if command -v git >/dev/null 2>&1; then
  APP_VERSION="$(git rev-parse --short HEAD 2>/dev/null || echo "$APP_VERSION")"
fi
PASSTHROUGH_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --foreground)
      START_MODE="foreground"
      ;;
    --daemon)
      START_MODE="daemon"
      ;;
    --help|-h)
      echo "用法: ./start.sh [--daemon|--foreground]"
      echo "  --daemon      默认行为。systemd 环境安装/重启 weekly-web；非 systemd 环境用 nohup 后台启动。"
      echo "  --foreground  前台启动 Web 和 Paper，供 systemd 托管。"
      exit 0
      ;;
    *)
      PASSTHROUGH_ARGS+=("$arg")
      ;;
  esac
done

mkdir -p runtime/logs

has_systemd() {
  command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]
}

stop_existing_project_processes() {
  local patterns=(
    "$ROOT_DIR/start.sh"
    "$ROOT_DIR/scripts/start.sh"
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
      [ "$pid" != "${PPID:-}" ] || continue
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

install_or_restart_systemd_service() {
  if ! command -v sudo >/dev/null 2>&1; then
    return 1
  fi

  sudo systemctl stop "${WEB_SERVICE}.service" 2>/dev/null || true
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
Environment=PORT=${REQUESTED_PORT}
Environment=PAPER_POLL_SECONDS=${PAPER_POLL_SECONDS}
Environment=APP_VERSION=${APP_VERSION}
Environment=START_MODE=systemd
ExecStart=/usr/bin/env bash ${ROOT_DIR}/start.sh --foreground
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
  stop_existing_project_processes

  sudo systemctl daemon-reload
  sudo systemctl enable "${WEB_SERVICE}.service" >/dev/null
  sudo systemctl restart "${WEB_SERVICE}.service"
  echo "start.sh 已交给 systemd 托管: ${WEB_SERVICE}.service"
  echo "查看状态: sudo systemctl status ${WEB_SERVICE}"
  echo "查看日志: sudo journalctl -u ${WEB_SERVICE} -f"
}

if [ "$START_MODE" = "daemon" ]; then
  if [ "${START_USE_SYSTEMD:-1}" = "1" ] && has_systemd; then
    install_or_restart_systemd_service
    exit 0
  fi
  nohup "$0" --foreground "${PASSTHROUGH_ARGS[@]}" >> runtime/logs/start.log 2>&1 &
  SUPERVISOR_PID="$!"
  echo "$SUPERVISOR_PID" > runtime/start.pid
  echo "start.sh 已在后台启动: pid=${SUPERVISOR_PID}"
  echo "日志: runtime/logs/start.log"
  echo "停止: kill \$(cat runtime/start.pid) 或 systemctl stop weekly-web"
  exit 0
fi

echo "$$" > runtime/start.pid

OS_NAME="$(uname -s)"

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

stop_existing_project_processes

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u
  fi
}

is_project_pid() {
  local pid="$1"
  local command_line
  local cwd
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  cwd=""
  if [ -r "/proc/${pid}/cwd" ]; then
    cwd="$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)"
  elif command -v lsof >/dev/null 2>&1; then
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  fi
  if [ "$cwd" = "$ROOT_DIR" ]; then
    case "$command_line" in
      *"uvicorn app.main:app"*|*"app.paper_runner"*|*"start.sh"*)
        return 0
        ;;
    esac
  fi
  case "$command_line" in
    *"$ROOT_DIR/.venv/"*|*"$ROOT_DIR/start.sh"*|*"$ROOT_DIR/scripts/start.sh"*|*"WorkingDirectory=${ROOT_DIR}"*)
      return 0
      ;;
  esac
  return 1
}

terminate_pids() {
  local pids=("$@")
  [ "${#pids[@]}" -gt 0 ] || return 0
  kill "${pids[@]}" 2>/dev/null || true
  sleep 2
  local pid
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

resolve_web_port() {
  local start="$1"
  local port
  local pid
  for ((port = start; port < start + 50; port++)); do
    local pids=()
    while IFS= read -r pid; do
      [ -n "$pid" ] || continue
      pids+=("$pid")
    done < <(port_pids "$port")

    if [ "${#pids[@]}" -eq 0 ]; then
      echo "$port"
      return 0
    fi

    local all_project=1
    for pid in "${pids[@]}"; do
      if ! is_project_pid "$pid"; then
        all_project=0
        break
      fi
    done

    if [ "$all_project" -eq 1 ]; then
      echo "端口 ${port} 被本项目进程占用，先停止后复用: ${pids[*]}" >&2
      terminate_pids "${pids[@]}"
      echo "$port"
      return 0
    fi

    echo "端口 ${port} 被其他应用占用，顺延检查下一个端口。" >&2
  done
  echo "No available port from ${start} to $((start + 49))" >&2
  return 1
}

PORT="$(resolve_web_port "$REQUESTED_PORT")"

echo "系统: ${PLATFORM}"
echo "监听: http://127.0.0.1:${PORT} 以及 http://0.0.0.0:${PORT}"
echo "回测系统: FastAPI Web/API"
echo "模拟交易系统: Paper runner，每 ${PAPER_POLL_SECONDS} 秒轮询已收盘 K 线"
echo "版本: ${APP_VERSION}"
echo "停止: kill \$(cat runtime/start.pid) 或 systemctl stop weekly-web"

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

APP_VERSION="$APP_VERSION" START_MODE="$START_MODE" PAPER_POLL_SECONDS="$PAPER_POLL_SECONDS" "$VENV_PYTHON" -m app.paper_runner >> runtime/logs/paper_runner.log 2>&1 &
PAPER_PID="$!"
echo "模拟交易系统已启动: pid=${PAPER_PID}, log=runtime/logs/paper_runner.log"

APP_VERSION="$APP_VERSION" START_MODE="$START_MODE" "$VENV_PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" >> runtime/logs/web.log 2>&1 &
WEB_PID="$!"
echo "Web/回测系统已启动: pid=${WEB_PID}, log=runtime/logs/web.log"

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
