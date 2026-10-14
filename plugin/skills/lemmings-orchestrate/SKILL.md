---
name: lemmings-orchestrate
description: >-
  Orchestrate the Lemmings Squad multi-agent software development lifecycle.
  Use this skill whenever the user asks to run Lemmings, invoke the Commander/Tech-Lead,
  approves an implementation plan ("aprovado", "pode seguir", "continuar"), or provides
  a software specification (feature, bugfix, refactoring).
---

# Lemmings Squad — Orchestration Skill (`lemmings-orchestrate`)

Use this skill to execute or resume the **Lemmings Squad** workflow in the active workspace.
**IMPORTANT UX RULE:** The user only interacts using natural phrases (e.g., *"Use o Lemmings na spec X"*, *"Aprovado"*, *"Pode continuar"*). You must handle all file naming (`00`..`08`) and helper script calls (`state_manager.py`, `verify_wave.py`, `run_bomber_checks.py`) **automatically behind the scenes** without ever requiring the user to mention them.

---

## Automatic State Machine & Resume Detection (Check This First!)

Whenever invoked, first check if `<workspace_root>/.lemmings/runs/` already has an active run directory. Read its `00-run-status.json` to decide which stage to execute automatically:

| `current_step` in `00-run-status.json` | User Intent / Trigger | Action to Execute Automatically |
| :--- | :--- | :--- |
| *(No active run yet)* | User gives a spec or feature request | Run **Stage 1** (`Step 1` $\rightarrow$ `Step 4`): Create `00-run-status.json`, dispatch `lemming-scout` (`01-scout-report.md`), write `02-implementation-plan.md`, and ask for approval. |
| `02_WAITING_PLAN_APPROVAL` or `02_PLAN_APPROVED` | User says *"Aprovado"*, *"Pode seguir"*, *"Continue"*, or clicks Approve | Mark `02-implementation-plan.md` as `APPROVED`, run **Stage 2** (`Step 5` $\rightarrow$ `Step 6`: generate `03-backlog.json` & `03-backlog.md`), and immediately continue into **Stages 3, 4, 5 & 6** (`Step 7` $\rightarrow$ `Step 13`). |
| `03_BACKLOG_READY` or `04_WAVE_*` | User says *"Pode seguir"*, *"Continue"*, *"Executar"* | Run **Stages 3 & 4** (`Step 7` $\rightarrow$ `Step 9`) across all waves until `ALL_WAVES_VERIFIED`, then automatically run **Stages 5 & 6** (`Step 10` $\rightarrow$ `Step 13`). |
| `05_ALL_WAVES_VERIFIED` or `06_QA_FAILED_*` | User says *"Pode seguir"*, *"Continue"*, *"Rodar QA"* | Run **Stage 5** (`Step 10` $\rightarrow$ `Step 11`): Dispatch `lemming-bomber` (`06-bomber-qa-security-attempt-<A>.md`) with Hotfix Wave auto-healing if needed, then proceed to **Stage 6** (`Step 12` $\rightarrow$ `Step 13`). |
| `06_QA_SECURITY_PASSED` or `07_DEPLOY_*` | User says *"Pode seguir"*, *"Continue"*, *"Deploy"*, *"Finalizar"* | Run **Stage 6** (`Step 12` $\rightarrow$ `Step 13`): Dispatch `lemming-floater` (`07-floater-deploy-<env>.md`) and finalize the run (`08-final-summary.md`). |

---

## MANDATORY RULE: File-First Output Standard

**NEVER return outputs only on the chat screen or only inside internal brain artifacts.**
Every step and subagent MUST persist its output as physical, step-numbered files inside `<workspace_root>/.lemmings/runs/<run-id>/`:

| Step Prefix | File Name Pattern in `.lemmings/runs/<run-id>/` | Producer | Cardinality |
| :--- | :--- | :--- | :--- |
| **`00`** | `00-run-status.json` | `lemming-commander` / `state_manager.py` | 1 per run (updated at every step transition) |
| **`01`** | `01-scout-report.md` *(or `01-scout-report-<scope>.md`)* | `lemming-scout` | $1..N$ per run |
| **`02`** | `02-implementation-plan.md` | `lemming-commander` | 1 per run |
| **`03`** | `03-backlog.json` & `03-backlog.md` | `lemming-commander` + `state_manager.py` | 1 pair per run |
| **`04`** | `04-wave-<W>-builder-<TASK_ID>.md` | `lemming-builder` | 1 per task/wave |
| **`05`** | `05-wave-<W>-inspector-attempt-<A>.md` | `lemming-inspector` | 1 per wave validation attempt |
| **`06`** | `06-bomber-qa-security-attempt-<A>.md` | `lemming-bomber` | $1..N$ per run |
| **`07`** | `07-floater-deploy-<env>.md` | `lemming-floater` | 1 per run |
| **`08`** | `08-final-summary.md` | `lemming-commander` + `state_manager.py` | 1 per run |

---

## Stage 1: Discovery, Planning & Approval (`00`, `01`, `02`)

### Step 1: Initialize Run Directory & Write `00-run-status.json`
1. Determine the active workspace root directory (`<workspace_root>`).
2. Generate `<run-id>` in the format `<YYYYMMDD>-<slug>` (e.g., `20260930-auth-refactor`).
3. Run `state_manager.py init-run` via `run_command`:
   ```bash
   python3 ~/.gemini/config/plugins/lemmings-squad/skills/lemmings-orchestrate/scripts/state_manager.py init-run \
     --workspace "<workspace_root>" \
     --run-id "<run-id>" \
     --spec "<relative_path_to_spec>"
   ```

### Step 2: Dispatch Reconnaissance via `lemming-scout` (Writes `01-scout-report*.md`)
1. Call `invoke_subagent` with `TypeName: "lemming-scout"` and `Workspace: "inherit"`.
   - Explicitly instruct `lemming-scout` to write `<workspace_root>/.lemmings/runs/<run-id>/01-scout-report.md` using `write_to_file` before finishing.
2. Wait for `lemming-scout` to finish and verify via `view_file` that `<workspace_root>/.lemmings/runs/<run-id>/01-scout-report*.md` exists on disk.

### Step 3: Write `02-implementation-plan.md` & Update `00-run-status.json`
1. Read `<workspace_root>/.lemmings/runs/<run-id>/01-scout-report*.md`.
2. Call `write_to_file` (`Overwrite: true`) to create `<workspace_root>/.lemmings/runs/<run-id>/02-implementation-plan.md`.
3. Update `<workspace_root>/.lemmings/runs/<run-id>/00-run-status.json` setting `"current_step": "02_WAITING_PLAN_APPROVAL"` and `"status": "WAITING_APPROVAL"`.

### Step 4: Request Plan Approval (Human Gate)
1. Show a concise summary with clickable `file://` links to `00-run-status.json`, `01-scout-report.md`, and `02-implementation-plan.md`.
2. Unless `auto_approve: true` was set, call `ask_question`:
   - `(Recommended) Aprovar o plano e iniciar a execução`
   - `Solicitar ajustes no plano antes de aprovar`
   - `Pausar por enquanto`
3. As soon as the user approves, update `status: "APPROVED"` in `02-implementation-plan.md` and **automatically execute Stage 2, Stage 3, Stage 4, Stage 5, and Stage 6**.

---

## Stage 2: Backlog DAG, Waves & Planned Tests (`03-backlog.json` & `03-backlog.md`)

### Step 5: Write `<workspace_root>/.lemmings/runs/<run-id>/03-backlog.json`
Call `write_to_file` (`Overwrite: true`) to create `<workspace_root>/.lemmings/runs/<run-id>/03-backlog.json` containing `run_id`, `step: "03-backlog"`, `spec_path`, `plan_path`, `status: "READY"`, `config`, and `waves[]`.

### Step 6: Validate Backlog DAG & Auto-Render `03-backlog.md`
Automatically run `state_manager.py validate-backlog` via `run_command`:
```bash
python3 ~/.gemini/config/plugins/lemmings-squad/skills/lemmings-orchestrate/scripts/state_manager.py validate-backlog \
  --run-dir "<workspace_root>/.lemmings/runs/<run-id>"
```

---

## Stages 3 & 4: Parallel Wave Implementation (`lemming-builder`) & Zero-Trust Validation Loop (`lemming-inspector`)

Execute the following Wave Loop until `next-wave` returns `"status": "ALL_WAVES_VERIFIED"` or `"status": "HALTED"`:

### Step 7: Query Next Wave & Dispatch Parallel `lemming-builder` Subagents
1. Run `state_manager.py next-wave`:
   ```bash
   python3 ~/.gemini/config/plugins/lemmings-squad/skills/lemmings-orchestrate/scripts/state_manager.py next-wave \
     --run-dir "<workspace_root>/.lemmings/runs/<run-id>"
   ```
2. If `"status": "WAVE_READY"`:
   - Launch **ALL tasks in `executable_tasks` concurrently in a SINGLE `invoke_subagent` call** (`TypeName: "lemming-builder"`, `Workspace: <isolation_mode>`).
   - Wait for all `lemming-builder` subagents in Wave $W$ to complete, merge worktrees if `isolation_mode == "share"`, and verify that every task in Wave $W$ has its `04-wave-<W>-builder-<TASK-ID>.md` file on disk and status `DEV_DONE`.

### Step 8: Dispatch `lemming-inspector` (Zero-Trust Wave Gate -> `05-wave-<W>-inspector-attempt-<A>.md`)
Once all tasks in Wave $W$ are `DEV_DONE`:
1. Call `invoke_subagent` with `TypeName: "lemming-inspector"` and `Workspace: "inherit"`.
   - Instruct `lemming-inspector` to run `verify_wave.py`, inspect code/wiring/tests, write `<workspace_root>/.lemmings/runs/<run-id>/05-wave-<W>-inspector-attempt-<A>.md`, update each task via `state_manager.py update-task` (`VERIFIED` or `FAILED_VALIDATION`), and run `state_manager.py check-wave-gate`.
2. Wait for `lemming-inspector` to complete.

### Step 9: Evaluate Wave Gate (`PASSED` vs `RETRY_REQUIRED` vs `CIRCUIT_BREAKER`)
- **`"gate": "PASSED"`:** Loop back to **Step 7** (`next-wave`) to start Wave $W+1$ (or proceed to **Stage 5 (Step 10)** when `"ALL_WAVES_VERIFIED"`).
- **`"gate": "RETRY_REQUIRED"`:** Loop back to **Step 7** (`next-wave`) to re-dispatch `lemming-builder` only for the `FAILED_VALIDATION` tasks of Wave $W$.
- **`"gate": "CIRCUIT_BREAKER"`:** Stop execution and notify the user.

---

## Stage 5: Full Repository QA, Security Vulnerability Scan & Auto-Healing (`lemming-bomber`)

When all backlog waves are `VERIFIED` (`"status": "ALL_WAVES_VERIFIED"`):

### Step 10: Dispatch `lemming-bomber` (`06-bomber-qa-security-attempt-<A>.md`)
1. Determine the QA attempt number $A$ (`qa_attempts + 1`, starting at `1`).
2. Call `invoke_subagent` with `TypeName: "lemming-bomber"` and `Workspace: "inherit"`:
   - Pass `<workspace_root>`, `<run-id>`, QA attempt `<A>`, and target report path `<workspace_root>/.lemmings/runs/<run-id>/06-bomber-qa-security-attempt-<A>.md`.
   - Instruct `lemming-bomber` to:
     1. Run `run_bomber_checks.py --workspace "<workspace_root>" --run-dir "<workspace_root>/.lemmings/runs/<run-id>"`.
     2. Perform semantic OWASP Top 10 / CWE security review and regression checks across all touched files.
     3. Write `<workspace_root>/.lemmings/runs/<run-id>/06-bomber-qa-security-attempt-<A>.md`.
     4. Run `state_manager.py record-qa --run-dir "<workspace_root>/.lemmings/runs/<run-id>" --verdict <PASSED|FAILED> --report ".lemmings/runs/<run-id>/06-bomber-qa-security-attempt-<A>.md" --summary "..."`.
3. Wait for `lemming-bomber` to complete and verify that `06-bomber-qa-security-attempt-<A>.md` exists on disk.

### Step 11: Evaluate Bomber Verdict & Auto-Healing (`Hotfix Wave`)
Inspect the `action` returned by `state_manager.py record-qa`:
- **`"action": "PROCEED_TO_DEPLOY_OR_FINISH"` (`verdict: "PASSED"`):**
  - Proceed immediately to **Stage 6 (Step 12 & Step 13)**.
- **`"action": "CREATE_HOTFIX_WAVE"` (`verdict: "FAILED"`, `qa_attempt <= max_qa_retries`):**
  - Automatically create a corrective **Hotfix Wave** using `state_manager.py add-hotfix-wave`:
    ```bash
    python3 ~/.gemini/config/plugins/lemmings-squad/skills/lemmings-orchestrate/scripts/state_manager.py add-hotfix-wave \
      --run-dir "<workspace_root>/.lemmings/runs/<run-id>" \
      --tasks-json '[{"id": "TASK-HF<A>", "title": "<Hotfix Title>", "description": "<Exact fix for QA/security failure>", "target_files": ["..."], "test_files": ["..."], "acceptance_criteria": ["..."], "verification_cmd": "..."}]'
    ```
  - Immediately loop back to **Step 7** (`next-wave`) to run `lemming-builder` + `lemming-inspector` on the Hotfix Wave, and then re-run **Step 10** (`lemming-bomber`)!
- **`"action": "CIRCUIT_BREAKER"` (`qa_attempt > max_qa_retries`):**
  - Stop execution and notify the user with the link to `06-bomber-qa-security-attempt-<A>.md`.

---

## Stage 6: Conditional Staging/Test Deployment (`lemming-floater`) & Final Consolidated Summary (`08-final-summary.md`)

When `lemming-bomber` passes (`06_QA_SECURITY_PASSED`):

### Step 12: Dispatch `lemming-floater` (`07-floater-deploy-<env>.md`)
1. Call `invoke_subagent` with `TypeName: "lemming-floater"` and `Workspace: "inherit"`:
   - Pass `<workspace_root>`, `<run-id>`, and target `deploy_target` (`none`, `test`, `staging`, `homolog`).
   - Instruct `lemming-floater` to evaluate the deployment policy, execute the deploy + smoke test if configured (or mark `SKIPPED` if policy is `never`/`on_param` with `none`), write `<workspace_root>/.lemmings/runs/<run-id>/07-floater-deploy-<env>.md`, and run `state_manager.py record-deploy`.
2. Wait for `lemming-floater` to complete and verify that `07-floater-deploy-<env>.md` exists on disk.

### Step 13: Finalize Run & Generate `08-final-summary.md`
1. Run `state_manager.py finalize-run` via `run_command` to generate `<workspace_root>/.lemmings/runs/<run-id>/08-final-summary.md` and mark `00-run-status.json` as `"status": "COMPLETED"`, `"current_step": "08_COMPLETED"`:
   ```bash
   python3 ~/.gemini/config/plugins/lemmings-squad/skills/lemmings-orchestrate/scripts/state_manager.py finalize-run \
     --run-dir "<workspace_root>/.lemmings/runs/<run-id>" \
     --summary "<Resumo executivo das entregas, cobertura de testes, veredito de segurança e deploy>" \
     --overwrite-summary
   ```
2. Present a final summary to the user with clickable `file://` links to `08-final-summary.md`, `07-floater-deploy-<env>.md`, `06-bomber-qa-security-attempt-<A>.md`, `03-backlog.md`, and `00-run-status.json`.

