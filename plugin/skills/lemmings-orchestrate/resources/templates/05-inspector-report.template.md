---
run_id: "{{RUN_ID}}"
step: "05-inspector-report"
wave_number: {{WAVE_NUMBER}}
attempt: {{ATTEMPT_NUMBER}}
wave_verdict: "{{WAVE_VERDICT}}" # PASSED | RETRY_REQUIRED | CIRCUIT_BREAKER
audited_at: "{{AUDITED_AT}}"
---

# Relatório de Validação Zero-Trust (Inspector Report) — Wave {{WAVE_NUMBER}} (Tentativa {{ATTEMPT_NUMBER}})

## 1. Resumo do Gate de Validação da Onda
- **Veredito da Onda {{WAVE_NUMBER}}:** `{{WAVE_VERDICT}}`
- **Tasks Aprovadas (`VERIFIED`):** {{VERIFIED_COUNT}}
- **Tasks Reprovadas (`FAILED_VALIDATION` / `HALTED`):** {{FAILED_COUNT}}

## 2. Tabela de Auditoria por Task
| Task ID | Título | Existência/Diff OK? | Anti-Patterns (`TODO`/Stubs)? | Teste Independente (`verification_cmd`) | Critérios de Aceite & Wiring | Veredito Final |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{{TASK_AUDIT_ROWS}}

---

## 3. Detalhamento Técnico e Feedback Acionável por Task

{{TASK_DETAILED_VERDICTS}}
