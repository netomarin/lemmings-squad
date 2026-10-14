---
name: lemmings-init
description: Initialize and configure Lemmings Squad (.lemmings/config.yaml, .lemmings/config.json, optional custom report templates) and build or update CI/CD pipelines and deployment configurations (.github/workflows, GitLab CI, Cloud Build, Git Hooks, Dockerfile, firebase.json) via lemming-basher in any repository.
---

# `lemmings-init` — Inicializador de Repositório e Consultor de CI/CD (`lemming-basher`)

Use esta skill em **2 cenários principais**:
1. **Gatilho 1 — Inicialização do Repositório (`lemmings-init`):** O usuário pede para inicializar o Lemmings no projeto (*"Inicialize o Lemmings neste projeto"*, *"lemmings init"*).
2. **Gatilho 2 — Pedido Manual Sob Demanda de Deploy / CI / CD:** O usuário pede ajuda explicitamente para preparar o deploy ou a esteira CI/CD (*"Me ajude a configurar o deploy deste projeto"*, *"Configure o CI/CD com o Lemmings"*, *"Prepare o deploy para Cloud Run / Firebase"*).

---

## Gatilho 1: Inicialização do Repositório + Sugestão Inteligente Baseada em Indícios (`deploy_signals`)

1. Execute o script de auto-discovery e análise de indícios na raiz do repositório alvo (`<workspace_root>`):

```bash
python3 ~/.gemini/config/plugins/lemmings-squad/skills/lemmings-init/scripts/init_config.py \
  --workspace "<workspace_root>"
```

2. Analise o bloco `"deploy_signals"` retornado no JSON:
   - **Caso A — Há indícios suficientes de deploy (`deploy_signals.should_suggest_cd == true`, `confidence: "high"` ou `"medium"`):**
     - Mostre ao usuário os indícios encontrados (`infra_artifacts`, `app_signals`, `recommended_target` e as API Keys/Secrets detectadas no código em `detected_secret_vars`).
     - Pergunte via `ask_question` sugerindo proativamente o CD:
       - `(Recommended) Configurar CI Contínuo + Deploy/CD Guiado com o lemming-basher (alvo sugerido: <recommended_target>)`
       - `Configurar apenas o pipeline de CI Contínuo (commits em qualquer branch + gate na main)`
       - `Manter apenas a configuração local (.lemmings/config.yaml) por enquanto`
   - **Caso B — NÃO há indícios de deploy (`deploy_signals.should_suggest_cd == false`, `confidence: "none"`, ex: biblioteca pura ou repositório vazio):**
     - **Não** incomode o usuário com perguntas de nuvem/ambientes.
     - Pergunte via `ask_question` priorizando apenas o CI ou a configuração local:
       - `(Recommended) Configurar apenas o pipeline de CI Contínuo (commits em qualquer branch + gate na main)`
       - `Manter apenas a configuração local (.lemmings/config.yaml) por enquanto`
       - `Quero configurar também o Deploy / CD manualmente com o lemming-basher`

---

## Gatilho 2: Disparo Manual Sob Demanda (*"Me ajude a configurar o deploy / CD"*) ou Aceite no Gatilho 1

Quando o usuário pedir ajuda para configurar o deploy/CD (ou aceitar a opção no Gatilho 1), acione o **`lemming-basher`** via `invoke_subagent` (`TypeName: "lemming-basher"`, `Workspace: "inherit"`):

1. **Se o usuário pediu apenas CI (Continuous Integration):**
   - Execute `init_config.py --workspace "<workspace_root>" --with-ci`, gerando o workflow de CI (ou Git Hooks locais se não houver remote) e `.lemmings/cicd-pipeline-report.md`.
2. **Se o usuário pediu ajuda para configurar o Deploy / CD (Modo Consultor Completo):**
   - Conduza a entrevista guiada de 3 passos (Ambientes/Gatilhos $\rightarrow$ Destino de Nuvem + Smoke Test $\rightarrow$ Confirmação das API Keys/Secrets detectadas pelo `env_scanner` e Autenticação Cloud).
   - Se o repositório ainda não possuir `Dockerfile`, `.dockerignore`, `firebase.json` ou `.env.example`, passe `--scaffold-infra` e `--cloud-target <cloud-run|firebase|gke|custom>` ao `init_config.py` para gerar os arquivos de infraestrutura faltantes.
   - Se disponível no Antigravity, utilize os servidores MCP nativos (`cloudrun`, `firebase-mcp-server`, `gke-oss`) para listar projetos/serviços existentes e auxiliar na configuração.
   - Gere os pipelines de CI/CD, sincronize `.lemmings/config.yaml` (para o `lemming-floater` usar nas runs) e grave `.lemmings/cicd-pipeline-report.md`.
