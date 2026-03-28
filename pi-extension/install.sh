#!/usr/bin/env bash
set -euo pipefail

EXT_DIR="${HOME}/.pi/agent/extensions"
TARGET="${EXT_DIR}/let-me-know-agent.ts"
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
SOURCE="${REPO_ROOT}/extensions/let-me-know-agent.ts"

mkdir -p "${EXT_DIR}"
cp "${SOURCE}" "${TARGET}"

echo "Installed Pi extension to: ${TARGET}"
echo "Now run in pi: /reload"
