#!/usr/bin/env python3
"""
Lemmings Squad Deploy Pre-Flight Checker (`check_deploy_readiness.py`).
Used by `lemming-floater` (Stage 6) and `lemming-basher` before executing a deployment
to verify cloud CLI authentication, required infra files (`Dockerfile`, `firebase.json`),
and required environment secrets/API keys.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def load_dotenv_keys(workspace: Path, env_name: str) -> set[str]:
    keys: set[str] = set()
    for candidate in [f".env.{env_name}", ".env.local", ".env"]:
        p = workspace / candidate
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() and v.strip():
                        keys.add(k.strip())
            except Exception:
                pass
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flight readiness check for Lemmings deployment")
    parser.add_argument("--workspace", required=True, help="Target repository root")
    parser.add_argument("--env", default="staging", help="Target environment (test, staging, homolog, none)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    env_name = args.env or "none"

    cfg_path = workspace / ".lemmings" / "config.json"
    cfg: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    deploy_cfg = cfg.get("deploy", {})
    strategy = deploy_cfg.get("default_strategy", "on_param")
    cloud_target = deploy_cfg.get("cloud_target", "custom")
    envs = deploy_cfg.get("environments", {})
    env_block = envs.get(env_name, {}) if isinstance(envs.get(env_name), dict) else {}
    deploy_cmd = str(env_block.get("command", "")).strip()
    smoke_cmd = str(env_block.get("smoke_test_cmd", "")).strip()
    req_secrets: List[str] = deploy_cfg.get("required_secrets", [])

    if env_name == "none" or strategy == "never" or not deploy_cmd:
        print(
            json.dumps(
                {
                    "ok": True,
                    "ready": False,
                    "should_skip": True,
                    "reason": f"No active deployment required for env='{env_name}' (strategy='{strategy}', command='{deploy_cmd or 'empty'}').",
                    "missing_items": [],
                    "remediation_commands": [],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    missing_items: List[str] = []
    remediation_cmds: List[str] = []

    # 1. Check required infra files & Cloud CLI authentication based on command / target
    cmd_lower = deploy_cmd.lower()
    if "gcloud " in cmd_lower or cloud_target in ("cloud-run", "gke"):
        if cloud_target == "cloud-run" and not (workspace / "Dockerfile").exists() and "--source" not in cmd_lower:
            missing_items.append("Missing `Dockerfile` for container deployment.")
            remediation_cmds.append("lemmings init-config --workspace . --with-cd --cloud-target cloud-run --scaffold-infra")
        gcloud_bin = shutil.which("gcloud")
        if not gcloud_bin:
            missing_items.append("Google Cloud CLI (`gcloud`) is not installed.")
            remediation_cmds.append("brew install --cask google-cloud-sdk && gcloud auth login")
        else:
            try:
                acc = subprocess.run(
                    [gcloud_bin, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if acc.returncode != 0 or not acc.stdout.strip():
                    missing_items.append("Google Cloud CLI (`gcloud`) has no active authenticated account.")
                    remediation_cmds.append("gcloud auth login && gcloud config set project <PROJECT_ID>")
            except Exception:
                pass

    if "firebase" in cmd_lower or cloud_target == "firebase":
        if not (workspace / "firebase.json").exists():
            missing_items.append("Missing `firebase.json` in repository root.")
            remediation_cmds.append("lemmings init-config --workspace . --with-cd --cloud-target firebase --scaffold-infra")

    # 2. Check required application secrets / API keys
    dotenv_keys = load_dotenv_keys(workspace, env_name)
    missing_secrets: List[str] = []
    for sec in req_secrets:
        if not os.environ.get(sec) and sec not in dotenv_keys:
            missing_secrets.append(sec)

    if missing_secrets:
        missing_items.append(
            f"Application secrets/API keys detected in code are not set in environment or .env.{env_name}: {', '.join(missing_secrets)}"
        )
        remediation_cmds.append(
            f"Configure {', '.join(missing_secrets)} in `.env.{env_name}` or export them before running deploy."
        )

    ready = len(missing_items) == 0
    print(
        json.dumps(
            {
                "ok": True,
                "ready": ready,
                "should_skip": False,
                "environment": env_name,
                "cloud_target": cloud_target,
                "deploy_cmd": deploy_cmd,
                "smoke_test_cmd": smoke_cmd,
                "missing_items": missing_items,
                "missing_secrets": missing_secrets,
                "remediation_commands": remediation_cmds,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
