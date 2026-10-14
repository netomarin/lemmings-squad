---
run_id: "{{RUN_ID}}"
step: "06-bomber-qa-security-report"
qa_attempt: {{QA_ATTEMPT}}
verdict: "{{VERDICT}}" # PASSED | FAILED
action: "{{ACTION}}" # PROCEED_TO_DEPLOY_OR_FINISH | CREATE_HOTFIX_WAVE | CIRCUIT_BREAKER
executed_at: "{{EXECUTED_AT}}"
---

# Relatório de QA Global e Análise de Vulnerabilidades (Bomber Report) — Tentativa {{QA_ATTEMPT}}

## 1. Resumo Executivo de Qualidade e Segurança
- **Veredito Global:** `{{VERDICT}}`
- **Próxima Ação da Máquina de Estados:** `{{ACTION}}`
- **Bateria de Comandos Globais (`build`/`lint`/`typecheck`/`tests`):** `{{COMMANDS_SUMMARY}}`
- **Análise de Vulnerabilidades e Segurança (Dependências + SAST/OWASP):** `{{SECURITY_SUMMARY}}`

## 2. Resultado da Bateria Global de Testes e Build
| Etapa | Comando Executado | Exit Code | Duração (`s`) | Status |
| :--- | :--- | :--- | :--- | :--- |
{{QA_COMMANDS_TABLE_ROWS}}

### Logs Relevantes de Execução
```text
{{QA_LOGS_EXCERPT}}
```

## 3. Análise de Vulnerabilidades e Segurança (SAST & Dependências)
### 3.1. Varredura Automatizada (`run_bomber_checks.py` & Dependency Audit)
{{AUTOMATED_SECURITY_FINDINGS}}

### 3.2. Revisão de Segurança Semântica (OWASP Top 10 / CWEs sobre o `git diff`)
- **Injeção (SQL / NoSQL / Command Injection):** {{INJECTION_REVIEW}}
- **Autenticação, Autorização e Controle de Acesso:** {{AUTH_REVIEW}}
- **Exposição de Segredos / Dados Sensíveis:** {{SECRETS_REVIEW}}
- **Validação de Entrada e XSS / Path Traversal / SSRF:** {{INPUT_VALIDATION_REVIEW}}

## 4. Plano de Correção (*Hotfix Tasks* recomendadas caso `FAILED`)
{{HOTFIX_RECOMMENDATIONS}}
