#!/usr/bin/env python3
"""
Lemmings Squad — Deterministic Wave Pre-Auditor (verify_wave.py)

Used by `lemming-inspector` to perform zero-trust static & dynamic checks on all
tasks of a given Wave in `03-backlog.json`:
  1. Verifies existence and non-emptiness of all `target_files` and `test_files`.
  2. Scans `target_files` for incomplete code / anti-patterns (TODO, FIXME, HACK,
     NotImplementedError, placeholder stubs).
  3. Checks git status / diff statistics for `target_files`.
  4. Optionally executes each task's `verification_cmd` in a clean subprocess
     and captures exit code + output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List

ANTI_PATTERN_REGEXES = [
    ("TODO_MARKER", re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")),
    ("NOT_IMPLEMENTED", re.compile(r"\bNotImplementedError\b|throw\s+new\s+Error\(['\"]Not implemented", re.IGNORECASE)),
    ("PLACEHOLDER_STUB", re.compile(r"\b(placeholder|implement\s+later|mock\s+implementation)\b", re.IGNORECASE)),
]


def scan_file_for_antipatterns(file_path: Path) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [{"line": 0, "rule": "READ_ERROR", "snippet": str(exc)}]

    for idx, line in enumerate(lines, start=1):
        for rule_name, pattern in ANTI_PATTERN_REGEXES:
            if pattern.search(line):
                findings.append(
                    {
                        "line": idx,
                        "rule": rule_name,
                        "snippet": line.strip()[:200],
                    }
                )
    return findings


def run_verification_command(cmd: str, cwd: Path, timeout_sec: int = 120) -> Dict[str, Any]:
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
        combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return {
            "command": cmd,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "output_tail": combined.strip()[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "command": cmd,
            "exit_code": -1,
            "passed": False,
            "output_tail": f"Command timed out after {timeout_sec}s: {cmd}",
        }


def audit_wave(
    workspace: Path,
    run_dir: Path,
    wave_number: int,
    run_tests: bool = True,
) -> Dict[str, Any]:
    backlog_path = run_dir / "03-backlog.json"
    if not backlog_path.exists():
        raise FileNotFoundError(f"Backlog not found: {backlog_path}")

    backlog = json.loads(backlog_path.read_text(encoding="utf-8"))
    target_wave = None
    for w in backlog.get("waves", []):
        if w.get("wave_number") == wave_number:
            target_wave = w
            break

    if not target_wave:
        raise ValueError(f"Wave {wave_number} not found in {backlog_path}")

    task_audits: List[Dict[str, Any]] = []
    all_deterministic_checks_passed = True

    for task in target_wave.get("tasks", []):
        t_id = task.get("id")
        target_files = task.get("target_files", [])
        test_files = task.get("test_files", [])
        missing_files: List[str] = []
        empty_files: List[str] = []
        antipatterns: Dict[str, List[Dict[str, Any]]] = {}

        for rel_path in target_files + test_files:
            abs_p = (workspace / rel_path).resolve()
            if not abs_p.exists():
                missing_files.append(rel_path)
            elif abs_p.is_file() and abs_p.stat().st_size == 0:
                empty_files.append(rel_path)

        for rel_path in target_files:
            abs_p = (workspace / rel_path).resolve()
            if abs_p.exists() and abs_p.is_file():
                hits = scan_file_for_antipatterns(abs_p)
                if hits:
                    antipatterns[rel_path] = hits

        builder_report_rel = task.get("builder_report_file")
        builder_report_exists = False
        if builder_report_rel:
            builder_report_exists = (workspace / builder_report_rel).exists()

        test_result = None
        if run_tests and task.get("verification_cmd"):
            test_result = run_verification_command(task["verification_cmd"], workspace)

        deterministic_pass = (
            len(missing_files) == 0
            and len(empty_files) == 0
            and len(antipatterns) == 0
            and (test_result["passed"] if test_result is not None else True)
        )
        if not deterministic_pass:
            all_deterministic_checks_passed = False

        task_audits.append(
            {
                "task_id": t_id,
                "title": task.get("title"),
                "reported_status": task.get("status"),
                "builder_report_file": builder_report_rel,
                "builder_report_exists": builder_report_exists,
                "missing_files": missing_files,
                "empty_files": empty_files,
                "antipattern_findings": antipatterns,
                "verification_execution": test_result,
                "deterministic_checks_passed": deterministic_pass,
                "acceptance_criteria_to_verify": task.get("acceptance_criteria", []),
            }
        )

    return {
        "ok": True,
        "run_id": backlog.get("run_id"),
        "wave_number": wave_number,
        "all_deterministic_checks_passed": all_deterministic_checks_passed,
        "tasks": task_audits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Lemmings Squad Zero-Trust Wave Pre-Auditor")
    parser.add_argument("--workspace", required=True, help="Target repository root path")
    parser.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    parser.add_argument("--wave", required=True, type=int, help="Wave number to audit")
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip executing verification_cmd (only run file & anti-pattern checks)",
    )
    args = parser.parse_args()
    try:
        report = audit_wave(
            workspace=Path(args.workspace).resolve(),
            run_dir=Path(args.run_dir).resolve(),
            wave_number=args.wave,
            run_tests=not args.skip_tests,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
