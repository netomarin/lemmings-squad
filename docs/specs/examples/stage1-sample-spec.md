# Spec de Exemplo (Validação Estágio 1): Gerenciador de Estado Atômico e Validador de Schema

> **Objetivo deste arquivo:** Servir como insumo de teste para validar o **Estágio 1** do Lemmings Squad (`lemming-commander` + `lemming-scout`).

## 1. Descrição da Feature
Precisamos implementar o núcleo de gerenciamento de estado do **Lemmings Squad** (previsto para o Estágio 2 da especificação geral), composto pelos schemas JSON e pelo script `state_manager.py`.

## 2. Referências Obrigatórias
O agente explorador (`lemming-scout`) **deve** ler os seguintes documentos referenciados antes da geração do plano:
- Especificação Geral do Projeto: [general-spec.md](../general-spec.md)
- Política de Segurança e Escrita Atômica: [referenced-security-policy.md](./referenced-security-policy.md)

## 3. Requisitos Funcionais
1. Criar `schemas/backlog.schema.json` e `schemas/lemmings-config.schema.json`.
2. Criar `plugin/skills/lemmings-orchestrate/scripts/state_manager.py` com suporte a:
   - `init-run --spec <path>`
   - `next-wave --run-dir <path>`
   - `update-task --run-dir <path> --task-id <id> --status <status>`
3. Obedecer integralmente às 3 regras descritas em [referenced-security-policy.md](./referenced-security-policy.md).
4. Incluir suíte de testes unitários em `tests/test_state_manager.py` executável via `python3 -m unittest`.
