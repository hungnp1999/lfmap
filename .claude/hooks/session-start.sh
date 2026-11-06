#!/usr/bin/env bash
# Enable the repo git hooks; install dependencies in Claude Code cloud sessions only.
set -euo pipefail
cd "${CLAUDE_PROJECT_DIR:-.}"
# Add the Dev-Environment trailer to commits (docs/DEVELOPMENT_PROVENANCE.md).
git config core.hooksPath .githooks
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
# The cloud checkout has no origin/HEAD; /security-review needs it to find the diff base.
git remote set-head origin main > /dev/null 2>&1 || true
uv sync
