#!/usr/bin/env bash
# list-paused-plates.sh — Emit one row per paused plate across all instances.
# Output format: <convoID>|<plate_id>|<label>|<summary_action>|<pushed_at>
# Used by SKILL.md to build the AskUserQuestion dropdown.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root

shopt -s nullglob
for f in "$PLATE_ROOT"/instances/*.json; do
  INSTANCE_FILE="$f" python3 <<'PY' 2>/dev/null || true
import json, os
d = json.load(open(os.environ['INSTANCE_FILE']))
convo = d.get('convo_id', '')
label = d.get('label') or convo[:12]
for p in d.get('stack', []):
    if p.get('state') == 'paused':
        pushed = p.get('pushed_at', '')
        action = p.get('summary_action') or '(no synopsis)'
        print(f"{convo}|{p['plate_id']}|{label}|{action}|{pushed}")
PY
done
shopt -u nullglob
