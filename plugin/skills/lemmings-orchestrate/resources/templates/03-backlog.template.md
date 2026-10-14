---
run_id: "{{RUN_ID}}"
step: "03-backlog"
source_plan: ".lemmings/runs/{{RUN_ID}}/02-implementation-plan.md"
backlog_json: ".lemmings/runs/{{RUN_ID}}/03-backlog.json"
status: "READY" # READY | IN_PROGRESS | ALL_VERIFIED | QA_PASSED | COMPLETED | HALTED
updated_at: "{{UPDATED_AT}}"
---

# Backlog de Execução em Ondas (DAG): {{TITLE}}

> Este arquivo é sincronizado com [`03-backlog.json`](./03-backlog.json) e reflete o estado real das tasks, ondas de paralelismo e testes planejados.

## 1. Resumo de Ondas e Isolamento

| Onda (`Wave`) | Título | Modo de Isolamento (`Workspace`) | Colisão de Arquivos? | Total de Tasks | Status da Onda |
| :--- | :--- | :--- | :--- | :--- | :--- |
{{WAVES_SUMMARY_ROWS}}

---

## 2. Matriz de Tasks, Critérios de Aceite e Testes Planejados

{{WAVES_DETAILED_SECTIONS}}
