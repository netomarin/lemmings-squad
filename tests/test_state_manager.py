import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "plugin"
    / "skills"
    / "lemmings-orchestrate"
    / "scripts"
    / "state_manager.py"
)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestStateManager(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.run_id = "20260929-sample-feature"
        self.run_dir = self.workspace / ".lemmings" / "runs" / self.run_id

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _create_sample_backlog(self, collision_in_wave_1: bool = False) -> dict:
        t2_file = "src/module_a.py" if collision_in_wave_1 else "src/module_b.py"
        backlog = {
            "run_id": self.run_id,
            "step": "03-backlog",
            "spec_path": "docs/specs/sample.md",
            "plan_path": f".lemmings/runs/{self.run_id}/02-implementation-plan.md",
            "status": "READY",
            "config": {
                "max_task_retries": 3,
                "max_qa_retries": 2,
                "qa_commands": {
                    "install": None,
                    "lint": "ruff check .",
                    "typecheck": "mypy .",
                    "unit_test": "python3 -m unittest",
                    "integration_test": None,
                    "security_scan": "pip-audit",
                    "build": None,
                },
                "deploy": {
                    "enabled": False,
                    "environment": "none",
                    "command": None,
                    "smoke_test_cmd": None,
                },
            },
            "waves": [
                {
                    "wave_number": 1,
                    "title": "Wave 1 — Core Modules",
                    "isolation_mode": "inherit",
                    "status": "PENDING",
                    "tasks": [
                        {
                            "id": "TASK-01",
                            "title": "Implement Module A",
                            "description": "Create module_a.py",
                            "depends_on": [],
                            "target_files": ["src/module_a.py"],
                            "test_files": ["tests/test_module_a.py"],
                            "acceptance_criteria": ["Function foo() returns 42"],
                            "verification_cmd": "python3 -m unittest tests/test_module_a.py",
                            "status": "PENDING",
                            "attempts": 0,
                        },
                        {
                            "id": "TASK-02",
                            "title": "Implement Module B",
                            "description": "Create module_b.py",
                            "depends_on": [],
                            "target_files": [t2_file],
                            "test_files": ["tests/test_module_b.py"],
                            "acceptance_criteria": ["Function bar() returns 'ok'"],
                            "verification_cmd": "python3 -m unittest tests/test_module_b.py",
                            "status": "PENDING",
                            "attempts": 0,
                        },
                    ],
                },
                {
                    "wave_number": 2,
                    "title": "Wave 2 — Integration",
                    "isolation_mode": "inherit",
                    "status": "PENDING",
                    "tasks": [
                        {
                            "id": "TASK-03",
                            "title": "Wire Modules A and B",
                            "description": "Connect A and B in app.py",
                            "depends_on": ["TASK-01", "TASK-02"],
                            "target_files": ["src/app.py"],
                            "test_files": ["tests/test_app.py"],
                            "acceptance_criteria": ["App runs both modules"],
                            "verification_cmd": "python3 -m unittest tests/test_app.py",
                            "status": "PENDING",
                            "attempts": 0,
                        }
                    ],
                },
            ],
        }
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "03-backlog.json").write_text(json.dumps(backlog, indent=2), encoding="utf-8")
        return backlog

    def test_init_run_and_path_traversal_rejection(self) -> None:
        res = run_cli(
            "init-run",
            "--workspace",
            str(self.workspace),
            "--run-id",
            self.run_id,
            "--spec",
            "docs/specs/sample.md",
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        status_file = self.run_dir / "00-run-status.json"
        self.assertTrue(status_file.exists())

        # Path traversal in spec must fail
        bad = run_cli(
            "init-run",
            "--workspace",
            str(self.workspace),
            "--run-id",
            self.run_id,
            "--spec",
            "../outside/secret.md",
        )
        self.assertNotEqual(bad.returncode, 0)

    def test_validate_backlog_disjoint_vs_collision_and_markdown_sync(self) -> None:
        # 1. Disjoint files in Wave 1 -> isolation_mode == 'inherit'
        self._create_sample_backlog(collision_in_wave_1=False)
        res = run_cli("validate-backlog", "--run-dir", str(self.run_dir))
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual(out["waves_summary"][0]["isolation_mode"], "inherit")
        self.assertFalse(out["waves_summary"][0]["file_collision_detected"])
        self.assertTrue((self.run_dir / "03-backlog.md").exists())
        self.assertTrue((self.run_dir / "00-run-status.json").exists())

        # 2. Overlapping target_files in Wave 1 -> automatically switches to 'share'
        self._create_sample_backlog(collision_in_wave_1=True)
        res2 = run_cli("validate-backlog", "--run-dir", str(self.run_dir))
        self.assertEqual(res2.returncode, 0, res2.stderr)
        out2 = json.loads(res2.stdout)
        self.assertEqual(out2["waves_summary"][0]["isolation_mode"], "share")
        self.assertTrue(out2["waves_summary"][0]["file_collision_detected"])

    def test_next_wave_and_retry_circuit_breaker_lifecycle(self) -> None:
        self._create_sample_backlog(collision_in_wave_1=False)
        run_cli("validate-backlog", "--run-dir", str(self.run_dir))

        # Wave 1 should be ready with 2 parallel tasks
        nw = json.loads(run_cli("next-wave", "--run-dir", str(self.run_dir)).stdout)
        self.assertEqual(nw["status"], "WAVE_READY")
        self.assertEqual(nw["wave_number"], 1)
        self.assertEqual(len(nw["executable_tasks"]), 2)

        # Mark TASK-01 VERIFIED and TASK-02 FAILED_VALIDATION (Attempt 1)
        run_cli("update-task", "--run-dir", str(self.run_dir), "--task-id", "TASK-01", "--status", "VERIFIED")
        run_cli(
            "update-task",
            "--run-dir",
            str(self.run_dir),
            "--task-id",
            "TASK-02",
            "--status",
            "FAILED_VALIDATION",
            "--feedback",
            "Found TODO in module_b.py",
        )

        gate1 = json.loads(run_cli("check-wave-gate", "--run-dir", str(self.run_dir), "--wave", "1").stdout)
        self.assertEqual(gate1["gate"], "RETRY_REQUIRED")
        self.assertEqual(gate1["retry_tasks"], ["TASK-02"])

        # Fail TASK-02 two more times (total 3 attempts -> hits circuit breaker!)
        run_cli("update-task", "--run-dir", str(self.run_dir), "--task-id", "TASK-02", "--status", "FAILED_VALIDATION")
        run_cli("update-task", "--run-dir", str(self.run_dir), "--task-id", "TASK-02", "--status", "FAILED_VALIDATION")

        gate_cb = json.loads(run_cli("check-wave-gate", "--run-dir", str(self.run_dir), "--wave", "1").stdout)
        self.assertEqual(gate_cb["gate"], "CIRCUIT_BREAKER")
        self.assertEqual(gate_cb["halted_tasks"], ["TASK-02"])


if __name__ == "__main__":
    unittest.main()
