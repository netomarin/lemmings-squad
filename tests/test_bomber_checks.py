import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "plugin"
    / "skills"
    / "lemmings-orchestrate"
    / "scripts"
)
BOMBER_SCRIPT = SCRIPTS_DIR / "run_bomber_checks.py"
STATE_SCRIPT = SCRIPTS_DIR / "state_manager.py"


class TestBomberAndAutoHealing(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.run_id = "20260930-bomber-test"
        self.run_dir = self.workspace / ".lemmings" / "runs" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _write_verified_backlog(self, unit_test_cmd: str = "python3 -c 'exit(0)'") -> None:
        backlog = {
            "run_id": self.run_id,
            "step": "03-backlog",
            "spec_path": "docs/specs/sample.md",
            "plan_path": f".lemmings/runs/{self.run_id}/02-implementation-plan.md",
            "status": "ALL_VERIFIED",
            "config": {
                "max_task_retries": 3,
                "max_qa_retries": 2,
                "qa_commands": {
                    "install": None,
                    "lint": "python3 -c 'print(\"lint ok\")'",
                    "typecheck": None,
                    "unit_test": unit_test_cmd,
                    "integration_test": None,
                    "security_scan": None,
                    "build": None,
                },
                "deploy": {"enabled": False, "environment": "none"},
            },
            "waves": [
                {
                    "wave_number": 1,
                    "title": "Wave 1",
                    "isolation_mode": "inherit",
                    "status": "VERIFIED",
                    "tasks": [
                        {
                            "id": "TASK-01",
                            "title": "Auth Service",
                            "description": "Implement auth service",
                            "depends_on": [],
                            "target_files": ["src/auth.py"],
                            "test_files": [],
                            "acceptance_criteria": ["Secure auth"],
                            "verification_cmd": "python3 -c 'exit(0)'",
                            "status": "VERIFIED",
                            "attempts": 1,
                        }
                    ],
                }
            ],
        }
        (self.run_dir / "03-backlog.json").write_text(json.dumps(backlog, indent=2), encoding="utf-8")

    def test_bomber_detects_hardcoded_secret_and_triggers_hotfix_wave(self) -> None:
        self._write_verified_backlog()
        src = self.workspace / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "auth.py").write_text(
            'API_KEY = "sk_live_9876543210abcdef123456"\n',
            encoding="utf-8",
        )

        res = subprocess.run(
            [
                sys.executable,
                str(BOMBER_SCRIPT),
                "--workspace",
                str(self.workspace),
                "--run-dir",
                str(self.run_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        report = json.loads(res.stdout)
        self.assertFalse(report["overall_passed"])
        self.assertEqual(report["blocking_security_findings_count"], 1)
        self.assertEqual(report["security_findings"][0]["rule_id"], "CWE-798_HARDCODED_SECRET")

        # Record QA failure -> must request CREATE_HOTFIX_WAVE
        rec = subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "record-qa",
                "--run-dir",
                str(self.run_dir),
                "--verdict",
                "FAILED",
                "--summary",
                "Hardcoded secret in src/auth.py",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(rec.returncode, 0, rec.stderr)
        rec_out = json.loads(rec.stdout)
        self.assertEqual(rec_out["action"], "CREATE_HOTFIX_WAVE")

        # Add Hotfix Wave
        hf_task = [
            {
                "id": "TASK-HF1",
                "title": "Remove hardcoded API_KEY from src/auth.py",
                "description": "Read API_KEY from os.environ instead of hardcoding",
                "target_files": ["src/auth.py"],
                "acceptance_criteria": ["No hardcoded secret in src/auth.py"],
                "verification_cmd": "python3 -c 'exit(0)'",
            }
        ]
        hf_res = subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "add-hotfix-wave",
                "--run-dir",
                str(self.run_dir),
                "--tasks-json",
                json.dumps(hf_task),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(hf_res.returncode, 0, hf_res.stderr)
        hf_out = json.loads(hf_res.stdout)
        self.assertEqual(hf_out["wave_number"], 2)
        self.assertEqual(hf_out["task_ids"], ["TASK-HF1"])


if __name__ == "__main__":
    unittest.main()
