---
run_id: "{{RUN_ID}}"
step: "02-implementation-plan"
spec_source: "{{SPEC_SOURCE}}"
scout_reports:
  - ".lemmings/runs/{{RUN_ID}}/01-scout-report.md"
status: "WAITING_APPROVAL" # DRAFT | WAITING_APPROVAL | APPROVED | IN_PROGRESS | COMPLETED | HALTED
auto_approve: {{AUTO_APPROVE}}
deploy_target: "{{DEPLOY_TARGET}}" # none | test | staging
created_at: "{{CREATED_AT}}"
---

# Plano de Implementação: {{TITLE}}

## 1. Resumo Executivo e Objetivo
{{EXECUTIVE_SUMMARY}}

## 2. Artefatos de Entrada e Referências Analisadas
- **Especificação Principal:** [{{SPEC_BASENAME}}](file://{{SPEC_ABS_PATH}})
- **Relatório(s) do Scout:** [01-scout-report.md](file://{{SCOUT_REPORT_ABS_PATH}})
- **Referências Cruzadas Lidas:**
{{REFERENCED_DOCS_LIST}}

## 3. Diagnóstico da Arquitetura e Mapa de Arquivos Impactados
### 3.1. Padrões e Convenções do Repositório
{{ARCHITECTURE_PATTERNS}}

### 3.2. Arquivos a Criar, Modificar ou Remover
| Arquivo / Módulo | Ação (`CREATE` / `MODIFY` / `DELETE`) | Responsabilidade / Mudança Planejada |
| :--- | :--- | :--- |
{{IMPACT_TABLE_ROWS}}

## 4. Comandos de Qualidade, Segurança e Deploy (Config / Auto-Discovery)
> Fonte da descoberta: `{{CONFIG_SOURCE}}`

| Etapa | Comando Descoberto / Configurado | Obrigatório? |
| :--- | :--- | :--- |
| **Install / Setup** | `{{INSTALL_CMD}}` | Opcional |
| **Lint** | `{{LINT_CMD}}` | Sim |
| **Typecheck** | `{{TYPECHECK_CMD}}` | Sim |
| **Unit Tests** | `{{UNIT_TEST_CMD}}` | Sim |
| **Integration / E2E Tests** | `{{INTEGRATION_TEST_CMD}}` | Condicional |
| **Security / Vulnerability Scan** | `{{SECURITY_SCAN_CMD}}` | Sim |
| **Build** | `{{BUILD_CMD}}` | Sim |
| **Deploy (`{{DEPLOY_TARGET}}`)** | `{{DEPLOY_CMD}}` | Condicional |
| **Smoke Test Pós-Deploy** | `{{SMOKE_TEST_CMD}}` | Condicional |

## 5. Estratégia de Implementação em Ondas (Wave Execution Plan)
{{WAVE_STRATEGY_DIAGRAM_AND_SUMMARY}}

### Detalhamento Preliminar de Ondas e Tasks
{{WAVES_TASKS_BREAKDOWN}}

## 6. Riscos, Casos Limites (Edge Cases) e Mitigações
{{RISKS_AND_MITIGATIONS}}

---

## 7. Gate de Aprovação
- [ ] **Plano revisado e aprovado para geração do Backlog (`03-backlog.json`) e início da implementação.**
  - *Para aprovar via integração/arquivo, altere `status: "WAITING_APPROVAL"` para `status: "APPROVED"` no frontmatter deste arquivo e `00-run-status.json`, ou aprove diretamente na solicitação do Commander.*
