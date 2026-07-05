#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

WEB_SERVICE="${WEB_SERVICE:-weekly-web}"
LEGACY_PAPER_SERVICE="${LEGACY_PAPER_SERVICE:-weekly-paper}"

echo "准备停止本项目服务: $ROOT_DIR"

has_systemctl() {
  command -v systemctl >/dev/null 2>&1
}

run_systemctl_stop() {
  local service="$1"
  if ! has_systemctl; then
    return 0
  fi

  if systemctl list-unit-files "${service}.service" >/dev/null 2>&1 || \
     systemctl list-units --all "${service}.service" >/dev/null 2>&1; then
    echo "停止 systemd 服务: ${service}.service"
    if command -v sudo >/dev/null 2>&1; then
      sudo systemctl stop "${service}.service" 2>/dev/null || true
    else
      systemctl stop "${service}.service" 2>/dev/null || true
    fi
  fi
}

append_unique_pid() {
  local new_pid="$1"
  local existing
  [ -n "$new_pid" ] || return 0
  [ "$new_pid" != "$$" ] || return 0
  [ "$new_pid" != "${PPID:-}" ] || return 0
  for existing in "${PIDS_TO_STOP[@]}"; do
    [ "$existing" != "$new_pid" ] || return 0
  done
  PIDS_TO_STOP+=("$new_pid")
}

collect_pid_file() {
  local file="$1"
  local pid
  [ -f "$file" ] || return 0
  pid="$(tr -d '[:space:]' < "$file" 2>/dev/null || true)"
  case "$pid" in
    ''|*[!0-9]*)
      return 0
      ;;
  esac
  if kill -0 "$pid" 2>/dev/null; then
    append_unique_pid "$pid"
  fi
}

collect_project_pattern() {
  local pattern="$1"
  local pid
  while IFS= read -r pid; do
    append_unique_pid "$pid"
  done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

stop_pids() {
  local pid
  [ "${#PIDS_TO_STOP[@]}" -gt 0 ] || return 0

  echo "停止本项目进程: ${PIDS_TO_STOP[*]}"
  kill "${PIDS_TO_STOP[@]}" 2>/dev/null || true
  sleep 2
  for pid in "${PIDS_TO_STOP[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "进程仍在运行，强制停止: $pid"
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}

PIDS_TO_STOP=()

run_systemctl_stop "$WEB_SERVICE"
run_systemctl_stop "$LEGACY_PAPER_SERVICE"

collect_pid_file "$ROOT_DIR/runtime/start.pid"

collect_project_pattern "$ROOT_DIR/start.sh"
collect_project_pattern "$ROOT_DIR/scripts/start.sh"
collect_project_pattern "$ROOT_DIR/scripts/run_paper.sh"
collect_project_pattern "$ROOT_DIR/scripts/collect_websocket.sh"
collect_project_pattern "$ROOT_DIR/.venv/bin/python.*uvicorn app.main:app"
collect_project_pattern "$ROOT_DIR/.venv/bin/python3.*uvicorn app.main:app"
collect_project_pattern "$ROOT_DIR/.venv/bin/python.*app.paper_runner"
collect_project_pattern "$ROOT_DIR/.venv/bin/python3.*app.paper_runner"
collect_project_pattern "$ROOT_DIR/.venv/bin/python.*app.websocket_collector"
collect_project_pattern "$ROOT_DIR/.venv/bin/python3.*app.websocket_collector"

stop_pids

rm -f "$ROOT_DIR/runtime/start.pid"

echo "已停止本项目 Web、Paper runner、WebSocket collector 和后台启动进程。"
