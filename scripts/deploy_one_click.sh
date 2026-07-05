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
OS_NAME="$(uname -s)"
PROJECT_DB_PATH="${PROJECT_DB_PATH:-$ROOT_DIR/data/trading.db}"

handle_existing_project_database() {
  if [ ! -f "$PROJECT_DB_PATH" ]; then
    return 0
  fi

  echo "检测到本项目数据库: $PROJECT_DB_PATH"

  local action="${DEPLOY_EXISTING_DB_ACTION:-}"
  if [ -z "$action" ]; then
    if [ ! -t 0 ]; then
      echo "当前不是交互式终端，默认保留数据库并继续部署。"
      return 0
    fi
    while true; do
      read -r -p "请选择：[s] 保留数据库并继续部署 / [d] 删除数据库后继续部署: " action
      case "$action" in
        s|S|skip|SKIP|保留|跳过|keep|KEEP)
          action="skip"
          break
          ;;
        d|D|delete|DELETE|删除|remove|REMOVE)
          action="delete"
          break
          ;;
        *)
          echo "请输入 s 或 d。"
          ;;
      esac
    done
  fi

  case "$action" in
    skip|SKIP|s|S|保留|跳过|keep|KEEP)
      echo "保留现有数据库，继续部署。"
      ;;
    delete|DELETE|d|D|删除|remove|REMOVE)
      echo "准备删除现有数据库，先停止本项目 systemd 服务。"
      sudo systemctl stop "${WEB_SERVICE}.service" 2>/dev/null || true
      sudo systemctl stop "${LEGACY_PAPER_SERVICE}.service" 2>/dev/null || true
      rm -f "$PROJECT_DB_PATH" "$PROJECT_DB_PATH-wal" "$PROJECT_DB_PATH-shm"
      echo "已删除数据库: $PROJECT_DB_PATH"
      ;;
    *)
      echo "DEPLOY_EXISTING_DB_ACTION 只支持 skip 或 delete。"
      exit 1
      ;;
  esac
}

if ! command -v systemctl >/dev/null 2>&1; then
  if [ "$OS_NAME" = "Darwin" ]; then
    echo "检测到 macOS：跳过 Ubuntu/systemd 部署，改为本机自适应启动。"
    echo "云服务器长期部署请在 Ubuntu 上执行本脚本；本机调试请访问 start.sh 输出的地址。"
    chmod +x "$ROOT_DIR/start.sh"
    HOST="$HOST" PORT="$PORT" PAPER_POLL_SECONDS="$PAPER_POLL_SECONDS" "$ROOT_DIR/start.sh"
    exit 0
  fi
  echo "当前系统没有 systemd，无法安装长期运行服务。请在 Ubuntu 云服务器上执行。"
  exit 1
fi

if [ -f /etc/os-release ] && ! grep -qi ubuntu /etc/os-release; then
  echo "当前 Linux 不是 Ubuntu，将跳过 apt 安装，只使用现有 Python 环境继续部署。"
fi

handle_existing_project_database

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

chmod +x "$ROOT_DIR/start.sh" "$ROOT_DIR/scripts/run_paper.sh"

WEB_SERVICE="$WEB_SERVICE" \
LEGACY_PAPER_SERVICE="$LEGACY_PAPER_SERVICE" \
SERVICE_USER="$SERVICE_USER" \
HOST="$HOST" \
PORT="$PORT" \
PAPER_POLL_SECONDS="$PAPER_POLL_SECONDS" \
"$ROOT_DIR/start.sh"

echo "部署完成"
echo "Web: http://服务器IP:${PORT}"
echo "模拟交易状态页: http://服务器IP:${PORT}/paper"
echo "所有服务由 start.sh 统一启动；查看日志: sudo journalctl -u ${WEB_SERVICE} -f"
sudo systemctl --no-pager --full status "${WEB_SERVICE}.service"
