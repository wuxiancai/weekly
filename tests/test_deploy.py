from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class DeployScriptTests(unittest.TestCase):
    def test_one_click_deploy_installs_web_and_paper_systemd_services(self) -> None:
        script = (ROOT / "scripts" / "deploy_one_click.sh").read_text()

        self.assertIn("weekly-web", script)
        self.assertIn("weekly-paper", script)
        self.assertIn("0.0.0.0", script)
        self.assertIn("python3-venv", script)
        self.assertIn("systemctl enable", script)
        self.assertIn("run_paper.sh", script)

    def test_paper_runner_script_uses_project_venv(self) -> None:
        script = (ROOT / "scripts" / "run_paper.sh").read_text()

        self.assertIn(".venv", script)
        self.assertIn("app.paper_runner", script)

    def test_paper_runner_supports_one_hour_interval(self) -> None:
        runner = (ROOT / "app" / "paper_runner.py").read_text()

        self.assertIn('"1h": 60 * 60 * 1000', runner)
