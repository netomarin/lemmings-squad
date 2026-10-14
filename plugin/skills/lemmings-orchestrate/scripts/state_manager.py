#!/usr/bin/env python3
"""
Lemmings Squad — Atomic State & Backlog DAG Manager (state_manager.py)

Provides deterministic, file-locked operations over:
  - .lemmings/runs/<run-id>/00-run-status.json
  - .lemmings/runs/<run-id>/03-backlog.json
  - .lemmings/runs/<run-id>/03-backlog.md

Security & Integrity Guarantees:
  1. Exclusive file locking via fcntl.flock() on a dedicated .lock file.
  2. Path traversal prevention (rejects '..' or absolute paths escaping workspace).
  3. Atomic write-then-rename via tempfile + os.replace().
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, Generator, List, Set, Tuple

VALID_TASK_STATUSES = {
    "PENDING",
    "IN_PROGRESS",
    "DEV_DONE",
    "VERIFIED",
    "FAILED_VALIDATION",
    "HALTED",
}

RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
TASK_ID_PATTERN = re.compile(r"^TASK-[0-9A-Za-z_-]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def validate_safe_relative_path(rel_path: str, field_name: str = "path") -> str:
    """Ensure a relative path does not contain '..' traversal segments or start with '/'."""
    if not rel_path or not isinstance(rel_path, str):
        raise ValueError(f"Invalid empty {field_name}.")
    normalized = rel_path.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    if normalized.startswith("/") or ".." in parts:
        raise ValueError(
            f"Security violation in {field_name}: path traversal or absolute path not allowed ('{rel_path}')."
        )
    return normalized


def validate_run_id(run_id: str) -> str:
    if not run_id or ".." in run_id or "/" in run_id or "\\" in run_id or not RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Security violation: invalid run_id '{run_id}'.")
    return run_id


@contextmanager
def file_lock(run_dir: Path) -> Generator[None, None, None]:
    """Acquire an exclusive flock on <run_dir>/.state.lock."""
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / ".state.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_write_text(target_path: Path, content: str) -> None:
    """Write content to a temporary file in the same directory and atomically replace target_path."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(target_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def atomic_write_json(target_path: Path, data: Dict[str, Any]) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(target_path, content)


def read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_and_enrich_backlog(backlog: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Validate 03-backlog.json structure, DAG dependencies, path safety,
    and automatically detect file collisions within each wave to set isolation_mode.
    """
    errors: List[str] = []

    run_id = backlog.get("run_id", "")
    try:
        validate_run_id(run_id)
    except ValueError as e:
        errors.append(str(e))

    for path_field in ("spec_path", "plan_path"):
        val = backlog.get(path_field, "")
        try:
            validate_safe_relative_path(val, path_field)
        except ValueError as e:
            errors.append(str(e))

    waves = backlog.get("waves")
    if not isinstance(waves, list) or not waves:
        errors.append("Backlog must contain a non-empty 'waves' list.")
        return backlog, errors

    task_to_wave: Dict[str, int] = {}
    all_tasks: Dict[str, Dict[str, Any]] = {}

    # First pass: validate individual tasks and map task_id -> wave_number
    seen_wave_numbers: Set[int] = set()
    for wave in waves:
        wave_num = wave.get("wave_number")
        if not isinstance(wave_num, int) or wave_num < 1:
            errors.append(f"Invalid wave_number: {wave_num}")
            continue
        if wave_num in seen_wave_numbers:
            errors.append(f"Duplicate wave_number: {wave_num}")
        seen_wave_numbers.add(wave_num)

        tasks = wave.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"Wave {wave_num} must have a non-empty 'tasks' list.")
            continue

        wave_files_seen: Dict[str, str] = {}
        collision_detected = False

        for task in tasks:
            t_id = task.get("id", "")
            if not TASK_ID_PATTERN.match(str(t_id)):
                errors.append(f"Invalid task id '{t_id}' in wave {wave_num}. Expected 'TASK-XX'.")
            if t_id in all_tasks:
                errors.append(f"Duplicate task id '{t_id}'.")
            task_to_wave[t_id] = wave_num
            all_tasks[t_id] = task

            if not task.get("title"):
                errors.append(f"Task {t_id} is missing 'title'.")
            if not task.get("description"):
                errors.append(f"Task {t_id} is missing 'description'.")
            if not task.get("verification_cmd"):
                errors.append(f"Task {t_id} is missing 'verification_cmd' (planned test command).")

            criteria = task.get("acceptance_criteria")
            if not isinstance(criteria, list) or not criteria:
                errors.append(f"Task {t_id} must have at least one item in 'acceptance_criteria'.")

            target_files = task.get("target_files")
            if not isinstance(target_files, list) or not target_files:
                errors.append(f"Task {t_id} must have a non-empty 'target_files' list.")
                target_files = []

            test_files = task.get("test_files")
            if test_files is None:
                task["test_files"] = []
                test_files = []

            combined_files = set(target_files) | set(test_files)
            for fpath in combined_files:
                try:
                    norm_f = validate_safe_relative_path(fpath, f"{t_id}.files")
                    if norm_f in wave_files_seen and wave_files_seen[norm_f] != t_id:
                        collision_detected = True
                    wave_files_seen[norm_f] = t_id
                except ValueError as e:
                    errors.append(str(e))

            task.setdefault("depends_on", [])
            task.setdefault("status", "PENDING")
            task.setdefault("attempts", 0)
            task.setdefault(
                "builder_report_file",
                f".lemmings/runs/{run_id}/04-wave-{wave_num}-builder-{t_id}.md",
            )
            task.setdefault("inspector_history", [])

        wave["file_collision_detected"] = collision_detected
        if collision_detected:
            wave["isolation_mode"] = "share"
        else:
            wave.setdefault("isolation_mode", "inherit")
        wave.setdefault("title", f"Wave {wave_num}")
        wave["status"] = compute_wave_status(tasks)

    # Second pass: validate DAG dependencies (no unknown tasks, no cycles, dependencies must be in earlier waves)
    for t_id, task in all_tasks.items():
        w_num = task_to_wave[t_id]
        for dep_id in task.get("depends_on", []):
            if dep_id not in all_tasks:
                errors.append(f"Task {t_id} depends on unknown task '{dep_id}'.")
                continue
            dep_wave = task_to_wave[dep_id]
            if dep_wave >= w_num:
                errors.append(
                    f"DAG violation: Task {t_id} (Wave {w_num}) depends on {dep_id} (Wave {dep_wave}). "
                    f"Dependencies must belong to strictly earlier waves (< {w_num})."
                )

    return backlog, errors


def compute_wave_status(tasks: List[Dict[str, Any]]) -> str:
    statuses = [t.get("status", "PENDING") for t in tasks]
    if any(s == "HALTED" for s in statuses):
        return "HALTED"
    if all(s == "VERIFIED" for s in statuses):
        return "VERIFIED"
    if any(s == "FAILED_VALIDATION" for s in statuses):
        return "FAILED_VALIDATION"
    if all(s in ("DEV_DONE", "VERIFIED") for s in statuses):
        return "DEV_DONE"
    if any(s in ("IN_PROGRESS", "DEV_DONE", "VERIFIED") for s in statuses):
        return "IN_PROGRESS"
    return "PENDING"


def compute_backlog_status(waves: List[Dict[str, Any]], current_status: str) -> str:
    wave_statuses = [w.get("status", "PENDING") for w in waves]
    if any(s == "HALTED" for s in wave_statuses):
        return "HALTED"
    if all(s == "VERIFIED" for s in wave_statuses):
        if current_status in ("QA_PASSED", "COMPLETED"):
            return current_status
        return "ALL_VERIFIED"
    if any(s != "PENDING" for s in wave_statuses):
        return "IN_PROGRESS"
    return "READY"


def render_backlog_markdown(backlog: Dict[str, Any]) -> str:
    """Render 03-backlog.md from 03-backlog.json."""
    run_id = backlog.get("run_id", "")
    plan_path = backlog.get("plan_path", f".lemmings/runs/{run_id}/02-implementation-plan.md")
    status = backlog.get("status", "READY")
    updated = now_iso()

    lines: List[str] = [
        "---",
        f'run_id: "{run_id}"',
        'step: "03-backlog"',
        f'source_plan: "{plan_path}"',
        f'backlog_json: ".lemmings/runs/{run_id}/03-backlog.json"',
        f'status: "{status}"',
        f'updated_at: "{updated}"',
        "---",
        "",
        f"# Backlog de Execução em Ondas (DAG): `{run_id}`",
        "",
        "> Este arquivo é gerado e sincronizado automaticamente a partir de [`03-backlog.json`](./03-backlog.json).",
        "",
        "## 1. Resumo de Ondas e Isolamento",
        "",
        "| Onda (`Wave`) | Título | Modo de Isolamento (`Workspace`) | Colisão de Arquivos? | Total de Tasks | Status da Onda |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for wave in backlog.get("waves", []):
        w_num = wave.get("wave_number")
        w_title = wave.get("title", f"Wave {w_num}")
        iso = wave.get("isolation_mode", "inherit")
        collision = "Sim (`share`)" if wave.get("file_collision_detected") else "Não (`inherit`)"
        tasks = wave.get("tasks", [])
        w_status = wave.get("status", "PENDING")
        lines.append(
            f"| **Wave {w_num}** | {w_title} | `{iso}` | {collision} | {len(tasks)} | `{w_status}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 2. Matriz de Tasks, Critérios de Aceite e Testes Planejados",
        "",
    ])

    for wave in backlog.get("waves", []):
        w_num = wave.get("wave_number")
        w_title = wave.get("title", f"Wave {w_num}")
        iso = wave.get("isolation_mode", "inherit")
        w_status = wave.get("status", "PENDING")
        lines.append(f"### Wave {w_num}: {w_title} (`isolation_mode: {iso}` | Status: `{w_status}`)")
        lines.append("")

        for task in wave.get("tasks", []):
            t_id = task.get("id")
            t_title = task.get("title")
            t_status = task.get("status", "PENDING")
            checkbox = "[x]" if t_status == "VERIFIED" else "[ ]"
            deps = ", ".join(f"`{d}`" for d in task.get("depends_on", [])) or "Nenhuma"
            target_files = ", ".join(f"`{f}`" for f in task.get("target_files", []))
            test_files = ", ".join(f"`{f}`" for f in task.get("test_files", [])) or "Incluído em target_files"
            ver_cmd = task.get("verification_cmd", "")
            attempts = task.get("attempts", 0)
            builder_rep = task.get("builder_report_file") or "N/A"

            lines.append(f"- {checkbox} **`{t_id}` — {t_title}** (`{t_status}`, Tentativas: `{attempts}`)")
            lines.append(f"  - **Descrição:** {task.get('description', '')}")
            lines.append(f"  - **Dependências (`depends_on`):** {deps}")
            lines.append(f"  - **Arquivos-Alvo (`target_files`):** {target_files}")
            lines.append(f"  - **Arquivos de Teste (`test_files`):** {test_files}")
            lines.append(f"  - **Comando de Teste (`verification_cmd`):** `{ver_cmd}`")
            lines.append(f"  - **Relatório do Builder:** `{builder_rep}`")
            lines.append("  - **Critérios de Aceite:**")
            for crit in task.get("acceptance_criteria", []):
                crit_box = "[x]" if t_status == "VERIFIED" else "[ ]"
                lines.append(f"    - {crit_box} {crit}")
            if task.get("inspector_history"):
                last_entry = task["inspector_history"][-1]
                lines.append(
                    f"  - **Último Parecer do Inspector (Tentativa {last_entry.get('attempt')} - `{last_entry.get('verdict')}`):** "
                    f"{last_entry.get('feedback')} (`{last_entry.get('report_file')}`)"
                )
            lines.append("")

    return "\n".join(lines)


def sync_run_status(run_dir: Path, backlog: Dict[str, Any], current_step_override: str | None = None) -> None:
    status_path = run_dir / "00-run-status.json"
    run_id = backlog.get("run_id", run_dir.name)
    if status_path.exists():
        run_status = read_json(status_path)
    else:
        run_status = {
            "run_id": run_id,
            "spec_source": backlog.get("spec_path", ""),
            "current_step": "03_BACKLOG_READY",
            "status": "IN_PROGRESS",
            "auto_approve": False,
            "deploy_target": backlog.get("config", {}).get("deploy", {}).get("environment", "none"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "artifacts": {
                "scout_reports": [f".lemmings/runs/{run_id}/01-scout-report.md"],
                "implementation_plan": backlog.get("plan_path", f".lemmings/runs/{run_id}/02-implementation-plan.md"),
                "backlog_json": f".lemmings/runs/{run_id}/03-backlog.json",
                "backlog_md": f".lemmings/runs/{run_id}/03-backlog.md",
                "builder_reports": [],
                "inspector_reports": [],
                "bomber_reports": [],
                "floater_report": None,
                "final_summary": None,
            },
        }

    run_status["updated_at"] = now_iso()
    if current_step_override:
        run_status["current_step"] = current_step_override

    b_status = backlog.get("status", "READY")
    if b_status == "HALTED":
        run_status["status"] = "HALTED"
    elif b_status == "COMPLETED":
        run_status["status"] = "COMPLETED"
    else:
        run_status["status"] = "IN_PROGRESS"

    artifacts = run_status.setdefault("artifacts", {})
    artifacts["backlog_json"] = f".lemmings/runs/{run_id}/03-backlog.json"
    artifacts["backlog_md"] = f".lemmings/runs/{run_id}/03-backlog.md"

    builder_reports: List[str] = []
    inspector_reports: List[str] = []
    for wave in backlog.get("waves", []):
        for task in wave.get("tasks", []):
            if task.get("status") in ("DEV_DONE", "VERIFIED", "FAILED_VALIDATION") and task.get("builder_report_file"):
                rep = task["builder_report_file"]
                if rep not in builder_reports:
                    builder_reports.append(rep)
            for insp in task.get("inspector_history", []):
                irep = insp.get("report_file")
                if irep and irep not in inspector_reports:
                    inspector_reports.append(irep)

    artifacts["builder_reports"] = builder_reports
    artifacts["inspector_reports"] = inspector_reports
    bomber_reports: List[str] = []
    for qa_entry in backlog.get("qa_history", []):
        brep = qa_entry.get("report_file")
        if brep and brep not in bomber_reports:
            bomber_reports.append(brep)
    artifacts["bomber_reports"] = bomber_reports

    deploy_hist = backlog.get("deploy_history", [])
    if deploy_hist:
        artifacts["floater_report"] = deploy_hist[-1].get("report_file")

    if backlog.get("final_summary_file"):
        artifacts["final_summary"] = backlog["final_summary_file"]

    atomic_write_json(status_path, run_status)



def cmd_init_run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    run_id = validate_run_id(args.run_id)
    spec_rel = validate_safe_relative_path(args.spec, "spec")
    run_dir = workspace / ".lemmings" / "runs" / run_id

    with file_lock(run_dir):
        now = now_iso()
        status_data = {
            "run_id": run_id,
            "spec_source": spec_rel,
            "current_step": "01_SCOUT_RECONNAISSANCE",
            "status": "IN_PROGRESS",
            "auto_approve": bool(args.auto_approve),
            "deploy_target": args.deploy_target,
            "created_at": now,
            "updated_at": now,
            "artifacts": {
                "scout_reports": [],
                "implementation_plan": None,
                "backlog_json": None,
                "backlog_md": None,
                "builder_reports": [],
                "inspector_reports": [],
                "bomber_reports": [],
                "floater_report": None,
                "final_summary": None,
            },
        }
        status_path = run_dir / "00-run-status.json"
        atomic_write_json(status_path, status_data)
        print(json.dumps({"ok": True, "run_dir": str(run_dir), "status_file": str(status_path)}, indent=2))
    return 0


def cmd_validate_backlog(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    if not backlog_path.exists():
        print(json.dumps({"ok": False, "errors": [f"File not found: {backlog_path}"]}), file=sys.stderr)
        return 1

    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        backlog, errors = validate_and_enrich_backlog(backlog)
        if errors:
            print(json.dumps({"ok": False, "errors": errors}, indent=2), file=sys.stderr)
            return 1

        backlog["status"] = compute_backlog_status(backlog["waves"], backlog.get("status", "READY"))
        atomic_write_json(backlog_path, backlog)

        md_content = render_backlog_markdown(backlog)
        md_path = run_dir / "03-backlog.md"
        atomic_write_text(md_path, md_content)

        sync_run_status(run_dir, backlog, current_step_override="03_BACKLOG_READY")
        print(
            json.dumps(
                {
                    "ok": True,
                    "run_id": backlog["run_id"],
                    "total_waves": len(backlog["waves"]),
                    "total_tasks": sum(len(w["tasks"]) for w in backlog["waves"]),
                    "waves_summary": [
                        {
                            "wave_number": w["wave_number"],
                            "isolation_mode": w["isolation_mode"],
                            "file_collision_detected": w["file_collision_detected"],
                            "task_ids": [t["id"] for t in w["tasks"]],
                        }
                        for w in backlog["waves"]
                    ],
                },
                indent=2,
            )
        )
    return 0


def cmd_next_wave(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    if not backlog_path.exists():
        print(json.dumps({"ok": False, "error": f"Missing {backlog_path}"}), file=sys.stderr)
        return 1

    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        max_retries = backlog.get("config", {}).get("max_task_retries", 3)

        if backlog.get("status") == "HALTED":
            print(json.dumps({"ok": True, "status": "HALTED", "wave": None}, indent=2))
            return 0

        for wave in sorted(backlog.get("waves", []), key=lambda w: w["wave_number"]):
            w_status = compute_wave_status(wave.get("tasks", []))
            if w_status == "VERIFIED":
                continue
            if w_status == "HALTED":
                print(
                    json.dumps(
                        {"ok": True, "status": "HALTED", "wave_number": wave["wave_number"]},
                        indent=2,
                    )
                )
                return 0

            executable = [
                t
                for t in wave.get("tasks", [])
                if t.get("status") in ("PENDING", "FAILED_VALIDATION") and t.get("attempts", 0) < max_retries
            ]
            step_status = "WAVE_DEV_DONE" if (w_status == "DEV_DONE" and not executable) else "WAVE_READY"
            print(
                json.dumps(
                    {
                        "ok": True,
                        "status": step_status,
                        "wave_number": wave["wave_number"],
                        "title": wave.get("title", f"Wave {wave['wave_number']}"),
                        "isolation_mode": wave.get("isolation_mode", "inherit"),
                        "file_collision_detected": wave.get("file_collision_detected", False),
                        "wave_status": w_status,
                        "all_wave_tasks": wave.get("tasks", []),
                        "executable_tasks": executable,
                    },
                    indent=2,
                )
            )
            return 0

        print(json.dumps({"ok": True, "status": "ALL_WAVES_VERIFIED", "wave": None}, indent=2))
    return 0


def cmd_update_task(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    if args.status not in VALID_TASK_STATUSES:
        raise ValueError(f"Invalid status '{args.status}'. Must be one of {sorted(VALID_TASK_STATUSES)}.")

    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        max_retries = backlog.get("config", {}).get("max_task_retries", 3)
        found_task = None
        found_wave = None

        for wave in backlog.get("waves", []):
            for task in wave.get("tasks", []):
                if task.get("id") == args.task_id:
                    found_task = task
                    found_wave = wave
                    break
            if found_task:
                break

        if not found_task or not found_wave:
            print(json.dumps({"ok": False, "error": f"Task '{args.task_id}' not found."}), file=sys.stderr)
            return 1

        if args.builder_report:
            found_task["builder_report_file"] = validate_safe_relative_path(
                args.builder_report, "builder_report"
            )

        if args.status == "FAILED_VALIDATION":
            found_task["attempts"] = int(found_task.get("attempts", 0)) + 1
            insp_rep = (
                validate_safe_relative_path(args.inspector_report, "inspector_report")
                if args.inspector_report
                else f".lemmings/runs/{backlog['run_id']}/05-wave-{found_wave['wave_number']}-inspector-attempt-{found_task['attempts']}.md"
            )
            found_task.setdefault("inspector_history", []).append(
                {
                    "attempt": found_task["attempts"],
                    "verdict": "FAILED_VALIDATION",
                    "feedback": args.feedback or "Validation failed.",
                    "report_file": insp_rep,
                    "timestamp": now_iso(),
                }
            )
            if found_task["attempts"] >= max_retries:
                found_task["status"] = "HALTED"
            else:
                found_task["status"] = "FAILED_VALIDATION"
        elif args.status == "VERIFIED":
            attempt_num = max(1, int(found_task.get("attempts", 0)) + 1)
            insp_rep = (
                validate_safe_relative_path(args.inspector_report, "inspector_report")
                if args.inspector_report
                else f".lemmings/runs/{backlog['run_id']}/05-wave-{found_wave['wave_number']}-inspector-attempt-{attempt_num}.md"
            )
            found_task["status"] = "VERIFIED"
            found_task.setdefault("inspector_history", []).append(
                {
                    "attempt": attempt_num,
                    "verdict": "VERIFIED",
                    "feedback": args.feedback or "All acceptance criteria and tests verified.",
                    "report_file": insp_rep,
                    "timestamp": now_iso(),
                }
            )
        else:
            found_task["status"] = args.status

        found_wave["status"] = compute_wave_status(found_wave["tasks"])
        backlog["status"] = compute_backlog_status(backlog["waves"], backlog.get("status", "READY"))

        atomic_write_json(backlog_path, backlog)
        atomic_write_text(run_dir / "03-backlog.md", render_backlog_markdown(backlog))

        step_label = f"04_WAVE_{found_wave['wave_number']}_{found_wave['status']}"
        if backlog["status"] == "ALL_VERIFIED":
            step_label = "05_ALL_WAVES_VERIFIED"
        elif backlog["status"] == "HALTED":
            step_label = f"05_CIRCUIT_BREAKER_WAVE_{found_wave['wave_number']}"

        sync_run_status(run_dir, backlog, current_step_override=step_label)
        print(
            json.dumps(
                {
                    "ok": True,
                    "task_id": found_task["id"],
                    "task_status": found_task["status"],
                    "attempts": found_task["attempts"],
                    "wave_status": found_wave["status"],
                    "backlog_status": backlog["status"],
                },
                indent=2,
            )
        )
    return 0


def cmd_check_wave_gate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        max_retries = backlog.get("config", {}).get("max_task_retries", 3)
        target_wave = None
        for wave in backlog.get("waves", []):
            if wave.get("wave_number") == args.wave:
                target_wave = wave
                break
        if not target_wave:
            print(json.dumps({"ok": False, "error": f"Wave {args.wave} not found."}), file=sys.stderr)
            return 1

        tasks = target_wave.get("tasks", [])
        halted = [
            t["id"]
            for t in tasks
            if t.get("status") == "HALTED"
            or (t.get("status") == "FAILED_VALIDATION" and t.get("attempts", 0) >= max_retries)
        ]
        if halted:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "gate": "CIRCUIT_BREAKER",
                        "wave_number": args.wave,
                        "halted_tasks": halted,
                    },
                    indent=2,
                )
            )
            return 0

        retry = [
            t["id"]
            for t in tasks
            if t.get("status") == "FAILED_VALIDATION" and t.get("attempts", 0) < max_retries
        ]
        if retry:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "gate": "RETRY_REQUIRED",
                        "wave_number": args.wave,
                        "retry_tasks": retry,
                    },
                    indent=2,
                )
            )
            return 0

        if all(t.get("status") == "VERIFIED" for t in tasks):
            print(json.dumps({"ok": True, "gate": "PASSED", "wave_number": args.wave}, indent=2))
            return 0

        pending = [t["id"] for t in tasks if t.get("status") != "VERIFIED"]
        print(
            json.dumps(
                {
                    "ok": True,
                    "gate": "INCOMPLETE",
                    "wave_number": args.wave,
                    "pending_tasks": pending,
                },
                indent=2,
            )
        )
    return 0


def cmd_record_qa(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        run_id = backlog.get("run_id", run_dir.name)
        max_qa_retries = int(backlog.get("config", {}).get("max_qa_retries", 2))
        qa_attempts = int(backlog.get("qa_attempts", 0)) + 1
        backlog["qa_attempts"] = qa_attempts

        report_rel = (
            validate_safe_relative_path(args.report, "report")
            if args.report
            else f".lemmings/runs/{run_id}/06-bomber-qa-security-attempt-{qa_attempts}.md"
        )
        backlog.setdefault("qa_history", []).append(
            {
                "attempt": qa_attempts,
                "verdict": args.verdict,
                "report_file": report_rel,
                "summary": args.summary or "",
                "timestamp": now_iso(),
            }
        )

        if args.verdict == "PASSED":
            backlog["status"] = "QA_PASSED"
            action = "PROCEED_TO_DEPLOY_OR_FINISH"
            step_label = "06_QA_SECURITY_PASSED"
        else:
            if qa_attempts > max_qa_retries:
                backlog["status"] = "HALTED"
                action = "CIRCUIT_BREAKER"
                step_label = "06_QA_CIRCUIT_BREAKER"
            else:
                backlog["status"] = "IN_PROGRESS"
                action = "CREATE_HOTFIX_WAVE"
                step_label = f"06_QA_FAILED_ATTEMPT_{qa_attempts}_NEEDS_HOTFIX"

        atomic_write_json(backlog_path, backlog)
        atomic_write_text(run_dir / "03-backlog.md", render_backlog_markdown(backlog))
        sync_run_status(run_dir, backlog, current_step_override=step_label)
        print(
            json.dumps(
                {
                    "ok": True,
                    "qa_attempt": qa_attempts,
                    "verdict": args.verdict,
                    "action": action,
                    "report_file": report_rel,
                    "backlog_status": backlog["status"],
                },
                indent=2,
            )
        )
    return 0


def cmd_add_hotfix_wave(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    raw_tasks = json.loads(args.tasks_json)
    if isinstance(raw_tasks, dict):
        raw_tasks = [raw_tasks]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("tasks-json must be a non-empty JSON list of task objects.")

    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        run_id = backlog.get("run_id", run_dir.name)
        waves = backlog.setdefault("waves", [])
        next_wave_num = max((w.get("wave_number", 0) for w in waves), default=0) + 1
        qa_attempt = int(backlog.get("qa_attempts", 1))

        for t in raw_tasks:
            t_id = t.get("id", f"TASK-HF{qa_attempt}")
            t["id"] = t_id
            t.setdefault("depends_on", [])
            t.setdefault("test_files", [])
            t["status"] = "PENDING"
            t["attempts"] = 0
            t["builder_report_file"] = f".lemmings/runs/{run_id}/04-wave-{next_wave_num}-builder-{t_id}.md"
            t["inspector_history"] = []

        new_wave = {
            "wave_number": next_wave_num,
            "title": f"Wave {next_wave_num} — Hotfix QA & Security (Attempt {qa_attempt})",
            "isolation_mode": "inherit",
            "file_collision_detected": False,
            "status": "PENDING",
            "tasks": raw_tasks,
        }
        waves.append(new_wave)

        backlog, errors = validate_and_enrich_backlog(backlog)
        if errors:
            print(json.dumps({"ok": False, "errors": errors}, indent=2), file=sys.stderr)
            return 1

        backlog["status"] = "IN_PROGRESS"
        atomic_write_json(backlog_path, backlog)
        atomic_write_text(run_dir / "03-backlog.md", render_backlog_markdown(backlog))
        sync_run_status(run_dir, backlog, current_step_override=f"04_WAVE_{next_wave_num}_HOTFIX_READY")
        print(
            json.dumps(
                {
                    "ok": True,
                    "wave_number": next_wave_num,
                    "isolation_mode": new_wave["isolation_mode"],
                    "task_ids": [t["id"] for t in raw_tasks],
                },
                indent=2,
            )
        )
    return 0


def cmd_record_deploy(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        run_id = backlog.get("run_id", run_dir.name)
        env_name = args.env or "none"
        report_rel = (
            validate_safe_relative_path(args.report, "report")
            if args.report
            else f".lemmings/runs/{run_id}/07-floater-deploy-{env_name}.md"
        )
        backlog.setdefault("deploy_history", []).append(
            {
                "environment": env_name,
                "verdict": args.verdict,
                "report_file": report_rel,
                "summary": args.summary or "",
                "timestamp": now_iso(),
            }
        )

        if args.verdict == "FAILED":
            backlog["status"] = "HALTED"
            step_label = f"07_DEPLOY_FAILED_{env_name.upper()}"
            action = "HALTED"
        elif args.verdict == "SKIPPED":
            step_label = "07_DEPLOY_SKIPPED"
            action = "FINALIZE_RUN"
        else:
            step_label = f"07_DEPLOYED_{env_name.upper()}"
            action = "FINALIZE_RUN"

        atomic_write_json(backlog_path, backlog)
        atomic_write_text(run_dir / "03-backlog.md", render_backlog_markdown(backlog))
        sync_run_status(run_dir, backlog, current_step_override=step_label)
        print(
            json.dumps(
                {
                    "ok": True,
                    "environment": env_name,
                    "verdict": args.verdict,
                    "action": action,
                    "report_file": report_rel,
                    "backlog_status": backlog["status"],
                },
                indent=2,
            )
        )
    return 0


def render_final_summary_markdown(
    run_status: Dict[str, Any], backlog: Dict[str, Any], executive_summary: str | None = None
) -> str:
    run_id = backlog.get("run_id", run_status.get("run_id", "unknown"))
    spec_path = backlog.get("spec_path", run_status.get("spec_source", ""))
    final_status = backlog.get("status", "COMPLETED")
    created_at = run_status.get("created_at", now_iso())
    completed_at = now_iso()

    waves = backlog.get("waves", [])
    total_waves = len(waves)
    all_tasks = [t for w in waves for t in w.get("tasks", [])]
    total_tasks = len(all_tasks)
    verified_tasks = sum(1 for t in all_tasks if t.get("status") == "VERIFIED")

    qa_hist = backlog.get("qa_history", [])
    qa_attempts = backlog.get("qa_attempts", len(qa_hist))
    last_qa = qa_hist[-1] if qa_hist else {}
    qa_verdict = last_qa.get("verdict", "N/A")
    last_bomber_report = last_qa.get("report_file", "N/A")
    qa_summary = last_qa.get("summary", "Suíte global de QA e segurança executada com sucesso.")

    deploy_hist = backlog.get("deploy_history", [])
    last_deploy = deploy_hist[-1] if deploy_hist else {}
    deploy_verdict = last_deploy.get("verdict", "SKIPPED")
    deploy_env = last_deploy.get("environment", run_status.get("deploy_target", "none"))
    floater_report = last_deploy.get("report_file", "N/A")
    deploy_summary = last_deploy.get(
        "summary",
        "Deploy ignorado conforme política configurada (`on_param` / `never`).",
    )

    exec_text = (
        executive_summary
        or f"Ciclo completo do Lemmings Squad concluído para `{spec_path}` com {verified_tasks}/{total_tasks} tasks verificadas em {total_waves} onda(s)."
    )

    lines: List[str] = [
        "# Relatório Consolidado de Execução (`08-final-summary.md`)",
        "",
        f"- **Run ID:** `{run_id}`",
        f"- **Especificação Origem:** `{spec_path}`",
        f"- **Status Final:** `{final_status}`",
        f"- **Início da Run:** `{created_at}`",
        f"- **Conclusão da Run:** `{completed_at}`",
        "",
        "---",
        "",
        "## 1. Resumo Executivo",
        "",
        exec_text,
        "",
        "| Métrica | Valor |",
        "| :--- | :--- |",
        f"| **Total de Ondas (Waves) Executadas** | `{total_waves}` |",
        f"| **Total de Tasks Concluídas (`VERIFIED`)** | `{verified_tasks} / {total_tasks}` |",
        f"| **Tentativas de QA Global & AppSec (`Bomber`)** | `{qa_attempts}` (`{qa_verdict}`) |",
        f"| **Status de Deploy (`Floater`)** | `{deploy_verdict}` (Ambiente: `{deploy_env}`) |",
        "",
        "---",
        "",
        "## 2. Entregas por Onda (Waves & Tasks)",
        "",
        "| Wave | Task ID | Título | Status | Tentativas | Arquivos Alvo | Relatório do Builder |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for w in waves:
        w_num = w.get("wave_number")
        for t in w.get("tasks", []):
            t_files = ", ".join(f"`{f}`" for f in t.get("target_files", []))
            b_rep = f"`{t.get('builder_report_file', '')}`" if t.get("builder_report_file") else "-"
            lines.append(
                f"| Wave {w_num} | `{t.get('id')}` | {t.get('title')} | `{t.get('status')}` | "
                f"{t.get('attempts', 0)} | {t_files} | {b_rep} |"
            )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Qualidade Global e Segurança (`lemming-bomber`)",
            "",
            f"- **Relatório:** `{last_bomber_report}`",
            f"- **Resumo:** {qa_summary}",
            "",
            "---",
            "",
            "## 4. Deploy e Homologação (`lemming-floater`)",
            "",
            f"- **Relatório:** `{floater_report}`",
            f"- **Resumo:** {deploy_summary}",
            "",
            "---",
            "",
            "## 5. Índice Completo de Artefatos Gerados na Run",
            "",
            f"- **Status Global (`00`):** `.lemmings/runs/{run_id}/00-run-status.json`",
        ]
    )

    artifacts = run_status.get("artifacts", {})
    for s_rep in artifacts.get("scout_reports", []):
        lines.append(f"- **Scout (`01`):** `{s_rep}`")
    if artifacts.get("implementation_plan"):
        lines.append(f"- **Plano de Implementação (`02`):** `{artifacts['implementation_plan']}`")
    if artifacts.get("backlog_json"):
        lines.append(f"- **Backlog Estruturado (`03`):** `{artifacts['backlog_json']}` & `{artifacts.get('backlog_md', '')}`")
    for b_rep in artifacts.get("builder_reports", []):
        lines.append(f"- **Builder (`04`):** `{b_rep}`")
    for i_rep in artifacts.get("inspector_reports", []):
        lines.append(f"- **Inspector (`05`):** `{i_rep}`")
    for qa_rep in artifacts.get("bomber_reports", []):
        lines.append(f"- **Bomber QA & AppSec (`06`):** `{qa_rep}`")
    if artifacts.get("floater_report"):
        lines.append(f"- **Floater Deploy (`07`):** `{artifacts['floater_report']}`")
    lines.append(f"- **Resumo Final (`08`):** `.lemmings/runs/{run_id}/08-final-summary.md`")
    lines.append("")
    return "\n".join(lines)


def cmd_finalize_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    backlog_path = run_dir / "03-backlog.json"
    status_path = run_dir / "00-run-status.json"
    with file_lock(run_dir):
        backlog = read_json(backlog_path)
        run_id = backlog.get("run_id", run_dir.name)
        summary_rel = f".lemmings/runs/{run_id}/08-final-summary.md"
        summary_abs = run_dir / "08-final-summary.md"

        backlog["status"] = "COMPLETED"
        backlog["final_summary_file"] = summary_rel
        atomic_write_json(backlog_path, backlog)
        atomic_write_text(run_dir / "03-backlog.md", render_backlog_markdown(backlog))
        sync_run_status(run_dir, backlog, current_step_override="08_COMPLETED")

        run_status = read_json(status_path)
        if not summary_abs.exists() or args.overwrite_summary:
            md_text = render_final_summary_markdown(run_status, backlog, args.summary)
            atomic_write_text(summary_abs, md_text)

        print(
            json.dumps(
                {
                    "ok": True,
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "current_step": "08_COMPLETED",
                    "final_summary": summary_rel,
                },
                indent=2,
            )
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lemmings Squad Atomic State & Backlog Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-run", help="Initialize .lemmings/runs/<run-id>/00-run-status.json")
    p_init.add_argument("--workspace", required=True, help="Target repository root path")
    p_init.add_argument("--run-id", required=True, help="Run ID (e.g., 20260929-feature-slug)")
    p_init.add_argument("--spec", required=True, help="Relative path to the specification file")
    p_init.add_argument("--auto-approve", action="store_true", help="Set auto_approve=true")
    p_init.add_argument("--deploy-target", default="none", choices=["none", "test", "staging", "homolog"])
    p_init.set_defaults(func=cmd_init_run)

    p_val = sub.add_parser(
        "validate-backlog",
        help="Validate 03-backlog.json DAG, detect file collisions, and render 03-backlog.md",
    )
    p_val.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_val.set_defaults(func=cmd_validate_backlog)

    p_next = sub.add_parser("next-wave", help="Return next executable wave and tasks in JSON")
    p_next.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_next.set_defaults(func=cmd_next_wave)

    p_upd = sub.add_parser("update-task", help="Atomically update task status and sync 03-backlog.md")
    p_upd.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_upd.add_argument("--task-id", required=True, help="Task ID (e.g., TASK-01)")
    p_upd.add_argument("--status", required=True, choices=sorted(VALID_TASK_STATUSES))
    p_upd.add_argument("--builder-report", default=None, help="Relative path to 04-wave-W-builder-TASK.md")
    p_upd.add_argument("--inspector-report", default=None, help="Relative path to 05-wave-W-inspector-attempt-A.md")
    p_upd.add_argument("--feedback", default=None, help="Inspector validation feedback")
    p_upd.set_defaults(func=cmd_update_task)

    p_gate = sub.add_parser("check-wave-gate", help="Check if wave passed, needs retry, or hit circuit breaker")
    p_gate.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_gate.add_argument("--wave", required=True, type=int, help="Wave number")
    p_gate.set_defaults(func=cmd_check_wave_gate)

    p_qa = sub.add_parser("record-qa", help="Record Bomber full QA and security scan verdict")
    p_qa.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_qa.add_argument("--verdict", required=True, choices=["PASSED", "FAILED"])
    p_qa.add_argument("--report", default=None, help="Relative path to 06-bomber-qa-security-attempt-A.md")
    p_qa.add_argument("--summary", default=None, help="Summary of QA/security findings")
    p_qa.set_defaults(func=cmd_record_qa)

    p_hf = sub.add_parser("add-hotfix-wave", help="Append a corrective Hotfix Wave after Bomber QA/Security failure")
    p_hf.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_hf.add_argument("--tasks-json", required=True, help="JSON string of hotfix task(s) to add")
    p_hf.set_defaults(func=cmd_add_hotfix_wave)

    p_dep = sub.add_parser("record-deploy", help="Record Floater staging/test deployment verdict")
    p_dep.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_dep.add_argument("--env", default="none", help="Target environment (test, staging, homolog, none)")
    p_dep.add_argument("--verdict", required=True, choices=["DEPLOYED", "SKIPPED", "FAILED"])
    p_dep.add_argument("--report", default=None, help="Relative path to 07-floater-deploy-<env>.md")
    p_dep.add_argument("--summary", default=None, help="Summary of deployment and smoke test")
    p_dep.set_defaults(func=cmd_record_deploy)

    p_fin = sub.add_parser("finalize-run", help="Render 08-final-summary.md and mark the run as COMPLETED")
    p_fin.add_argument("--run-dir", required=True, help="Path to .lemmings/runs/<run-id>")
    p_fin.add_argument("--summary", default=None, help="Executive summary text for 08-final-summary.md")
    p_fin.add_argument("--overwrite-summary", action="store_true", help="Overwrite existing 08-final-summary.md")
    p_fin.set_defaults(func=cmd_finalize_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
