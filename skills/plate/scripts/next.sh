#!/usr/bin/env bash
# next.sh — Walk parent delegation chain upward to find next resume point (§4).
# Args: $1=convo_id
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="${CLAUDE_PLUGIN_ROOT}/python"
# shellcheck source=lib/paths.sh
. "$SCRIPTS_DIR/lib/paths.sh"
plate_discover_root

CONVO_ID="${1:?usage: next.sh <convo_id>}"

PLATE_ROOT="$PLATE_ROOT" CONVO_ID="$CONVO_ID" python3 <<'PY'
import json, os
from pathlib import Path

plate_root = Path(os.environ['PLATE_ROOT'])
convo = os.environ['CONVO_ID']
depth = 0
MAX_DEPTH = 20
exhausted = True

while depth < MAX_DEPTH:
    inst_path = plate_root / 'instances' / f'{convo}.json'
    if not inst_path.exists():
        exhausted = False
        break
    data = json.load(open(inst_path))
    parent = data.get('parent_ref', {})
    if not parent or not parent.get('convo_id'):
        print(f'Reached top-level instance: {convo}')
        print('No ancestor with paused work.')
        exhausted = False
        break
    parent_convo = parent['convo_id']
    parent_path = plate_root / 'instances' / f'{parent_convo}.json'
    if not parent_path.exists():
        print(f'Parent {parent_convo} not found (dangling ref)')
        exhausted = False
        break
    parent_data = json.load(open(parent_path))
    paused = [p for p in parent_data.get('stack', []) if p.get('state') == 'paused']
    if paused:
        cwd = parent_data.get('cwd', '.')
        label = parent_data.get('label') or parent_convo[:12]
        action = paused[-1].get('summary_action') or '(no synopsis)'
        print(f'Resume here: {label} -> "{action}"')
        print(f'  cd {cwd} && claude --resume {parent_convo}')
        exhausted = False
        break
    convo = parent_convo
    depth += 1

if exhausted:
    print('Max depth reached (possible cycle in parent_ref chain)')
PY
