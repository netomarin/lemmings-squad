# Relatório de Deploy e Smoke Test (`07-floater-deploy-{{ENV}}.md`)

- **Run ID:** `{{RUN_ID}}`
- **Ambiente Alvo:** `{{ENV}}` (`test` | `staging` | `homolog` | `none`)
- **Estratégia Configurada:** `{{DEPLOY_STRATEGY}}` (`never` | `auto` | `ask` | `on_param`)
- **Agente Executor:** `lemming-floater`
- **Veredito do Deploy:** `{{VERDICT}}` (`DEPLOYED` | `SKIPPED` | `FAILED`)
- **Timestamp:** `{{TIMESTAMP}}`

---

## 1. Avaliação da Política de Deploy

- **Fonte da Configuração:** `{{CONFIG_SOURCE}}` (`.lemmings/config.yaml` | `.lemmings/config.json` | `03-backlog.json` | `Parâmetro da Run`)
- **Decisão:** {{POLICY_DECISION_SUMMARY}}

---

## 2. Execução do Deploy

- **Comando de Deploy:** `{{DEPLOY_CMD}}`
- **Exit Code:** `{{DEPLOY_EXIT_CODE}}`
- **Duração:** `{{DEPLOY_DURATION}}`

### Resumo do Output de Deploy
```text
{{DEPLOY_OUTPUT_SNIPPET}}
```

---

## 3. Verificação Pós-Deploy (Smoke Test / Healthcheck)

- **Comando de Smoke Test:** `{{SMOKE_TEST_CMD}}`
- **Exit Code:** `{{SMOKE_EXIT_CODE}}`
- **Resultado:** `{{SMOKE_STATUS}}` (`PASSED` | `SKIPPED` | `FAILED`)

### Resumo do Output do Smoke Test
```text
{{SMOKE_OUTPUT_SNIPPET}}
```

---

## 4. Conclusão e Encaminhamento

{{CONCLUSION_NOTES}}
