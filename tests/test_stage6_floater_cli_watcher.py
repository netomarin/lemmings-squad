import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_MANAGER = REPO_ROOT / "plugin" / "skills" / "lemmings-orchestrate" / "scripts" / "state_manager.py"
CLI_BIN = REPO_ROOT / "bin" / "lemmings"
WATCHER_SCRIPT = REPO_ROOT / "sidecar" / "lemmings_watcher.py"


def run_cmd(cmd: list[str]) -> tuple[int, dict]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout.strip() or proc.stderr.strip()
    return proc.returncode, json.loads(out) if out else {}


class TestStage6FloaterCliAndWatcher(unittest.TestCase):
    def test_record_deploy_and_finalize_run_generates_08_final_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            run_id = "20260930-stage6-e2e"
            run_dir = ws / ".lemmings" / "runs" / run_id

            code, _ = run_cmd(
                [
                    sys.executable,
                    str(STATE_MANAGER),
                    "init-run",
                    "--workspace",
                    str(ws),
                    "--run-id",
                    run_id,
                    "--spec",
                    "docs/spec.md",
                    "--deploy-target",
                    "staging",
                ]
            )
            self.assertEqual(code, 0)

            backlog = {
                "run_id": run_id,
                "step": "03-backlog",
                "spec_path": "docs/spec.md",
                "plan_path": f".lemmings/runs/{run_id}/02-implementation-plan.md",
                "status": "QA_PASSED",
                "qa_attempts": 1,
                "qa_history": [
                    {
                        "attempt": 1,
                        "verdict": "PASSED",
                        "report_file": f".lemmings/runs/{run_id}/06-bomber-qa-security-attempt-1.md",
                        "summary": "All unit tests and SAST checks passed.",
                        "timestamp": "2026-09-30T18:00:00Z",
                    }
                ],
                "waves": [
                    {
                        "wave_number": 1,
                        "title": "Wave 1",
                        "tasks": [
                            {
                                "id": "TASK-01",
                                "title": "Core service",
                                "description": "Implement core service",
                                "target_files": ["src/service.py"],
                                "test_files": ["tests/test_service.py"],
                                "acceptance_criteria": ["Works"],
                                "verification_cmd": "python3 -m unittest",
                                "status": "VERIFIED",
                                "attempts": 1,
                                "builder_report_file": f".lemmings/runs/{run_id}/04-wave-1-builder-TASK-01.md",
                            }
                        ],
                    }
                ],
            }
            (run_dir / "03-backlog.json").write_text(json.dumps(backlog), encoding="utf-8")

            # Record Floater deploy
            code, dep_res = run_cmd(
                [
                    sys.executable,
                    str(STATE_MANAGER),
                    "record-deploy",
                    "--run-dir",
                    str(run_dir),
                    "--env",
                    "staging",
                    "--verdict",
                    "DEPLOYED",
                    "--report",
                    f".lemmings/runs/{run_id}/07-floater-deploy-staging.md",
                    "--summary",
                    "Deployed to staging and passed smoke test.",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(dep_res["action"], "FINALIZE_RUN")

            # Finalize run -> generates 08-final-summary.md
            code, fin_res = run_cmd(
                [
                    sys.executable,
                    str(STATE_MANAGER),
                    "finalize-run",
                    "--run-dir",
                    str(run_dir),
                    "--summary",
                    "Entrega completa validada até homologação.",
                    "--overwrite-summary",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(fin_res["status"], "COMPLETED")
            self.assertEqual(fin_res["current_step"], "08_COMPLETED")

            summary_file = run_dir / "08-final-summary.md"
            self.assertTrue(summary_file.exists())
            summary_content = summary_file.read_text(encoding="utf-8")
            self.assertIn("TASK-01", summary_content)
            self.assertIn("07-floater-deploy-staging.md", summary_content)

    def test_cli_init_status_approve_and_watcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "package.json").write_text(
                json.dumps(
                    {
                        "name": "demo-webapp",
                        "scripts": {
                            "lint": "eslint .",
                            "test": "vitest run",
                            "build": "vite build",
                            "deploy:staging": "firebase hosting:channel:deploy staging",
                        },
                    }
                ),
                encoding="utf-8",
            )

            # 1. Test CLI init-config
            code, init_res = run_cmd(
                [sys.executable, str(CLI_BIN), "init-config", "--workspace", str(ws), "--with-templates"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(init_res["project_name"], "demo-webapp")
            self.assertTrue((ws / ".lemmings" / "config.yaml").exists())
            self.assertTrue((ws / ".lemmings" / "config.json").exists())
            self.assertTrue((ws / ".lemmings" / "templates" / "08-final-summary.template.md").exists())

            # 2. Initialize a run and set it to 02_WAITING_PLAN_APPROVAL
            run_id = "20260930-watcher-test"
            run_dir = ws / ".lemmings" / "runs" / run_id
            run_cmd(
                [
                    sys.executable,
                    str(STATE_MANAGER),
                    "init-run",
                    "--workspace",
                    str(ws),
                    "--run-id",
                    run_id,
                    "--spec",
                    "docs/spec.md",
                ]
            )
            status_path = run_dir / "00-run-status.json"
            st = json.loads(status_path.read_text(encoding="utf-8"))
            st["current_step"] = "02_WAITING_PLAN_APPROVAL"
            st["status"] = "WAITING_APPROVAL"
            status_path.write_text(json.dumps(st, indent=2), encoding="utf-8")

            plan_path = run_dir / "02-implementation-plan.md"
            plan_path.write_text("# Plano\n- **Status de Aprovação:** `PENDING`\n", encoding="utf-8")

            # 3. Test CLI status --json
            code, stat_res = run_cmd([sys.executable, str(CLI_BIN), "status", "--workspace", str(ws), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(stat_res["current_step"], "02_WAITING_PLAN_APPROVAL")

            # 4. Test CLI approve --dry-run
            code, app_res = run_cmd([sys.executable, str(CLI_BIN), "approve", "--workspace", str(ws), "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(app_res["current_step"], "02_PLAN_APPROVED")
            self.assertIn("APPROVED", plan_path.read_text(encoding="utf-8"))

            # 5. Test Sidecar Watcher with an inbox spec and plan approval transition
            st["current_step"] = "02_WAITING_PLAN_APPROVAL"
            status_path.write_text(json.dumps(st, indent=2), encoding="utf-8")
            (ws / ".lemmings" / "inbox" / "new-feature.md").write_text("# Nova Feature\n", encoding="utf-8")

            code, watch_res = run_cmd(
                [
                    sys.executable,
                    str(WATCHER_SCRIPT),
                    "--workspace",
                    str(ws),
                    "--once",
                    "--dry-run",
                ]
            )
            self.assertEqual(code, 0)
            event_types = [e["type"] for e in watch_res["events"]]
            self.assertIn("INBOX_SPEC_TRIGGERED", event_types)
            self.assertIn("PLAN_APPROVAL_TRIGGERED", event_types)

    def test_lemming_basher_cicd_generation_and_incremental_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "package.json").write_text(
                json.dumps(
                    {
                        "name": "basher-service",
                        "scripts": {
                            "lint": "eslint .",
                            "test:unit": "vitest run",
                            "test:integration": "vitest run --config vitest.int.ts",
                            "build": "tsc -b",
                        },
                    }
                ),
                encoding="utf-8",
            )
            # Pre-populate a custom team workflow to verify incremental update preservation
            wf_dir = ws / ".github" / "workflows"
            wf_dir.mkdir(parents=True, exist_ok=True)
            (wf_dir / "ci.yml").write_text(
                "name: Custom Team Workflow\non: [push]\n\njobs:\n  custom-team-job:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo 'team job'\n",
                encoding="utf-8",
            )

            code, res = run_cmd(
                [
                    sys.executable,
                    str(CLI_BIN),
                    "init-config",
                    "--workspace",
                    str(ws),
                    "--with-ci",
                    "--with-cd",
                    "--deploy-staging-cmd",
                    "npm run deploy:staging",
                    "--smoke-staging-cmd",
                    "curl -sf https://staging.basher.internal/health",
                    "--deploy-prod-cmd",
                    "npm run deploy:prod",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(res["ci_provider"], "github-actions")
            self.assertEqual(res["cicd_report"], ".lemmings/cicd-pipeline-report.md")
            self.assertTrue(res["git_readiness"]["git_initialized"])
            self.assertTrue(res["git_readiness"]["git_auto_initialized"])
            self.assertFalse(res["git_readiness"]["has_remote"])
            self.assertTrue(res["git_readiness"]["local_hooks_activated"])
            self.assertTrue((ws / ".githooks" / "pre-commit").exists())
            self.assertTrue((ws / ".githooks" / "pre-push").exists())

            # Verify incremental preservation of custom-team-job + addition of fast-ci-check & main-bomber-gate
            ci_text = (wf_dir / "ci.yml").read_text(encoding="utf-8")
            self.assertIn("custom-team-job:", ci_text)
            self.assertIn("fast-ci-check:", ci_text)
            self.assertIn("main-bomber-gate:", ci_text)

            # Verify CD workflow and smoke test
            cd_text = (wf_dir / "cd.yml").read_text(encoding="utf-8")
            self.assertIn("deploy-staging:", cd_text)
            self.assertIn("deploy-production:", cd_text)
            self.assertIn("curl -sf https://staging.basher.internal/health", cd_text)

            # Verify synchronization with .lemmings/config.json & .lemmings/cicd-pipeline-report.md
            cfg_json = json.loads((ws / ".lemmings" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(
                cfg_json["deploy"]["environments"]["staging"]["smoke_test_cmd"],
                "curl -sf https://staging.basher.internal/health",
            )
            report_text = (ws / ".lemmings" / "cicd-pipeline-report.md").read_text(encoding="utf-8")
            self.assertIn("lemming-basher", report_text)
            self.assertIn("LEMMINGS_STAGING_DEPLOY_TOKEN", report_text)
            self.assertIn("gh auth login", report_text)

    def test_deploy_signals_env_scanner_and_preflight_check(self) -> None:
        preflight_script = (
            REPO_ROOT / "plugin" / "skills" / "lemmings-orchestrate" / "scripts" / "check_deploy_readiness.py"
        )
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            # 1. Pure library without web framework or infra -> should_suggest_cd == False
            (ws / "package.json").write_text(
                json.dumps({"name": "pure-utils-lib", "scripts": {"test": "vitest"}}),
                encoding="utf-8",
            )
            code, lib_res = run_cmd([sys.executable, str(CLI_BIN), "init-config", "--workspace", str(ws)])
            self.assertEqual(code, 0)
            self.assertFalse(lib_res["deploy_signals"]["should_suggest_cd"])
            self.assertEqual(lib_res["deploy_signals"]["confidence"], "none")

            # 2. Add Express + code referencing GEMINI_API_KEY and DATABASE_URL -> should_suggest_cd == True
            (ws / "package.json").write_text(
                json.dumps(
                    {
                        "name": "ai-api-service",
                        "dependencies": {"express": "^4.19.0"},
                        "scripts": {"start": "node src/server.js", "test": "vitest"},
                    }
                ),
                encoding="utf-8",
            )
            src_dir = ws / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "server.js").write_text(
                "const key = process.env.GEMINI_API_KEY;\nconst db = process.env.DATABASE_URL;\nconst appName = process.env.PUBLIC_APP_NAME;\n",
                encoding="utf-8",
            )

            code, cd_res = run_cmd(
                [
                    sys.executable,
                    str(CLI_BIN),
                    "init-config",
                    "--workspace",
                    str(ws),
                    "--force",
                    "--with-ci",
                    "--with-cd",
                    "--cloud-target",
                    "cloud-run",
                    "--scaffold-infra",
                    "--deploy-staging-cmd",
                    "npm run start",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(cd_res["deploy_signals"]["should_suggest_cd"])
            self.assertIn("GEMINI_API_KEY", cd_res["deploy_signals"]["detected_secret_vars"])
            self.assertIn("DATABASE_URL", cd_res["deploy_signals"]["detected_secret_vars"])
            self.assertIn("PUBLIC_APP_NAME", cd_res["deploy_signals"]["detected_config_vars"])

            # Verify Dockerfile and .env.example were scaffolded
            self.assertTrue((ws / "Dockerfile").exists())
            self.assertTrue((ws / ".env.example").exists())
            self.assertIn("GEMINI_API_KEY=", (ws / ".env.example").read_text(encoding="utf-8"))

            # Verify cd.yml contains Google Cloud auth + discovered secrets
            cd_yml = (ws / ".github" / "workflows" / "cd.yml").read_text(encoding="utf-8")
            self.assertIn("google-github-actions/auth@v2", cd_yml)
            self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", cd_yml)

            # 3. Run check_deploy_readiness.py before setting .env.staging -> ready == False (missing secrets)
            code, pf_missing = run_cmd(
                [sys.executable, str(preflight_script), "--workspace", str(ws), "--env", "staging"]
            )
            self.assertEqual(code, 0)
            self.assertFalse(pf_missing["ready"])
            self.assertIn("GEMINI_API_KEY", pf_missing["missing_secrets"])

            # 4. Provide .env.staging with required secrets -> ready == True (for custom target)
            cfg_file = ws / ".lemmings" / "config.json"
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
            cfg_data["deploy"]["cloud_target"] = "custom"
            cfg_file.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
            (ws / ".env.staging").write_text(
                "GEMINI_API_KEY=test-key\nDATABASE_URL=postgres://localhost/db\n",
                encoding="utf-8",
            )
            code, pf_ready = run_cmd(
                [sys.executable, str(preflight_script), "--workspace", str(ws), "--env", "staging"]
            )
            self.assertEqual(code, 0)
            self.assertTrue(pf_ready["ready"])


if __name__ == "__main__":
    unittest.main()



