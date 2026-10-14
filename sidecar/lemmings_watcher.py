#!/usr/bin/env python3
"""
Lemmings Squad Sidecar Watcher (`sidecar/lemmings_watcher.py`).
Monitors configured repositories for:
1. New specification files in `<workspace>/.lemmings/inbox/*.md`
2. Plan approvals (`APPROVED`) in `<workspace>/.lemmings/runs/<run-id>/02-implementation-plan.md`
   while `00-run-status.json` is at `02_WAITING_PLAN_APPROVAL`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


APPROVED_RE = re.compile(
    r"Status(?:\s+de\s+Aprova[cç][aã]o)?:\**\s*`?APPROVED`?",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(state_file: Path) -> Dict[str, Any]:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"dispatched_specs": [], "dispatched_approvals": []}


def save_state(state_file: Path, state: Dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def discover_workspaces(explicit_workspaces: List[str]) -> List[Path]:
    paths: List[Path] = []
    for w in explicit_workspaces:
        p = Path(w).expanduser().resolve()
        if p.is_dir() and p not in paths:
            paths.append(p)

    env_dirs = os.environ.get("LEMMINGS_WATCH_DIRS", "")
    for item in env_dirs.split(":"):
        item = item.strip()
        if item:
            p = Path(item).expanduser().resolve()
            if p.is_dir() and p not in paths:
                paths.append(p)

    reg_file = Path.home() / ".lemmings" / "workspaces.json"
    if reg_file.exists():
        try:
            data = json.loads(reg_file.read_text(encoding="utf-8"))
            for item in data.get("workspaces", []):
                p = Path(item).expanduser().resolve()
                if p.is_dir() and p not in paths:
                    paths.append(p)
        except Exception:
            pass

    return paths


def scan_workspace_once(workspace: Path, state: Dict[str, Any], dry_run: bool = False) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    agentapi_bin = shutil.which("agentapi")

    # 1. Check .lemmings/inbox/*.md for new specs
    inbox_dir = workspace / ".lemmings" / "inbox"
    if inbox_dir.is_dir():
        for spec_file in sorted(inbox_dir.glob("*.md")):
            key = f"{workspace}:{spec_file.name}:{int(spec_file.stat().st_mtime)}"
            if key in state["dispatched_specs"]:
                continue
            rel_spec = str(spec_file.relative_to(workspace))
            prompt = f"Use o Lemmings Squad para implementar a especificação '{rel_spec}' no repositório {workspace}."
            dispatched = False
            if not dry_run and agentapi_bin:
                subprocess.run(
                    [agentapi_bin, "new-conversation", f"--title=Lemmings Inbox: {spec_file.name}", prompt],
                    check=False,
                )
                dispatched = True
            state["dispatched_specs"].append(key)
            events.append(
                {
                    "type": "INBOX_SPEC_TRIGGERED",
                    "workspace": str(workspace),
                    "spec": rel_spec,
                    "prompt": prompt,
                    "agentapi_dispatched": dispatched,
                    "timestamp": now_iso(),
                }
            )

    # 2. Check .lemmings/runs/*/02-implementation-plan.md for APPROVED transition
    runs_dir = workspace / ".lemmings" / "runs"
    if runs_dir.is_dir():
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            status_path = run_dir / "00-run-status.json"
            plan_path = run_dir / "02-implementation-plan.md"
            if not status_path.exists() or not plan_path.exists():
                continue
            try:
                status_data = json.loads(status_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if status_data.get("current_step") != "02_WAITING_PLAN_APPROVAL":
                continue

            plan_text = plan_path.read_text(encoding="utf-8")
            if not APPROVED_RE.search(plan_text):
                continue

            run_id = status_data.get("run_id", run_dir.name)
            approval_key = f"{workspace}:{run_id}:APPROVED"
            if approval_key in state["dispatched_approvals"]:
                continue

            status_data["current_step"] = "02_PLAN_APPROVED"
            status_data["status"] = "IN_PROGRESS"
            status_data["updated_at"] = now_iso()
            status_path.write_text(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            prompt = f"Aprovado o plano da run {run_id} em {workspace}. Pode seguir com o Lemmings."
            dispatched = False
            if not dry_run and agentapi_bin:
                subprocess.run(
                    [agentapi_bin, "new-conversation", f"--title=Lemmings Approved: {run_id}", prompt],
                    check=False,
                )
                dispatched = True

            state["dispatched_approvals"].append(approval_key)
            events.append(
                {
                    "type": "PLAN_APPROVAL_TRIGGERED",
                    "workspace": str(workspace),
                    "run_id": run_id,
                    "prompt": prompt,
                    "agentapi_dispatched": dispatched,
                    "timestamp": now_iso(),
                }
            )

    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Lemmings Squad Sidecar File Watcher")
    parser.add_argument("--workspace", action="append", default=[], help="Workspace directory to watch")
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single scan pass and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not invoke agentapi binary")
    args = parser.parse_args()

    data_dir_env = os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR")
    if data_dir_env:
        state_file = Path(data_dir_env) / "watcher_state.json"
    elif args.workspace:
        state_file = Path(args.workspace[0]).resolve() / ".lemmings" / ".watcher_state.json"
    else:
        state_file = Path.home() / ".lemmings" / "watcher_state.json"

    state = load_state(state_file)

    while True:
        workspaces = discover_workspaces(args.workspace)
        all_events: List[Dict[str, Any]] = []
        for ws in workspaces:
            ev = scan_workspace_once(ws, state, dry_run=args.dry_run)
            if ev:
                all_events.extend(ev)
                save_state(state_file, state)

        if args.once:
            print(json.dumps({"ok": True, "events": all_events}, indent=2, ensure_ascii=False))
            return 0

        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
