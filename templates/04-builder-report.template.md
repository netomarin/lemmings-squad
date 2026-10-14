---
run_id: "{{RUN_ID}}"
step: "04-builder-report"
wave_number: {{WAVE_NUMBER}}
task_id: "{{TASK_ID}}"
task_title: "{{TASK_TITLE}}"
isolation_mode: "{{ISOLATION_MODE}}"
status: "DEV_DONE"
completed_at: "{{COMPLETED_AT}}"
---

# Relatório de Construção (Builder Report): `{{TASK_ID}}` — {{TASK_TITLE}}

## 1. Resumo da Implementação
{{IMPLEMENTATION_SUMMARY}}

## 2. Arquivos de Código e Testes Tocados
### 2.1. Arquivos de Implementação (`target_files`)
| Arquivo | Ação (`CREATED` / `MODIFIED`) | Descrição Técnica das Alterações |
| :--- | :--- | :--- |
{{TARGET_FILES_TABLE}}

### 2.2. Arquivos de Teste Unitário (`test_files`)
| Arquivo de Teste | Cenários Cobertos (Happy Path & Edge Cases) |
| :--- | :--- |
{{TEST_FILES_TABLE}}

## 3. Atendimento aos Critérios de Aceite
{{ACCEPTANCE_CRITERIA_CHECKLIST}}

## 4. Evidência de Execução de Testes (`verification_cmd`)
- **Comando Executado:** `{{VERIFICATION_CMD}}`
- **Código de Saída (Exit Code):** `{{EXIT_CODE}}`
- **Resumo do Output:**
```text
{{TEST_EXECUTION_OUTPUT}}
```

## 5. Notas para o `lemming-inspector`
{{NOTES_FOR_INSPECTOR}}
