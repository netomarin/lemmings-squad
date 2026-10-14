#!/usr/bin/env python3
"""
Lemmings Squad Repository & CI/CD Initializer (`init_config.py`).
Analyzes a target repository, auto-discovers build/test/lint/security/deploy commands,
scans source code for required environment variables/API keys (`env_scanner`),
evaluates deployability signals (`deploy_signals`) and cloud CLI readiness (`cloud_preflight`),
optionally scaffolds missing deployment files (`Dockerfile`, `.env.example`),
and builds/updates CI/CD pipelines and `.lemmings/cicd-pipeline-report.md`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


IGNORED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".lemmings",
    "coverage",
    "target",
}

ENV_PATTERNS = [
    re.compile(r"\bprocess\.env\.([A-Z][A-Z0-9_]{2,})\b"),
    re.compile(r"\bimport\.meta\.env\.([A-Z][A-Z0-9_]{2,})\b"),
    re.compile(r"\bos\.environ(?:\.get)?\(\s*['\"]([A-Z][A-Z0-9_]{2,})['\"]"),
    re.compile(r"\bos\.environ\[\s*['\"]([A-Z][A-Z0-9_]{2,})['\"]\s*\]"),
    re.compile(r"\bos\.getenv\(\s*['\"]([A-Z][A-Z0-9_]{2,})['\"]"),
    re.compile(r"\bos\.Getenv\(\s*\"([A-Z][A-Z0-9_]{2,})\"\s*\)"),
]

SECRET_KEYWORDS = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
    "PRIVATE",
    "AUTH",
    "DATABASE_URL",
    "DB_URL",
    "REDIS_URL",
    "DSN",
    "WEBHOOK",
    "CERT",
)

STANDARD_NON_SECRET_VARS = {
    "NODE_ENV",
    "PORT",
    "HOST",
    "TZ",
    "CI",
    "DEBUG",
    "LOG_LEVEL",
    "PATH",
    "HOME",
    "PWD",
    "PYTHONPATH",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_secret_var_name(name: str) -> bool:
    if name in STANDARD_NON_SECRET_VARS:
        return False
    upper = name.upper()
    return any(k in upper for k in SECRET_KEYWORDS)


def scan_env_vars_and_secrets(workspace: Path) -> Dict[str, List[str]]:
    """
    Scans repository source files and .env.example/.env.sample for environment variables
    and classifies them into `secret_vars` (API keys, tokens, DB URLs) and `config_vars`.
    """
    found_vars: Set[str] = set()

    for env_sample in [".env.example", ".env.sample", ".env.template"]:
        p = workspace / env_sample
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key = line.split("=", 1)[0].strip()
                    if re.match(r"^[A-Z][A-Z0-9_]{2,}$", key):
                        found_vars.add(key)
            except Exception:
                pass

    exts = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java"}
    files_scanned = 0
    for root_Or_file in workspace.rglob("*"):
        if files_scanned > 400:
            break
        if any(part in IGNORED_DIRS for part in root_Or_file.parts):
            continue
        if root_Or_file.is_file() and root_Or_file.suffix in exts:
            files_scanned += 1
            try:
                text = root_Or_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for pat in ENV_PATTERNS:
                for match in pat.findall(text):
                    if match not in {"PATH", "HOME", "PWD", "PYTHONPATH"}:
                        found_vars.add(match)

    secret_vars = sorted(v for v in found_vars if is_secret_var_name(v))
    config_vars = sorted(v for v in found_vars if not is_secret_var_name(v))
    return {
        "secret_vars": secret_vars,
        "config_vars": config_vars,
    }


def detect_deploy_signals_and_cloud_readiness(
    workspace: Path, env_scan: Dict[str, List[str]]
) -> Dict[str, Any]:
    """
    Evaluates whether the repository shows strong/medium evidence of being deployable
    (`deploy_signals`) and checks local Cloud CLI authentication (`cloud_preflight`).
    """
    infra_artifacts: List[str] = []
    app_signals: List[str] = []

    infra_candidates = [
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "firebase.json",
        ".firebaserc",
        "apphosting.yaml",
        "cloudbuild.yaml",
        "vercel.json",
        "fly.toml",
        "render.yaml",
        "Procfile",
    ]
    for name in infra_candidates:
        if (workspace / name).exists():
            infra_artifacts.append(name)
    for k8s_dir in ["k8s", "manifests", "helm", "charts"]:
        if (workspace / k8s_dir).is_dir():
            infra_artifacts.append(f"{k8s_dir}/")

    pkg_json = workspace / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        except Exception:
            pkg = {}
        scripts = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}
        deps = {}
        for dep_key in ("dependencies", "devDependencies"):
            if isinstance(pkg.get(dep_key), dict):
                deps.update(pkg[dep_key])

        for s_name in scripts:
            if s_name.startswith("deploy"):
                infra_artifacts.append(f"package.json:scripts.{s_name}")
        if "start" in scripts or "preview" in scripts or "serve" in scripts:
            app_signals.append("package.json:start/serve script")

        web_frameworks = [
            "next",
            "express",
            "fastify",
            "@nestjs/core",
            "vite",
            "react",
            "vue",
            "@angular/core",
            "hono",
            "koa",
            "astro",
            "nuxt",
        ]
        for fw in web_frameworks:
            if fw in deps:
                app_signals.append(f"npm:{fw}")

    for py_file in ["pyproject.toml", "requirements.txt"]:
        p = workspace / py_file
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore").lower()
                for fw in ["fastapi", "uvicorn", "flask", "django", "gunicorn", "streamlit", "gradio"]:
                    if fw in txt:
                        app_signals.append(f"python:{fw}")
            except Exception:
                pass

    go_mod = workspace / "go.mod"
    if go_mod.exists():
        try:
            txt = go_mod.read_text(encoding="utf-8", errors="ignore").lower()
            for fw in ["gin-gonic/gin", "labstack/echo", "gofiber/fiber", "gorilla/mux"]:
                if fw in txt:
                    app_signals.append(f"go:{fw}")
        except Exception:
            pass

    # Determine recommended cloud target
    if any(x in infra_artifacts for x in ("firebase.json", ".firebaserc", "apphosting.yaml")):
        recommended_target = "firebase"
    elif any(x in infra_artifacts for x in ("k8s/", "manifests/", "helm/", "charts/")):
        recommended_target = "gke"
    elif "Dockerfile" in infra_artifacts or "cloudbuild.yaml" in infra_artifacts or app_signals:
        recommended_target = "cloud-run"
    else:
        recommended_target = "custom"

    if infra_artifacts:
        confidence = "high"
    elif app_signals:
        confidence = "medium"
    else:
        confidence = "none"

    should_suggest_cd = confidence in ("high", "medium")

    # Cloud CLI Pre-Flight checks
    gcloud_bin = shutil.which("gcloud")
    gcloud_active_account = ""
    gcloud_project = ""
    if gcloud_bin:
        try:
            acc_proc = subprocess.run(
                [gcloud_bin, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if acc_proc.returncode == 0:
                gcloud_active_account = acc_proc.stdout.strip().splitlines()[0] if acc_proc.stdout.strip() else ""
            proj_proc = subprocess.run(
                [gcloud_bin, "config", "get-value", "project"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proj_proc.returncode == 0 and proj_proc.stdout.strip() != "(unset)":
                gcloud_project = proj_proc.stdout.strip()
        except Exception:
            pass

    firebase_installed = bool(shutil.which("firebase"))
    kubectl_installed = bool(shutil.which("kubectl"))
    docker_installed = bool(shutil.which("docker"))

    return {
        "confidence": confidence,
        "should_suggest_cd": should_suggest_cd,
        "recommended_target": recommended_target,
        "infra_artifacts": infra_artifacts,
        "app_signals": app_signals,
        "detected_secret_vars": env_scan["secret_vars"],
        "detected_config_vars": env_scan["config_vars"],
        "cloud_preflight": {
            "gcloud_installed": bool(gcloud_bin),
            "gcloud_authenticated": bool(gcloud_active_account),
            "gcloud_account": gcloud_active_account,
            "gcloud_project": gcloud_project,
            "firebase_cli_installed": firebase_installed,
            "kubectl_installed": kubectl_installed,
            "docker_installed": docker_installed,
        },
    }


def check_and_prepare_git_readiness(workspace: Path, auto_init_git: bool = True) -> Dict[str, Any]:
    git_dir = workspace / ".git"
    git_bin = shutil.which("git")
    gh_bin = shutil.which("gh")

    git_initialized = git_dir.exists()
    git_auto_initialized = False

    if not git_initialized and auto_init_git and git_bin:
        proc = subprocess.run(
            [git_bin, "init", "-b", "main"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                [git_bin, "init"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
            )
        if proc.returncode == 0 and git_dir.exists():
            git_initialized = True
            git_auto_initialized = True

    remote_url = ""
    if git_initialized and git_bin:
        r_proc = subprocess.run(
            [git_bin, "remote", "get-url", "origin"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        if r_proc.returncode == 0:
            remote_url = r_proc.stdout.strip()

    gh_installed = bool(gh_bin)
    gh_authenticated = False
    if gh_bin:
        try:
            gh_proc = subprocess.run(
                [gh_bin, "auth", "status"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=5,
            )
            gh_authenticated = gh_proc.returncode == 0
        except Exception:
            gh_authenticated = False

    return {
        "git_initialized": git_initialized,
        "git_auto_initialized": git_auto_initialized,
        "has_remote": bool(remote_url),
        "remote_url": remote_url,
        "gh_installed": gh_installed,
        "gh_authenticated": gh_authenticated,
        "local_hooks_activated": False,
    }


def detect_ci_provider(workspace: Path, requested: str = "auto") -> str:
    if requested and requested != "auto":
        mapping = {
            "github": "github-actions",
            "github-actions": "github-actions",
            "gitlab": "gitlab-ci",
            "gitlab-ci": "gitlab-ci",
            "cloudbuild": "cloud-build",
            "cloud-build": "cloud-build",
            "githooks": "git-hooks",
            "git-hooks": "git-hooks",
        }
        return mapping.get(requested, "github-actions")

    git_config = workspace / ".git" / "config"
    remote_text = ""
    if git_config.exists():
        try:
            remote_text = git_config.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            remote_text = ""

    if "gitlab" in remote_text or (workspace / ".gitlab-ci.yml").exists():
        return "gitlab-ci"
    if (workspace / "cloudbuild.yaml").exists():
        return "cloud-build"
    if "github.com" in remote_text or (workspace / ".github").exists():
        return "github-actions"
    return "github-actions"


def discover_project_config(workspace: Path) -> Dict[str, Any]:
    project_name = workspace.name
    stack = "generic"
    qa = {
        "install_cmd": "",
        "lint_cmd": "",
        "typecheck_cmd": "",
        "unit_test_cmd": "",
        "integration_test_cmd": "",
        "security_scan_cmd": "",
        "build_cmd": "",
    }
    deploy_test_cmd = ""
    deploy_staging_cmd = ""
    deploy_prod_cmd = ""

    pkg_json = workspace / "package.json"
    pyproject = workspace / "pyproject.toml"
    reqs_txt = workspace / "requirements.txt"
    go_mod = workspace / "go.mod"
    cargo_toml = workspace / "Cargo.toml"
    firebase_json = workspace / "firebase.json"

    if pkg_json.exists():
        stack = "node"
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        except Exception:
            pkg = {}
        if pkg.get("name"):
            project_name = str(pkg["name"])
        scripts = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}

        qa["install_cmd"] = "npm ci" if (workspace / "package-lock.json").exists() else "npm install"
        if "lint" in scripts:
            qa["lint_cmd"] = "npm run lint"
        if "typecheck" in scripts:
            qa["typecheck_cmd"] = "npm run typecheck"
        elif "check" in scripts:
            qa["typecheck_cmd"] = "npm run check"
        if "test:unit" in scripts:
            qa["unit_test_cmd"] = "npm run test:unit"
        elif "test" in scripts:
            qa["unit_test_cmd"] = "npm test"
        if "test:integration" in scripts:
            qa["integration_test_cmd"] = "npm run test:integration"
        if "build" in scripts:
            qa["build_cmd"] = "npm run build"
        qa["security_scan_cmd"] = "npm audit --audit-level=high"

        if "deploy:test" in scripts:
            deploy_test_cmd = "npm run deploy:test"
        if "deploy:staging" in scripts:
            deploy_staging_cmd = "npm run deploy:staging"
        if "deploy:prod" in scripts or "deploy:production" in scripts:
            deploy_prod_cmd = "npm run deploy:prod" if "deploy:prod" in scripts else "npm run deploy:production"

    elif pyproject.exists() or reqs_txt.exists() or (workspace / "tests").is_dir():
        stack = "python"
        if reqs_txt.exists():
            qa["install_cmd"] = "pip install -r requirements.txt"
        elif pyproject.exists():
            qa["install_cmd"] = "pip install -e ."
        if shutil.which("ruff"):
            qa["lint_cmd"] = "ruff check ."
        if shutil.which("mypy"):
            qa["typecheck_cmd"] = "mypy ."
        if (workspace / "tests").is_dir():
            qa["unit_test_cmd"] = "python3 -m unittest discover -s tests -v"
        else:
            qa["unit_test_cmd"] = "python3 -m unittest"
        if shutil.which("pip-audit"):
            qa["security_scan_cmd"] = "pip-audit"

    elif go_mod.exists():
        stack = "go"
        qa["install_cmd"] = "go mod download"
        qa["lint_cmd"] = "go vet ./..."
        qa["unit_test_cmd"] = "go test ./..."
        qa["build_cmd"] = "go build ./..."
        if shutil.which("govulncheck"):
            qa["security_scan_cmd"] = "govulncheck ./..."

    elif cargo_toml.exists():
        stack = "rust"
        qa["lint_cmd"] = "cargo clippy"
        qa["unit_test_cmd"] = "cargo test"
        qa["build_cmd"] = "cargo build"

    if firebase_json.exists():
        if not deploy_staging_cmd:
            deploy_staging_cmd = "npx -y firebase-tools@latest hosting:channel:deploy staging"
        if not deploy_prod_cmd:
            deploy_prod_cmd = "npx -y firebase-tools@latest deploy --only hosting"

    env_scan = scan_env_vars_and_secrets(workspace)
    deploy_signals = detect_deploy_signals_and_cloud_readiness(workspace, env_scan)

    return {
        "version": 1,
        "project_name": project_name,
        "stack": stack,
        "execution": {
            "max_parallel_builders": 4,
            "max_task_retries": 3,
            "max_qa_retries": 2,
            "default_approval_mode": "manual",
        },
        "qa": qa,
        "deploy": {
            "default_strategy": "on_param",
            "cloud_target": deploy_signals["recommended_target"],
            "required_secrets": env_scan["secret_vars"],
            "required_env_vars": env_scan["config_vars"],
            "environments": {
                "test": {
                    "command": deploy_test_cmd,
                    "smoke_test_cmd": "",
                },
                "staging": {
                    "command": deploy_staging_cmd,
                    "smoke_test_cmd": "",
                },
                "production": {
                    "command": deploy_prod_cmd,
                    "smoke_test_cmd": "",
                },
            },
        },
    }


def scaffold_missing_deploy_infra(
    workspace: Path, cfg: Dict[str, Any], cloud_target: str, env_scan: Dict[str, List[str]]
) -> List[str]:
    """
    Scaffolds missing deployment files (`Dockerfile`, `.dockerignore`, `firebase.json`, `.env.example`)
    when requested or when setting up CD for a target that requires them.
    """
    scaffolded: List[str] = []
    stack = cfg.get("stack", "generic")

    # 1. Ensure .env.example exists if code uses env vars/secrets
    all_vars = env_scan.get("secret_vars", []) + env_scan.get("config_vars", [])
    env_example = workspace / ".env.example"
    if all_vars and not env_example.exists():
        lines = ["# Generated by Lemmings Squad (lemming-basher) — Required Environment Variables & Secrets"]
        for v in env_scan.get("secret_vars", []):
            lines.append(f"{v}=your_{v.lower()}_here")
        for v in env_scan.get("config_vars", []):
            lines.append(f"{v}=")
        env_example.write_text("\n".join(lines) + "\n", encoding="utf-8")
        scaffolded.append(".env.example")

    # 2. If cloud_target is cloud-run or gke, ensure Dockerfile & .dockerignore exist
    if cloud_target in ("cloud-run", "gke"):
        dockerfile = workspace / "Dockerfile"
        if not dockerfile.exists():
            if stack == "node":
                df_content = """# Generated by Lemmings Squad (lemming-basher)
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev || npm install --omit=dev
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["npm", "start"]
"""
            elif stack == "python":
                df_content = """# Generated by Lemmings Squad (lemming-basher)
FROM python:3.11-slim
WORKDIR /app
COPY requirements*.txt pyproject.toml* ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["python3", "-m", "http.server", "8080"]
"""
            elif stack == "go":
                df_content = """# Generated by Lemmings Squad (lemming-basher)
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /server .

FROM alpine:3.19
COPY --from=builder /server /server
ENV PORT=8080
EXPOSE 8080
CMD ["/server"]
"""
            else:
                df_content = """# Generated by Lemmings Squad (lemming-basher)
FROM ubuntu:24.04
WORKDIR /app
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["echo", "Configure container entrypoint"]
"""
            dockerfile.write_text(df_content, encoding="utf-8")
            scaffolded.append("Dockerfile")

        dockerignore = workspace / ".dockerignore"
        if not dockerignore.exists():
            dockerignore.write_text(
                ".git\nnode_modules\n.venv\n__pycache__\n.lemmings\n.env\n*.md\n",
                encoding="utf-8",
            )
            scaffolded.append(".dockerignore")

    elif cloud_target == "firebase":
        fb_json = workspace / "firebase.json"
        if not fb_json.exists():
            fb_json.write_text(
                json.dumps(
                    {
                        "hosting": {
                            "public": "dist",
                            "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            scaffolded.append("firebase.json")

    return scaffolded


def render_yaml(cfg: Dict[str, Any]) -> str:
    qa = cfg["qa"]
    dep = cfg["deploy"]
    ex = cfg["execution"]
    envs = dep["environments"]
    cloud_target = dep.get("cloud_target", "custom")
    req_secrets = dep.get("required_secrets", [])
    req_vars = dep.get("required_env_vars", [])
    secrets_yaml = json.dumps(req_secrets)
    vars_yaml = json.dumps(req_vars)

    prod_block = ""
    if "production" in envs:
        prod_block = f"""    production:
      command: "{envs['production'].get('command', '')}"
      smoke_test_cmd: "{envs['production'].get('smoke_test_cmd', '')}"
"""
    return f"""version: {cfg['version']}
project_name: "{cfg['project_name']}"

execution:
  max_parallel_builders: {ex['max_parallel_builders']}
  max_task_retries: {ex['max_task_retries']}
  max_qa_retries: {ex['max_qa_retries']}
  default_approval_mode: "{ex['default_approval_mode']}" # manual | auto

qa:
  install_cmd: "{qa['install_cmd']}"
  lint_cmd: "{qa['lint_cmd']}"
  typecheck_cmd: "{qa['typecheck_cmd']}"
  unit_test_cmd: "{qa['unit_test_cmd']}"
  integration_test_cmd: "{qa['integration_test_cmd']}"
  security_scan_cmd: "{qa['security_scan_cmd']}"
  build_cmd: "{qa['build_cmd']}"

deploy:
  default_strategy: "{dep['default_strategy']}" # never | auto | ask | on_param
  cloud_target: "{cloud_target}" # cloud-run | firebase | gke | custom
  required_secrets: {secrets_yaml}
  required_env_vars: {vars_yaml}
  environments:
    test:
      command: "{envs['test']['command']}"
      smoke_test_cmd: "{envs['test']['smoke_test_cmd']}"
    staging:
      command: "{envs['staging']['command']}"
      smoke_test_cmd: "{envs['staging']['smoke_test_cmd']}"
{prod_block}"""


def _github_setup_step(stack: str) -> str:
    if stack == "node":
        return """      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
"""
    if stack == "python":
        return """      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
"""
    if stack == "go":
        return """      - name: Setup Go
        uses: actions/setup-go@v5
        with:
          go-version: "1.22"
"""
    return ""


def generate_github_ci_yaml(cfg: Dict[str, Any]) -> str:
    qa = cfg["qa"]
    stack = cfg.get("stack", "generic")
    setup_step = _github_setup_step(stack)

    fast_steps: List[str] = []
    for label, key in [
        ("Install dependencies", "install_cmd"),
        ("Lint check", "lint_cmd"),
        ("Typecheck", "typecheck_cmd"),
        ("Unit tests", "unit_test_cmd"),
        ("Build project", "build_cmd"),
    ]:
        cmd = qa.get(key, "").strip()
        if cmd:
            fast_steps.append(f"      - name: {label}\n        run: {cmd}")

    if not fast_steps:
        fast_steps.append('      - name: Verify repository\n        run: echo "CI fast checks passed"')

    bomber_steps: List[str] = []
    if qa.get("install_cmd", "").strip():
        bomber_steps.append(f"      - name: Install dependencies\n        run: {qa['install_cmd'].strip()}")
    if qa.get("integration_test_cmd", "").strip():
        bomber_steps.append(f"      - name: Integration tests\n        run: {qa['integration_test_cmd'].strip()}")
    if qa.get("security_scan_cmd", "").strip():
        bomber_steps.append(f"      - name: Security & vulnerability scan\n        run: {qa['security_scan_cmd'].strip()}")
    if not bomber_steps:
        bomber_steps.append('      - name: Full Bomber QA & Security Gate\n        run: echo "Main branch QA & Security verified"')

    fast_block = "\n".join(fast_steps)
    bomber_block = "\n".join(bomber_steps)

    return f"""# Generated & managed by Lemmings Squad (lemming-basher)
name: Lemmings CI

on:
  push:
    branches:
      - "**"
  pull_request:
    branches:
      - main
      - master

jobs:
  fast-ci-check:
    name: "CI Fast Feedback (All Branches & PRs)"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
{setup_step}{fast_block}

  main-bomber-gate:
    name: "Full QA & Security Gate (main post-merge/commit)"
    needs: fast-ci-check
    if: github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master')
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
{setup_step}{bomber_block}
"""


def _build_env_block_for_github(cfg: Dict[str, Any], default_token_secret: str) -> str:
    req_secrets = cfg.get("deploy", {}).get("required_secrets", [])
    lines = [f"          DEPLOY_TOKEN: ${{{{ secrets.{default_token_secret} }}}}"]
    for sec in req_secrets:
        lines.append(f"          {sec}: ${{{{ secrets.{sec} }}}}")
    return "\n".join(lines)


def generate_github_cd_yaml(cfg: Dict[str, Any]) -> str:
    qa = cfg["qa"]
    dep_cfg = cfg["deploy"]
    dep = dep_cfg["environments"]
    cloud_target = dep_cfg.get("cloud_target", "custom")
    stack = cfg.get("stack", "generic")
    setup_step = _github_setup_step(stack)

    install_step = ""
    if qa.get("install_cmd", "").strip():
        install_step = f"      - name: Install dependencies\n        run: {qa['install_cmd'].strip()}\n"

    cloud_auth_step = ""
    if cloud_target in ("cloud-run", "gke"):
        cloud_auth_step = """      - name: Authenticate to Google Cloud (Workload Identity / SA)
        if: env.GCP_WORKLOAD_IDENTITY_PROVIDER != '' || env.GCP_CREDENTIALS != ''
        uses: google-github-actions/auth@v2
        env:
          GCP_WORKLOAD_IDENTITY_PROVIDER: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          GCP_CREDENTIALS: ${{ secrets.GCP_SA_KEY }}
        with:
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}
          credentials_json: ${{ secrets.GCP_SA_KEY }}
"""

    default_stg_cmd = (
        f"gcloud run deploy {cfg['project_name']}-staging --source . --region ${{vars.GCP_REGION || 'us-central1'}} --allow-unauthenticated"
        if cloud_target == "cloud-run"
        else 'echo "Configure deploy.environments.staging.command in .lemmings/config.yaml"'
    )
    default_prod_cmd = (
        f"gcloud run deploy {cfg['project_name']} --source . --region ${{vars.GCP_REGION || 'us-central1'}}"
        if cloud_target == "cloud-run"
        else 'echo "Configure deploy.environments.production.command in .lemmings/config.yaml"'
    )

    stg_cmd = dep.get("staging", {}).get("command", "").strip() or default_stg_cmd
    stg_smoke = dep.get("staging", {}).get("smoke_test_cmd", "").strip()
    stg_smoke_step = f"\n      - name: Smoke Test (Staging)\n        run: {stg_smoke}" if stg_smoke else ""

    prod_cmd = dep.get("production", {}).get("command", "").strip() or default_prod_cmd
    prod_smoke = dep.get("production", {}).get("smoke_test_cmd", "").strip()
    prod_smoke_step = f"\n      - name: Smoke Test (Production)\n        run: {prod_smoke}" if prod_smoke else ""

    stg_env_block = _build_env_block_for_github(cfg, "LEMMINGS_STAGING_DEPLOY_TOKEN")
    prod_env_block = _build_env_block_for_github(cfg, "LEMMINGS_PROD_DEPLOY_TOKEN")

    return f"""# Generated & managed by Lemmings Squad (lemming-basher)
name: Lemmings CD ({cloud_target})

on:
  push:
    branches:
      - main
      - master
    tags:
      - "v*"
  workflow_dispatch:
    inputs:
      target_environment:
        description: "Target environment to deploy (staging or production)"
        required: true
        default: "staging"
        type: choice
        options:
          - staging
          - production

jobs:
  deploy-staging:
    name: "CD: Deploy to Staging / Homolog"
    if: >
      (github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master')) ||
      (github.event_name == 'workflow_dispatch' && inputs.target_environment == 'staging')
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
{setup_step}{cloud_auth_step}{install_step}      - name: Deploy to Staging
        env:
{stg_env_block}
        run: {stg_cmd}{stg_smoke_step}

  deploy-production:
    name: "CD: Deploy to Production"
    if: >
      startsWith(github.ref, 'refs/tags/v') ||
      (github.event_name == 'workflow_dispatch' && inputs.target_environment == 'production')
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
{setup_step}{cloud_auth_step}{install_step}      - name: Deploy to Production
        env:
{prod_env_block}
        run: {prod_cmd}{prod_smoke_step}
"""


def write_or_merge_workflow(target_file: Path, new_content: str, job_marker: str, force: bool = False) -> str:
    """
    Writes a workflow file or incrementally appends Lemmings jobs if a custom workflow already exists.
    Returns 'Created' or 'Incremental Update'.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if not target_file.exists() or force:
        mode = "Incremental Update" if target_file.exists() else "Created"
        target_file.write_text(new_content, encoding="utf-8")
        return mode

    existing = target_file.read_text(encoding="utf-8")
    if "Lemmings Squad (lemming-basher)" in existing or job_marker in existing:
        target_file.write_text(new_content, encoding="utf-8")
        return "Incremental Update"

    jobs_split = new_content.split("\njobs:\n", 1)
    if len(jobs_split) == 2 and "\njobs:" in existing:
        merged = existing.rstrip() + "\n\n  # --- Added incrementally by Lemmings Squad (lemming-basher) ---\n" + jobs_split[1]
        target_file.write_text(merged, encoding="utf-8")
        return "Incremental Update"

    target_file.write_text(new_content, encoding="utf-8")
    return "Incremental Update"


def generate_cicd_pipelines(
    workspace: Path,
    cfg: Dict[str, Any],
    provider: str,
    with_ci: bool,
    with_cd: bool,
    git_readiness: Dict[str, Any],
    force: bool = False,
) -> Tuple[List[Dict[str, str]], str]:
    pipeline_records: List[Dict[str, str]] = []
    overall_mode = "Created"

    if provider == "github-actions":
        wf_dir = workspace / ".github" / "workflows"
        if with_ci:
            ci_file = wf_dir / "ci.yml"
            mode = write_or_merge_workflow(ci_file, generate_github_ci_yaml(cfg), "fast-ci-check", force=force)
            if mode == "Incremental Update":
                overall_mode = "Incremental Update"
            pipeline_records.append(
                {
                    "file": str(ci_file.relative_to(workspace)),
                    "type": "CI (Continuous Integration)",
                    "triggers": "`push` em qualquer branch (`**`), `pull_request` e Gate completo na `main`",
                    "mode": mode,
                }
            )
        if with_cd:
            cd_file = wf_dir / "cd.yml"
            mode = write_or_merge_workflow(cd_file, generate_github_cd_yaml(cfg), "deploy-staging", force=force)
            if mode == "Incremental Update":
                overall_mode = "Incremental Update"
            pipeline_records.append(
                {
                    "file": str(cd_file.relative_to(workspace)),
                    "type": f"CD ({cfg['deploy'].get('cloud_target', 'custom')})",
                    "triggers": "`push` na `main` (Staging), tag `v*` e `workflow_dispatch` (Staging/Prod)",
                    "mode": mode,
                }
            )

    elif provider == "gitlab-ci":
        gl_file = workspace / ".gitlab-ci.yml"
        qa = cfg["qa"]
        dep = cfg["deploy"]["environments"]
        content = f"""# Generated & managed by Lemmings Squad (lemming-basher)
stages:
  - ci_fast
  - bomber_gate
  - deploy_staging
  - deploy_prod

fast_ci_check:
  stage: ci_fast
  script:
    - {qa.get('install_cmd') or 'echo "install"'}
    - {qa.get('lint_cmd') or 'echo "lint"'}
    - {qa.get('unit_test_cmd') or 'echo "unit tests"'}
    - {qa.get('build_cmd') or 'echo "build"'}

main_bomber_gate:
  stage: bomber_gate
  only:
    - main
    - master
  script:
    - {qa.get('integration_test_cmd') or 'echo "integration tests"'}
    - {qa.get('security_scan_cmd') or 'echo "security scan"'}
"""
        if with_cd:
            content += f"""
deploy_staging:
  stage: deploy_staging
  only:
    - main
  script:
    - {dep['staging']['command'] or 'echo "deploy staging"'}
"""
        mode = "Incremental Update" if gl_file.exists() else "Created"
        gl_file.write_text(content, encoding="utf-8")
        overall_mode = mode
        pipeline_records.append(
            {
                "file": ".gitlab-ci.yml",
                "type": "CI + CD" if with_cd else "CI",
                "triggers": "Commits em todas as branches + Gate e Deploy na `main`",
                "mode": mode,
            }
        )

    elif provider == "cloud-build":
        cb_file = workspace / "cloudbuild.yaml"
        qa = cfg["qa"]
        dep = cfg["deploy"]["environments"]
        content = f"""# Generated & managed by Lemmings Squad (lemming-basher)
steps:
  - name: 'ubuntu'
    id: 'fast-ci-check'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        {qa.get('install_cmd') or 'echo "install"'}
        {qa.get('lint_cmd') or 'echo "lint"'}
        {qa.get('unit_test_cmd') or 'echo "unit tests"'}
        {qa.get('build_cmd') or 'echo "build"'}
"""
        if with_cd and dep["staging"]["command"]:
            content += f"""  - name: 'ubuntu'
    id: 'deploy-staging'
    entrypoint: 'bash'
    args: ['-c', '{dep["staging"]["command"]}']
"""
        mode = "Incremental Update" if cb_file.exists() else "Created"
        cb_file.write_text(content, encoding="utf-8")
        overall_mode = mode
        pipeline_records.append(
            {
                "file": "cloudbuild.yaml",
                "type": "Cloud Build CI/CD",
                "triggers": "Triggers de branch e merge na `main` no Google Cloud Build",
                "mode": mode,
            }
        )

    need_local_hooks = (provider == "git-hooks") or (with_ci and not git_readiness.get("has_remote", False))
    if need_local_hooks:
        hooks_dir = workspace / ".githooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        qa = cfg["qa"]
        hook_content = f"""#!/usr/bin/env bash
set -euo pipefail
# Generated by Lemmings Squad (lemming-basher)
echo "==> [lemming-basher] Running local CI checks..."
{qa.get('lint_cmd') or 'true'}
{qa.get('typecheck_cmd') or 'true'}
{qa.get('unit_test_cmd') or 'true'}
"""
        for hook_name, trigger_desc in [
            ("pre-commit", "`git commit` local (Ativo enquanto não há remote ou em paralelo ao CI remoto)"),
            ("pre-push", "`git push` em qualquer branch local"),
        ]:
            hook_file = hooks_dir / hook_name
            mode = "Incremental Update" if hook_file.exists() else "Created"
            hook_file.write_text(hook_content, encoding="utf-8")
            hook_file.chmod(0o755)
            pipeline_records.append(
                {
                    "file": f".githooks/{hook_name}",
                    "type": "Local Git Hook CI (Fallback Local)",
                    "triggers": trigger_desc,
                    "mode": mode,
                }
            )

        git_bin = shutil.which("git")
        if git_readiness.get("git_initialized") and git_bin:
            subprocess.run(
                [git_bin, "config", "core.hooksPath", ".githooks"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
            )
            git_readiness["local_hooks_activated"] = True

    return pipeline_records, overall_mode


def render_cicd_report(
    cfg: Dict[str, Any],
    provider: str,
    with_ci: bool,
    with_cd: bool,
    pipeline_records: List[Dict[str, str]],
    overall_mode: str,
    git_readiness: Dict[str, Any],
    deploy_signals: Dict[str, Any],
    scaffolded_files: List[str],
) -> str:
    qa = cfg["qa"]
    dep_cfg = cfg["deploy"]
    dep = dep_cfg["environments"]
    cloud_target = dep_cfg.get("cloud_target", "custom")
    scope = "CI + CD" if (with_ci and with_cd) else ("CD Only" if with_cd else "CI Only")

    rows = []
    for rec in pipeline_records:
        rows.append(f"| `{rec['file']}` | {rec['type']} (`{rec['mode']}`) | {rec['triggers']} |")
    for sf in scaffolded_files:
        rows.append(f"| `{sf}` | Infra de Deploy Gerada (`Scaffolded`) | Suporte ao deploy em `{cloud_target}` |")
    table_str = "\n".join(rows) if rows else "| *(Nenhum arquivo gerado)* | - | - |"

    secrets_lines = [
        "- [ ] `LEMMINGS_STAGING_DEPLOY_TOKEN` *(Token/credencial de deploy para o ambiente de `staging` / `homolog`)*",
        "- [ ] `LEMMINGS_PROD_DEPLOY_TOKEN` *(Token/credencial de deploy para o ambiente de `production`, protegido por Environment Gate)*",
    ]
    if cloud_target in ("cloud-run", "gke"):
        secrets_lines.append(
            "- [ ] `GCP_WORKLOAD_IDENTITY_PROVIDER` + `GCP_SERVICE_ACCOUNT` *(ou `GCP_SA_KEY` JSON para autenticação no Google Cloud)*"
        )
    if cloud_target == "firebase" or "firebase" in (dep["staging"].get("command", "") + dep["production"].get("command", "")).lower():
        secrets_lines.append("- [ ] `FIREBASE_TOKEN` ou Service Account GCP (`GOOGLE_APPLICATION_CREDENTIALS` / Workload Identity)")

    for sec_var in dep_cfg.get("required_secrets", []):
        secrets_lines.append(f"- [ ] `{sec_var}` *(Detectada automaticamente no código-fonte / `.env.example` da aplicação)*")

    secrets_str = "\n".join(secrets_lines)
    config_vars_list = dep_cfg.get("required_env_vars", [])
    config_vars_str = ", ".join(f"`{v}`" for v in config_vars_list) if config_vars_list else "*(Nenhuma variável adicional detectada)*"

    git_init_status = (
        "Inicializado automaticamente pelo `lemming-basher` (`git init -b main`)"
        if git_readiness.get("git_auto_initialized")
        else ("Já inicializado" if git_readiness.get("git_initialized") else "Não inicializado")
    )
    remote_status = (
        f"Conectado (`{git_readiness.get('remote_url')}`)"
        if git_readiness.get("has_remote")
        else "Nenhum repositório remoto (`origin`) configurado ainda"
    )
    gh_status = (
        "Autenticado (`gh auth status` OK)"
        if git_readiness.get("gh_authenticated")
        else ("Instalado, porém **não autenticado**" if git_readiness.get("gh_installed") else "Não instalado / Sem credenciais locais")
    )
    hooks_note = (
        "Ativados automaticamente (`git config core.hooksPath .githooks`) para garantir CI imediato nos commits locais enquanto o repositório remoto não estiver conectado."
        if git_readiness.get("local_hooks_activated")
        else "Disponíveis em `.githooks/`"
    )

    preflight = deploy_signals.get("cloud_preflight", {})
    gcloud_note = (
        f"Autenticado (`{preflight.get('gcloud_account')}`, projeto: `{preflight.get('gcloud_project') or 'não definido'}`)"
        if preflight.get("gcloud_authenticated")
        else ("Instalado, porém **não autenticado** (`gcloud auth login` pendente)" if preflight.get("gcloud_installed") else "Não instalado localmente")
    )

    onboarding_block = ""
    if not git_readiness.get("has_remote") or not git_readiness.get("gh_authenticated"):
        onboarding_block = f"""
### Guia Passo a Passo: Como Conectar ao GitHub Quando Tiver as Credenciais

Os arquivos de workflow (`.github/workflows/*.yml`) já estão prontos no seu projeto. Enquanto você não configurar sua conta/credenciais do GitHub, os **Git Hooks locais (`.githooks/pre-commit` e `.githooks/pre-push`)** já rodam a validação de CI localmente na sua máquina!

Quando quiser ativar a esteira na nuvem do GitHub, escolha uma das opções abaixo:

#### Opção A — Via GitHub CLI (`gh`) (Recomendado)
```bash
# 1. Autenticar sua conta no GitHub CLI
gh auth login

# 2. Criar o repositório no GitHub e enviar a branch main
git add .
git commit -m "chore: configure Lemmings Squad CI/CD pipeline"
gh repo create {cfg['project_name']} --source=. --private --push
```

#### Opção B — Via URL SSH ou HTTPS Manual
```bash
git add .
git commit -m "chore: configure Lemmings Squad CI/CD pipeline"
git remote add origin https://github.com/<seu-usuario-ou-org>/{cfg['project_name']}.git
git push -u origin main
```
"""

    return f"""# Relatório de Pipeline CI/CD (`cicd-pipeline-report.md`)

- **Projeto:** `{cfg['project_name']}`
- **Agente Construtor:** `lemming-basher`
- **Provedor de CI/CD:** `{provider}`
- **Destino de Nuvem (`cloud_target`):** `{cloud_target}` (Confiança de Deploy: `{deploy_signals.get('confidence', 'none')}`)
- **Escopo Configurado:** `{scope}`
- **Modo de Atualização:** `{overall_mode}`
- **Timestamp:** `{now_iso()}`

---

## 1. Arquitetura da Esteira CI/CD

```mermaid
flowchart LR
    Commit["Novo Commit / Push\\n(Qualquer Branch ou PR)"] --> FastCI["CI: Fast Feedback\\n(Install, Lint, Typecheck, Unit Tests, Build)"]
    MergeMain["Commit ou Merge\\nna Branch Principal (main)"] --> FastCI
    FastCI -->|Se branch == main| FullQA["CI: Full Bomber Gate\\n(Integration Tests + Security Scan)"]
    FullQA -->|Se CD habilitado| DeployStaging["CD: Deploy Staging/Homolog ({cloud_target})\\n+ Smoke Test Healthcheck"]
    DeployStaging -->|Tag v* ou Aprovação Manual| DeployProd["CD: Deploy Production ({cloud_target})\\n+ Smoke Test Healthcheck"]
```

---

## 2. Arquivos de Pipeline e Infraestrutura Gerados / Atualizados

| Arquivo | Tipo | Gatilhos / Finalidade |
| :--- | :--- | :--- |
{table_str}

---

## 3. Comandos Sincronizados com `.lemmings/config.yaml`

### Etapa de CI (Espelho do `lemming-bomber`)
- **Install:** `{qa.get('install_cmd') or 'N/A'}`
- **Lint:** `{qa.get('lint_cmd') or 'N/A'}`
- **Typecheck:** `{qa.get('typecheck_cmd') or 'N/A'}`
- **Unit Tests:** `{qa.get('unit_test_cmd') or 'N/A'}`
- **Build:** `{qa.get('build_cmd') or 'N/A'}`
- **Integration Tests (`main`):** `{qa.get('integration_test_cmd') or 'N/A'}`
- **Security Scan (`main`):** `{qa.get('security_scan_cmd') or 'N/A'}`

### Etapa de CD (Sincronizada com `lemming-floater`)
- **Destino de Nuvem (`cloud_target`):** `{cloud_target}`
- **Ambiente `test`:** `{dep['test'].get('command') or 'N/A'}` (Smoke Test: `{dep['test'].get('smoke_test_cmd') or 'N/A'}`)
- **Ambiente `staging`:** `{dep['staging'].get('command') or 'N/A'}` (Smoke Test: `{dep['staging'].get('smoke_test_cmd') or 'N/A'}`)
- **Ambiente `production` (Somente via Pipeline CD com Gate):** `{dep.get('production', {}).get('command') or 'N/A'}`

---

## 4. Checklist de Secrets, API Keys e Variáveis Detectadas no Código

> [!IMPORTANT]
> O `lemming-basher` escaneou o código-fonte do repositório e injetou automaticamente as Secrets abaixo no pipeline de CD. Cadastre-as nas configurações do seu provedor de Git/Cloud:

{secrets_str}

- **Variáveis de Configuração Não-Sensíveis Detectadas:** {config_vars_str}

---

## 5. Diagnóstico de Prontidão Git, GitHub e Cloud (`Pre-Flight`)

- **Indícios de Deploy no Projeto:** Confiança `{deploy_signals.get('confidence')}` (Infra: `{deploy_signals.get('infra_artifacts')}`, App: `{deploy_signals.get('app_signals')}`)
- **Repositório Git Local (`.git`):** {git_init_status}
- **Repositório Remoto (`origin`):** {remote_status}
- **Credenciais GitHub CLI (`gh`):** {gh_status}
- **Google Cloud CLI (`gcloud`):** {gcloud_note}
- **Fallback de CI Local (`.githooks`):** {hooks_note}
{onboarding_block}"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize .lemmings/ configuration and CI/CD pipelines in a repository")
    parser.add_argument("--workspace", required=True, help="Target repository root")
    parser.add_argument("--force", action="store_true", help="Overwrite existing config/workflow files")
    parser.add_argument(
        "--with-templates",
        action="store_true",
        help="Copy customizable Markdown templates into .lemmings/templates/",
    )
    parser.add_argument("--with-ci", action="store_true", help="Generate/update Continuous Integration (CI) pipeline via lemming-basher")
    parser.add_argument("--with-cd", action="store_true", help="Generate/update Continuous Delivery/Deployment (CD) pipeline via lemming-basher")
    parser.add_argument(
        "--ci-provider",
        default="auto",
        choices=["auto", "github", "github-actions", "gitlab", "gitlab-ci", "cloudbuild", "cloud-build", "githooks", "git-hooks"],
        help="CI/CD platform provider (default: auto-detect from git remote)",
    )
    parser.add_argument(
        "--cloud-target",
        default="auto",
        choices=["auto", "cloud-run", "firebase", "gke", "custom"],
        help="Target cloud platform for CD (default: auto-detect from project signals)",
    )
    parser.add_argument(
        "--scaffold-infra",
        action="store_true",
        help="Automatically scaffold missing Dockerfile, .dockerignore, firebase.json, or .env.example",
    )
    parser.add_argument("--no-git-init", action="store_true", help="Do not automatically run git init if .git is missing")
    parser.add_argument("--deploy-test-cmd", default=None, help="Override deploy.environments.test.command")
    parser.add_argument("--deploy-staging-cmd", default=None, help="Override deploy.environments.staging.command")
    parser.add_argument("--deploy-prod-cmd", default=None, help="Override deploy.environments.production.command")
    parser.add_argument("--smoke-test-cmd", default=None, help="Override deploy.environments.test.smoke_test_cmd")
    parser.add_argument("--smoke-staging-cmd", default=None, help="Override deploy.environments.staging.smoke_test_cmd")
    parser.add_argument("--smoke-prod-cmd", default=None, help="Override deploy.environments.production.smoke_test_cmd")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(json.dumps({"ok": False, "error": f"Workspace not found: {workspace}"}), file=sys.stderr)
        return 1

    git_readiness = check_and_prepare_git_readiness(workspace, auto_init_git=not args.no_git_init)
    env_scan = scan_env_vars_and_secrets(workspace)
    deploy_signals = detect_deploy_signals_and_cloud_readiness(workspace, env_scan)

    lemmings_dir = workspace / ".lemmings"
    runs_dir = lemmings_dir / "runs"
    inbox_dir = lemmings_dir / "inbox"
    runs_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir.mkdir(parents=True, exist_ok=True)

    json_path = lemmings_dir / "config.json"
    yaml_path = lemmings_dir / "config.yaml"

    if json_path.exists() and not args.force:
        try:
            cfg = json.loads(json_path.read_text(encoding="utf-8"))
            discovered = discover_project_config(workspace)
            cfg.setdefault("stack", discovered.get("stack", "generic"))
            cfg.setdefault("deploy", {}).setdefault("environments", {}).setdefault(
                "production", {"command": "", "smoke_test_cmd": ""}
            )
            cfg["deploy"]["required_secrets"] = env_scan["secret_vars"]
            cfg["deploy"]["required_env_vars"] = env_scan["config_vars"]
            cfg["deploy"].setdefault("cloud_target", deploy_signals["recommended_target"])
        except Exception:
            cfg = discover_project_config(workspace)
    else:
        cfg = discover_project_config(workspace)

    if args.cloud_target and args.cloud_target != "auto":
        cfg["deploy"]["cloud_target"] = args.cloud_target

    envs = cfg["deploy"]["environments"]
    if args.deploy_test_cmd is not None:
        envs["test"]["command"] = args.deploy_test_cmd
    if args.deploy_staging_cmd is not None:
        envs["staging"]["command"] = args.deploy_staging_cmd
    if args.deploy_prod_cmd is not None:
        envs.setdefault("production", {"command": "", "smoke_test_cmd": ""})["command"] = args.deploy_prod_cmd
    if args.smoke_test_cmd is not None:
        envs["test"]["smoke_test_cmd"] = args.smoke_test_cmd
    if args.smoke_staging_cmd is not None:
        envs["staging"]["smoke_test_cmd"] = args.smoke_staging_cmd
    if args.smoke_prod_cmd is not None:
        envs.setdefault("production", {"command": "", "smoke_test_cmd": ""})["smoke_test_cmd"] = args.smoke_prod_cmd

    created_files: List[str] = []
    scaffolded_files: List[str] = []
    if args.scaffold_infra or args.with_cd:
        scaffolded_files = scaffold_missing_deploy_infra(
            workspace=workspace,
            cfg=cfg,
            cloud_target=cfg["deploy"].get("cloud_target", "custom"),
            env_scan=env_scan,
        )
        for sf in scaffolded_files:
            if sf not in created_files:
                created_files.append(sf)

    has_cd_overrides = any(
        v is not None
        for v in (
            args.deploy_test_cmd,
            args.deploy_staging_cmd,
            args.deploy_prod_cmd,
            args.smoke_test_cmd,
            args.smoke_staging_cmd,
            args.smoke_prod_cmd,
        )
    ) or (args.cloud_target != "auto")

    if not yaml_path.exists() or args.force or has_cd_overrides or args.with_cd:
        yaml_path.write_text(render_yaml(cfg), encoding="utf-8")
        created_files.append(str(yaml_path.relative_to(workspace)))

    if not json_path.exists() or args.force or has_cd_overrides or args.with_cd:
        json_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        created_files.append(str(json_path.relative_to(workspace)))

    if args.with_templates:
        dest_tpl = lemmings_dir / "templates"
        dest_tpl.mkdir(parents=True, exist_ok=True)
        script_dir = Path(__file__).resolve().parent
        candidate_dirs = [
            script_dir.parent.parent / "lemmings-orchestrate" / "resources" / "templates",
            script_dir.parent.parent.parent.parent / "templates",
        ]
        for cdir in candidate_dirs:
            if cdir.is_dir():
                for item in sorted(cdir.glob("*.template.*")):
                    target = dest_tpl / item.name
                    if not target.exists() or args.force:
                        shutil.copy2(item, target)
                        created_files.append(str(target.relative_to(workspace)))
                break

    provider = detect_ci_provider(workspace, args.ci_provider)
    pipeline_records: List[Dict[str, str]] = []
    cicd_report_rel: str | None = None

    if args.with_ci or args.with_cd:
        with_ci_flag = True if (args.with_ci or args.with_cd) else False
        pipeline_records, overall_mode = generate_cicd_pipelines(
            workspace=workspace,
            cfg=cfg,
            provider=provider,
            with_ci=with_ci_flag,
            with_cd=bool(args.with_cd),
            git_readiness=git_readiness,
            force=bool(args.force),
        )
        for rec in pipeline_records:
            if rec["file"] not in created_files:
                created_files.append(rec["file"])

        report_path = lemmings_dir / "cicd-pipeline-report.md"
        report_md = render_cicd_report(
            cfg=cfg,
            provider=provider,
            with_ci=with_ci_flag,
            with_cd=bool(args.with_cd),
            pipeline_records=pipeline_records,
            overall_mode=overall_mode,
            git_readiness=git_readiness,
            deploy_signals=deploy_signals,
            scaffolded_files=scaffolded_files,
        )
        report_path.write_text(report_md, encoding="utf-8")
        cicd_report_rel = str(report_path.relative_to(workspace))
        created_files.append(cicd_report_rel)

    print(
        json.dumps(
            {
                "ok": True,
                "workspace": str(workspace),
                "project_name": cfg["project_name"],
                "stack": cfg.get("stack", "generic"),
                "ci_provider": provider,
                "git_readiness": git_readiness,
                "deploy_signals": deploy_signals,
                "scaffolded_files": scaffolded_files,
                "created_files": created_files,
                "pipelines": pipeline_records,
                "cicd_report": cicd_report_rel,
                "discovered_qa": cfg["qa"],
                "discovered_deploy": cfg["deploy"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
