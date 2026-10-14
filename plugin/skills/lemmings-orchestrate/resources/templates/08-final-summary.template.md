# Relatório Consolidado de Execução (`08-final-summary.md`)

- **Run ID:** `{{RUN_ID}}`
- **Especificação Origem:** `{{SPEC_PATH}}`
- **Status Final:** `{{FINAL_STATUS}}` (`COMPLETED` | `HALTED`)
- **Início da Run:** `{{CREATED_AT}}`
- **Conclusão da Run:** `{{COMPLETED_AT}}`

---

## 1. Resumo Executivo

{{EXECUTIVE_SUMMARY}}

| Métrica | Valor |
| :--- | :--- |
| **Total de Ondas (Waves) Executadas** | `{{TOTAL_WAVES}}` |
| **Total de Tasks Concluídas (`VERIFIED`)** | `{{VERIFIED_TASKS}} / {{TOTAL_TASKS}}` |
| **Tentativas de QA Global & AppSec (`Bomber`)** | `{{QA_ATTEMPTS}}` (`{{QA_FINAL_VERDICT}}`) |
| **Status de Deploy (`Floater`)** | `{{DEPLOY_FINAL_VERDICT}}` (Ambiente: `{{DEPLOY_ENV}}`) |

---

## 2. Entregas por Onda (Waves & Tasks)

{{WAVES_DELIVERY_TABLE}}

---

## 3. Qualidade Global e Segurança (`lemming-bomber`)

- **Relatório:** `{{LAST_BOMBER_REPORT}}`
- **Resumo:** {{QA_SUMMARY}}

---

## 4. Deploy e Homologação (`lemming-floater`)

- **Relatório:** `{{FLOATER_REPORT}}`
- **Resumo:** {{DEPLOY_SUMMARY}}

---

## 5. Índice Completo de Artefatos Gerados na Run

{{ARTIFACTS_INDEX}}
