#!/usr/bin/env bash
set -euo pipefail

GLOBAL_CONFIG_DIR="${HOME}/.gemini/config"
TARGET_PLUGIN_DIR="${GLOBAL_CONFIG_DIR}/plugins/lemmings-squad"
TARGET_SIDECAR_DIR="${GLOBAL_CONFIG_DIR}/sidecars/lemmings-watcher"
TARGET_BIN="${HOME}/.local/bin/lemmings"

echo "==> Uninstalling Lemmings Squad..."

if [[ -L "${TARGET_PLUGIN_DIR}" || -d "${TARGET_PLUGIN_DIR}" ]]; then
  rm -rf "${TARGET_PLUGIN_DIR}"
  echo "  - Removed plugin: ${TARGET_PLUGIN_DIR}"
else
  echo "  - Plugin not found at ${TARGET_PLUGIN_DIR} (already removed)"
fi

if [[ -L "${TARGET_SIDECAR_DIR}" || -d "${TARGET_SIDECAR_DIR}" ]]; then
  rm -rf "${TARGET_SIDECAR_DIR}"
  echo "  - Removed sidecar: ${TARGET_SIDECAR_DIR}"
fi

if [[ -L "${TARGET_BIN}" || -f "${TARGET_BIN}" ]]; then
  rm -f "${TARGET_BIN}"
  echo "  - Removed CLI binary: ${TARGET_BIN}"
fi

echo "==> [OK] Lemmings Squad uninstalled cleanly."
