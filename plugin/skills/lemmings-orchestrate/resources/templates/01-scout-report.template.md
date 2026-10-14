---
run_id: "{{RUN_ID}}"
step: "01-scout-report"
scout_scope: "{{SCOUT_SCOPE}}"
spec_source: "{{SPEC_SOURCE}}"
created_at: "{{CREATED_AT}}"
---

# Relatório de Reconhecimento (Scout Report): {{TITLE}}

## 1. Especificação e Referências Analisadas
- **Especificação Principal:** [{{SPEC_BASENAME}}](file://{{SPEC_ABS_PATH}})
- **Documentos, Schemas e Referências Cruzadas Lidas:**
{{REFERENCED_DOCS_LIST}}

## 2. Requisitos Extraídos e Critérios de Aceite da Spec
{{EXTRACTED_REQUIREMENTS}}

## 3. Diagnóstico da Arquitetura e Convenções do Repositório
- **Linguagem / Runtime / Framework:** {{STACK_SUMMARY}}
- **Padrões Arquiteturais e de Código:** {{ARCHITECTURE_PATTERNS}}
- **Framework e Convenções de Testes:** {{TESTING_CONVENTIONS}}

## 4. Mapa de Arquivos Impactados
| Arquivo / Módulo | Status (`EXISTING` / `NEW`) | Ação (`CREATE` / `MODIFY` / `DELETE`) | Impacto e Dependências |
| :--- | :--- | :--- | :--- |
{{IMPACT_TABLE_ROWS}}

## 5. Comandos Descobertos (Config / Auto-Discovery)
- **Fonte da Descoberta:** `{{CONFIG_SOURCE}}`
- `install_cmd`: `{{INSTALL_CMD}}`
- `lint_cmd`: `{{LINT_CMD}}`
- `typecheck_cmd`: `{{TYPECHECK_CMD}}`
- `unit_test_cmd`: `{{UNIT_TEST_CMD}}`
- `integration_test_cmd`: `{{INTEGRATION_TEST_CMD}}`
- `security_scan_cmd`: `{{SECURITY_SCAN_CMD}}`
- `build_cmd`: `{{BUILD_CMD}}`
- `deploy_test_cmd`: `{{DEPLOY_TEST_CMD}}`
- `deploy_staging_cmd`: `{{DEPLOY_STAGING_CMD}}`

## 6. Recomendação de Ondas (Waves) e Fronteiras de Paralelismo
{{WAVE_RECOMMENDATIONS}}

## 7. Riscos, Ambiguidades e Casos Limites (Edge Cases)
{{RISKS_AND_AMBIGUITIES}}
