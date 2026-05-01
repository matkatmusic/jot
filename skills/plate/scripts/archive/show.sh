#!/usr/bin/env bash
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$SCRIPTS_DIR/render-tree.sh"
# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root
"${EDITOR:-less}" "$PLATE_ROOT/tree.md"
