---
trigger: model_decision
description: "Use these rules whenever the user mentions Lemmings, Commander, approves a plan ('aprovado', 'pode seguir', 'continue'), or works in a repository containing a .lemmings/ directory."
---

# Lemmings Squad — Zero-Friction UX, File Ownership & State Machine Protocol

1. **Zero Technical Boilerplate for the User:**
   - The user must NEVER be asked or expected to know internal script names (`state_manager.py`), internal step prefixes (`00-`..`08-`), or CLI flags.
   - Simple natural commands from the user such as *"Rode o Lemmings nessa spec"*, *"Aprovado"*, *"Pode seguir"*, or *"Continue o Lemmings"* are sufficient to trigger and advance the entire workflow.
2. **Automatic State Detection & Skill Reload:**
   - Whenever the user approves a plan or asks to continue a run, ALWAYS read the latest `lemmings-orchestrate` skill (`SKILL.md`) first, check `<workspace_root>/.lemmings/runs/` for the active `<run-id>`, inspect `00-run-status.json`, and automatically execute the next stage of the state machine.
3. **File-First Output Standard:**
   - Every stage and subagent must write its standardized files inside `<workspace_root>/.lemmings/runs/<run-id>/` (`00-run-status.json`, `01-scout-report.md`, `02-implementation-plan.md`, `03-backlog.json`, `03-backlog.md`, `04-wave-<W>-builder-<TASK-ID>.md`, etc.) automatically behind the scenes.
4. **Strict Parallel File Ownership (`target_files` & `test_files`):**
   - Each `lemming-builder` subagent may ONLY create or edit files listed in its assigned task's `target_files` and `test_files`, plus its own `04-wave-<W>-builder-<TASK-ID>.md` report.
   - Subagents must NEVER directly overwrite `03-backlog.json` or `00-run-status.json` using file-edit tools during parallel waves; all task status updates must go through `state_manager.py update-task` (which uses `fcntl.flock` atomic locking).
5. **Status Governance (`DEV_DONE` vs `VERIFIED`):**
   - `lemming-builder` may only set task status to `IN_PROGRESS` or `DEV_DONE`.
   - Only `lemming-inspector` (or the Commander Wave Gate during Stage 3 testing) may transition a task from `DEV_DONE` to `VERIFIED`.
