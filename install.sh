#!/usr/bin/env bash
set -euo pipefail

# Lemmings Squad — 1-Command Installer for Google Antigravity
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="${REPO_ROOT}/plugin"
SIDECAR_SRC="${REPO_ROOT}/sidecar"
CLI_SRC="${REPO_ROOT}/bin/lemmings"

GLOBAL_CONFIG_DIR="${HOME}/.gemini/config"
GLOBAL_PLUGINS_DIR="${GLOBAL_CONFIG_DIR}/plugins"
GLOBAL_SIDECARS_DIR="${GLOBAL_CONFIG_DIR}/sidecars"
TARGET_PLUGIN_DIR="${GLOBAL_PLUGINS_DIR}/lemmings-squad"
TARGET_SIDECAR_DIR="${GLOBAL_SIDECARS_DIR}/lemmings-watcher"
LOCAL_BIN_DIR="${HOME}/.local/bin"

# Default to "copy" so resolved paths stay strictly inside ~/.gemini/config/plugins/
# and Antigravity never asks for cross-workspace read permissions in other projects.
MODE="copy"
TARGET_REPO=""
WITH_WATCHER="false"

usage() {
  cat <<EOF
Usage: ./install.sh [OPTIONS]

Options:
  --copy                Copy plugin files into ~/.gemini/config/plugins/ (default, avoids cross-workspace permission prompts)
  --symlink             Link plugin directory (not recommended when testing from other workspaces due to symlink path resolution)
  --with-watcher        Also install the lemmings-watcher Sidecar in ~/.gemini/config/sidecars/lemmings-watcher
  --target-repo <path>  Also install agents & skills into a target repository (_agents/)
  -h, --help            Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --copy)
      MODE="copy"
      shift
      ;;
    --symlink)
      MODE="symlink"
      shift
      ;;
    --with-watcher)
      WITH_WATCHER="true"
      shift
      ;;
    --target-repo)
      TARGET_REPO="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

echo "==> Preparing Lemmings Squad plugin resources..."
mkdir -p "${GLOBAL_PLUGINS_DIR}"

# Sync templates & schemas into plugin/skills/lemmings-orchestrate/resources/
RESOURCES_DIR="${PLUGIN_SRC}/skills/lemmings-orchestrate/resources"
mkdir -p "${RESOURCES_DIR}/templates" "${RESOURCES_DIR}/schemas"
cp -R "${REPO_ROOT}/templates/"* "${RESOURCES_DIR}/templates/"
cp -R "${REPO_ROOT}/schemas/"* "${RESOURCES_DIR}/schemas/"

# Ensure scripts and CLI are executable
chmod +x "${PLUGIN_SRC}/skills/lemmings-orchestrate/scripts/"*.py
chmod +x "${PLUGIN_SRC}/skills/lemmings-init/scripts/"*.py
if [[ -f "${CLI_SRC}" ]]; then
  chmod +x "${CLI_SRC}"
fi
if [[ -f "${SIDECAR_SRC}/lemmings_watcher.py" ]]; then
  chmod +x "${SIDECAR_SRC}/lemmings_watcher.py"
fi

# Clean up any legacy symlinks inside source plugin/ folder
rm -f "${PLUGIN_SRC}/templates" "${PLUGIN_SRC}/schemas"

# Remove existing installation if present
if [[ -L "${TARGET_PLUGIN_DIR}" || -d "${TARGET_PLUGIN_DIR}" ]]; then
  rm -rf "${TARGET_PLUGIN_DIR}"
fi

if [[ "${MODE}" == "copy" ]]; then
  mkdir -p "${TARGET_PLUGIN_DIR}"
  cp -R "${PLUGIN_SRC}/"* "${TARGET_PLUGIN_DIR}/"
  mkdir -p "${TARGET_PLUGIN_DIR}/templates" "${TARGET_PLUGIN_DIR}/schemas"
  cp -R "${REPO_ROOT}/templates/"* "${TARGET_PLUGIN_DIR}/templates/"
  cp -R "${REPO_ROOT}/schemas/"* "${TARGET_PLUGIN_DIR}/schemas/"
  echo "==> [OK] Installed plugin (copied real files) to: ${TARGET_PLUGIN_DIR}"
else
  ln -s "${PLUGIN_SRC}" "${TARGET_PLUGIN_DIR}"
  echo "==> [OK] Linked plugin: ${TARGET_PLUGIN_DIR} -> ${PLUGIN_SRC}"
fi

# Install CLI into ~/.local/bin/lemmings if possible
if [[ -f "${CLI_SRC}" ]]; then
  if mkdir -p "${LOCAL_BIN_DIR}" 2>/dev/null && cp "${CLI_SRC}" "${LOCAL_BIN_DIR}/lemmings" 2>/dev/null; then
    chmod +x "${LOCAL_BIN_DIR}/lemmings"
    echo "==> [OK] Installed CLI to: ${LOCAL_BIN_DIR}/lemmings"
  fi
fi

# Install Sidecar if --with-watcher is enabled
if [[ "${WITH_WATCHER}" == "true" ]]; then
  mkdir -p "${GLOBAL_SIDECARS_DIR}"
  rm -rf "${TARGET_SIDECAR_DIR}"
  mkdir -p "${TARGET_SIDECAR_DIR}"
  cp -R "${SIDECAR_SRC}/"* "${TARGET_SIDECAR_DIR}/"
  chmod +x "${TARGET_SIDECAR_DIR}/lemmings_watcher.py"
  echo "==> [OK] Installed Sidecar to: ${TARGET_SIDECAR_DIR}"
fi

if [[ -n "${TARGET_REPO}" ]]; then
  if [[ ! -d "${TARGET_REPO}" ]]; then
    echo "Error: Target repo directory '${TARGET_REPO}' does not exist." >&2
    exit 1
  fi
  REPO_AGENTS_DIR="${TARGET_REPO}/_agents"
  mkdir -p "${REPO_AGENTS_DIR}/agents" "${REPO_AGENTS_DIR}/skills"
  cp -R "${PLUGIN_SRC}/agents/"* "${REPO_AGENTS_DIR}/agents/"
  cp -R "${PLUGIN_SRC}/skills/"* "${REPO_AGENTS_DIR}/skills/"
  echo "==> [OK] Installed Lemmings Squad into target repository: ${REPO_AGENTS_DIR}"
fi

echo ""
echo "Lemmings Squad installed successfully!"
echo "  - Plugin path:      ${TARGET_PLUGIN_DIR}"
echo "  - Available agents: lemming-commander, lemming-scout, lemming-builder, lemming-inspector, lemming-bomber, lemming-floater, lemming-basher"
echo "  - Available skills: lemmings-orchestrate, lemmings-init"
echo "  - CLI binary:       ${REPO_ROOT}/bin/lemmings"
