#!/usr/bin/env bash
# Install dependencies in Claude Code cloud sessions; no-op on local machines.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}"
uv sync
