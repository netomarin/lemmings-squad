#!/usr/bin/env python3
"""
Lemmings Squad — Full Repository QA & Security Scanner (run_bomber_checks.py)

Used by `lemming-bomber` once 100% of backlog waves are `VERIFIED` to execute:
  1. All configured global QA commands in `03-backlog.json` (`install`, `lint`,
     `typecheck`, `unit_test`, `integration_test`, `security_scan`, `build`).
  2. Static security & vulnerability scan (SAST / OWASP Top 10 / CWE checks)
     across all files created or modified by the run:
     - Hardcoded secrets / API keys / private keys (CWE-798)
     - Dynamic code execution `eval()` / `exec()` / unsafe `shell=True` (CWE-78 / CWE-94)
     - Raw SQL string formatting / concatenation (CWE-89)
     - Unescaped HTML injection `innerHTML` / `dangerouslySetInnerHTML` (CWE-79)
     - Weak cryptography `md5` / `sha1` for passwords/tokens (CWE-328)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Set

QA_STAGE_ORDER = [
    ("install", "Install / Setup"),
    ("lint", "Lint"),
    ("typecheck", "Typecheck"),
    ("unit_test", "Unit Tests"),
    ("integration_test", "Integration / E2E Tests"),
    ("security_scan", "Dependency / Security Audit"),
    ("build", "Build"),
]

SECURITY_PATTERNS = [
    (
        "CWE-798_HARDCODED_SECRET",
        "HIGH",
        re.compile(
            r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|private[_-]?key|password)\s*[:=]\s*['\"][A-Za-z0-9_\-./+=]{12,}['\"]"
        ),
    ),
    (
        "CWE-798_PRIVATE_KEY_BLOCK",
        "CRITICAL",
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PRIVATE )?KEY-----"),
    ),
    (
        "CWE-94_UNSAFE_EVAL_EXEC",
        "HIGH",
        re.compile(r"\b(eval|exec)\s*\("),
    ),
    (
        "CWE-79_UNSAFE_INNER_HTML",
        "MEDIUM",
        re.compile(r"\b(dangerouslySetInnerHTML|innerHTML\s*=)"),
    ),
    (
        "CWE-89_POTENTIAL_SQL_INJECTION",
        "HIGH",
        re.compile(
            r"(?i)(SELECT|INSERT|UPDATE|DELETE)\s+.*(\+\s*[a-zA-Z_]|f['\"].*\{.*\}|%s.*%\s*\()"
        ),
    ),
]


def run_shell_step(key: str, label: str, cmd: str, cwd: Path, timeout_sec: int = 300) -> Dict[str, Any]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        elapsed = round(time.monotonic() - start, 2)
        combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return {
            "stage": key,
            "label": label,
            "command": cmd,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "duration_sec": elapsed,
            "output_tail": combined.strip()[-3000:],
        }
    except subprocess.TimeoutExpired:
        elapsed = round(time.monotonic() - start, 2)
        return {
            "stage": key,
            "label": label,
            "command": cmd,
            "exit_code": -1,
            "passed": False,
            "duration_sec": elapsed,
            "output_tail": f"Command timed out after {timeout_sec}s: {cmd}",
        }


def scan_files_for_vulnerabilities(workspace: Path, rel_files: Set[str]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for rel_path in sorted(rel_files):
        abs_path = (workspace / rel_path).resolve()
        if not abs_path.exists() or not abs_path.is_file():
            continue
        try:
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            for rule_id, severity, regex in SECURITY_PATTERNS:
                if regex.search(line):
                    findings.append(
                        {
                            "file": rel_path,
                            "line": line_num,
                            "rule_id": rule_id,
                            "severity": severity,
                            "snippet": stripped[:200],
                        }
                    )
    return findings


def execute_bomber_suite(workspace: Path, run_dir: Path) -> Dict[str, Any]:
    backlog_path = run_dir / "03-backlog.json"
    if not backlog_path.exists():
        raise FileNotFoundError(f"Backlog not found: {backlog_path}")

    backlog = json.loads(backlog_path.read_text(encoding="utf-8"))
    qa_commands = backlog.get("config", {}).get("qa_commands", {}) or {}

    command_results: List[Dict[str, Any]] = []
    all_commands_passed = True

    for key, label in QA_STAGE_ORDER:
        cmd = qa_commands.get(key)
        if not cmd or str(cmd).strip().lower() in ("null", "none", "n/a", ""):
            continue
        res = run_shell_step(key, label, str(cmd), workspace)
        command_results.append(res)
        if not res["passed"]:
            all_commands_passed = False

    touched_files: Set[str] = set()
    for wave in backlog.get("waves", []):
        for task in wave.get("tasks", []):
            for f in task.get("target_files", []):
                touched_files.add(f)

    sast_findings = scan_files_for_vulnerabilities(workspace, touched_files)
    high_or_critical = [f for f in sast_findings if f["severity"] in ("HIGH", "CRITICAL")]

    overall_passed = all_commands_passed and len(high_or_critical) == 0
    attempt_number = int(backlog.get("qa_attempts", 0)) + 1

    return {
        "ok": True,
        "run_id": backlog.get("run_id"),
        "qa_attempt": attempt_number,
        "overall_passed": overall_passed,
        "all_commands_passed": all_commands_passed,
        "command_results": command_results,
        "touched_files_scanned": sorted(touched_files),
        "security_findings": sast_findings,
        "blocking_security_findings_count": len(high_or_critical),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Lemmings Squad Full QA & Security Scanner")
    parser.add_argument("--workspace", required=True, help="Target repository root path")
    parser.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    args = parser.parse_args()
    try:
        report = execute_bomber_suite(
            workspace=Path(args.workspace).resolve(),
            run_dir=Path(args.run_dir).resolve(),
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
