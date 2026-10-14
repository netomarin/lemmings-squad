# Política de Segurança e Auditoria de Estado (Referência Cruzada)

Este documento define as restrições de segurança e integridade que qualquer utilitário do **Lemmings Squad** deve obedecer ao manipular arquivos de estado no disco:

1. **Bloqueio de Arquivo (File Locking):** Toda escrita em `.lemmings/runs/<run-id>/backlog.json` ou `plan.md` deve utilizar lock exclusivo (`fcntl.flock`) para impedir corrupção em execuções paralelas.
2. **Prevenção de Path Traversal:** Nenhum `run_id` ou caminho de arquivo vindo do `backlog.json` pode conter sequências `..` ou escapar do diretório raiz do repositório alvo.
3. **Escrita Atômica (Write-Then-Rename):** Atualizações no `backlog.json` devem ser escritas primeiro em um arquivo temporário no mesmo diretório e aplicadas via `os.replace()`.
