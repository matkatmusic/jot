#!/usr/bin/env bash
# next.sh — Walk parent delegation chain upward to find next resume point (§4).
# Args: $1=convo_id
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="$(cd "$SCRIPTS_DIR/../../python/plate" && pwd)"
# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root

CONVO_ID="${1:?usage: next.sh <convo_id>}"

PLATE_ROOT="$PLATE_ROOT" CONVO_ID="$CONVO_ID" python3 "$PYTHON_DIR/next_resume_point.py"
