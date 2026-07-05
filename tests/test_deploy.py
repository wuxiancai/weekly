from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class DeployScriptTests(unittest.TestCase):
    def test_one_click_deploy_installs_single_start_sh_systemd_service(self) -> None:
        script = (ROOT / "scripts" / "deploy_one_click.sh").read_text()

        self.assertIn("weekly-web", script)
        self.assertIn("0.0.0.0", script)
        self.assertIn('PORT="${PORT:-8001}"', script)
        self.assertIn("python3-venv", script)
        self.assertIn('"$ROOT_DIR/start.sh"', script)
        self.assertIn('WEB_SERVICE="$WEB_SERVICE"', script)
        self.assertIn("LEGACY_PAPER_SERVICE", script)
        self.assertIn("检测到 macOS", script)
        self.assertIn('OS_NAME="$(uname -s)"', script)
        self.assertNotIn("scripts/start.sh", script)
        self.assertNotIn("ExecStart=/usr/bin/env bash ${ROOT_DIR}/scripts/run_paper.sh", script)
        self.assertNotIn('systemctl enable "${WEB_SERVICE}.service" "${PAPER_SERVICE}.service"', script)

    def test_scripts_start_sh_is_removed_to_keep_single_start_entrypoint(self) -> None:
        self.assertFalse((ROOT / "scripts" / "start.sh").exists())

    def test_root_start_script_launches_web_and_paper_and_stops_existing_processes(self) -> None:
        script = (ROOT / "start.sh").read_text()

        self.assertIn("stop_existing_project_processes", script)
        self.assertIn("pgrep -f", script)
        self.assertIn('"$ROOT_DIR/start.sh"', script)
        self.assertIn('"$ROOT_DIR/scripts/start.sh"', script)
        self.assertIn("app.paper_runner", script)
        self.assertIn("uvicorn app.main:app", script)
        self.assertIn("PAPER_POLL_SECONDS", script)
        self.assertIn('REQUESTED_PORT="${PORT:-8001}"', script)
        self.assertIn("resolve_web_port", script)
        self.assertIn("端口 ${port} 被本项目进程占用", script)
        self.assertIn("端口 ${port} 被其他应用占用", script)
        self.assertIn('--foreground', script)
        self.assertIn('START_MODE="${START_MODE:-daemon}"', script)
        self.assertIn("install_or_restart_systemd_service", script)
        self.assertIn("LEGACY_PAPER_SERVICE", script)
        self.assertIn('sudo systemctl stop "${WEB_SERVICE}.service"', script)
        self.assertIn('stop_existing_project_processes', script)
        self.assertIn("ExecStart=/usr/bin/env bash ${ROOT_DIR}/start.sh --foreground", script)
        self.assertIn('sudo systemctl restart "${WEB_SERVICE}.service"', script)
        self.assertIn("start.sh 已交给 systemd 托管", script)
        self.assertIn('nohup "$ROOT_DIR/start.sh" --foreground', script)
        self.assertIn('[ "${#PASSTHROUGH_ARGS[@]}" -gt 0 ]', script)
        self.assertIn("runtime/start.pid", script)
        self.assertIn("runtime/logs/start.log", script)
        self.assertIn("runtime/logs/web.log", script)
        self.assertNotIn("Ctrl+C", script)
        self.assertNotIn("Press CTRL+C", script)
        self.assertIn("start.sh 已在后台启动", script)

    def test_runtime_diagnosis_script_checks_ports_and_html_markers(self) -> None:
        script = (ROOT / "scripts" / "diagnose_runtime.sh").read_text()

        self.assertIn("8001 8002", script)
        self.assertIn("/api/system/runtime", script)
        self.assertIn("/paper", script)
        self.assertIn("OLD hardcoded title", script)
        self.assertIn("strategyIntervals", script)

    def test_legacy_systemd_installer_defaults_to_port_8001(self) -> None:
        script = (ROOT / "scripts" / "install_systemd_service.sh").read_text()

        self.assertIn('PORT="${PORT:-8001}"', script)

    def test_paper_runner_script_uses_project_venv(self) -> None:
        script = (ROOT / "scripts" / "run_paper.sh").read_text()

        self.assertIn(".venv", script)
        self.assertIn("app.paper_runner", script)

    def test_paper_runner_supports_one_hour_interval(self) -> None:
        runner = (ROOT / "app" / "paper_runner.py").read_text()

        self.assertIn('"1h": 60 * 60 * 1000', runner)

    def test_paper_runner_warmup_uses_at_least_sixty_candles(self) -> None:
        from app.paper_runner import _warmup_candles_for
        from app.strategy import StrategyParams

        self.assertGreaterEqual(_warmup_candles_for(StrategyParams(ema_period=15, ma_period=50)), 60)
