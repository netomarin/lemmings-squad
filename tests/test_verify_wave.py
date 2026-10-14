import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

VERIFY_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "plugin"
    / "skills"
    / "lemmings-orchestrate"
    / "scripts"
    / "verify_wave.py"
)


class TestVerifyWave(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.run_id = "20260930-inspector-test"
        self.run_dir = self.workspace / ".lemmings" / "runs" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _write_backlog(self) -> None:
        backlog = {
            "run_id": self.run_id,
            "step": "03-backlog",
            "spec_path": "docs/specs/sample.md",
            "plan_path": f".lemmings/runs/{self.run_id}/02-implementation-plan.md",
            "status": "IN_PROGRESS",
            "config": {
                "max_task_retries": 3,
                "max_qa_retries": 2,
                "qa_commands": {},
                "deploy": {"enabled": False, "environment": "none"},
            },
            "waves": [
                {
                    "wave_number": 1,
                    "title": "Wave 1",
                    "isolation_mode": "inherit",
                    "status": "DEV_DONE",
                    "tasks": [
                        {
                            "id": "TASK-01",
                            "title": "Clean Module",
                            "description": "Implement clean module",
                            "depends_on": [],
                            "target_files": ["src/clean.py"],
                            "test_files": [],
                            "acceptance_criteria": ["Returns 10"],
                            "verification_cmd": "python3 -c 'import sys; sys.path.insert(0, \"src\"); import clean; assert clean.val() == 10'",
                            "status": "DEV_DONE",
                            "attempts": 0,
                            "builder_report_file": f".lemmings/runs/{self.run_id}/04-wave-1-builder-TASK-01.md",
                        },
                        {
                            "id": "TASK-02",
                            "title": "Stubbed Module",
                            "description": "Module with TODO",
                            "depends_on": [],
                            "target_files": ["src/stubbed.py"],
                            "test_files": [],
                            "acceptance_criteria": ["No TODOs"],
                            "verification_cmd": "python3 -c 'exit(0)'",
                            "status": "DEV_DONE",
                            "attempts": 0,
                            "builder_report_file": f".lemmings/runs/{self.run_id}/04-wave-1-builder-TASK-02.md",
                        },
                    ],
                }
            ],
        }
        (self.run_dir / "03-backlog.json").write_text(json.dumps(backlog, indent=2), encoding="utf-8")

    def test_verify_wave_detects_todo_antipattern_and_runs_tests(self) -> None:
        self._write_backlog()
        src_dir = self.workspace / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "clean.py").write_text("def val():\n    return 10\n", encoding="utf-8")
        (src_dir / "stubbed.py").write_text("def incomplete():\n    # TODO: finish this later\n    return None\n", encoding="utf-8")

        res = subprocess.run(
            [
                sys.executable,
                str(VERIFY_SCRIPT),
                "--workspace",
                str(self.workspace),
                "--run-dir",
                str(self.run_dir),
                "--wave",
                "1",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        report = json.loads(res.stdout)
        self.assertFalse(report["all_deterministic_checks_passed"])

        t1 = report["tasks"][0]
        self.assertTrue(t1["deterministic_checks_passed"])
        self.assertTrue(t1["verification_execution"]["passed"])

        t2 = report["tasks"][1]
        self.assertFalse(t2["deterministic_checks_passed"])
        self.assertIn("src/stubbed.py", t2["antipattern_findings"])
        self.assertEqual(t2["antipattern_findings"]["src/stubbed.py"][0]["rule"], "TODO_MARKER")


if __name__ == "__main__":
    unittest.main()
