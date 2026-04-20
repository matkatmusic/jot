#!/usr/bin/env bash
# test-drop-smoke.sh — headless smoke test for /plate --drop.
set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; RESET=$'\033[0m'
FAIL=0
fail() { echo "${RED}FAIL:${RESET} $*"; FAIL=$((FAIL+1)); }
pass() { echo "${GREEN}PASS:${RESET} $*"; }

CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export CLAUDE_PLUGIN_ROOT

TMPTEST=$(mktemp -d /tmp/plate-test-drop.XXXXXX)
trap 'rm -rf "$TMPTEST"' EXIT

cd "$TMPTEST"
git init -q
git config user.email test@test.com
git config user.name "plate test"
echo "baseline" > a.txt
git add a.txt && git commit -q -m "init"

export CLAUDE_PLUGIN_DATA="$TMPTEST/.plugin-data"
mkdir -p "$CLAUDE_PLUGIN_DATA"
. "$CLAUDE_PLUGIN_ROOT/skills/plate/scripts/paths.sh"
plate_discover_repo_root
plate_ensure_dirs

INSTANCE="$PLATE_ROOT/instances/drop-smoke.json"
python3 "$CLAUDE_PLUGIN_ROOT/common/scripts/plate/instance_rw.py" create-instance "$INSTANCE" drop-smoke "$TMPTEST" main

# ── Sub-test 1: drop with nothing to drop emits error ─────────────────────
set +e
OUT=$(bash "$CLAUDE_PLUGIN_ROOT/skills/plate/scripts/drop.sh" drop-smoke "$INSTANCE" 2>&1)
RC=$?
set -e
if [ "$RC" -ne 0 ] && echo "$OUT" | grep -q "no plates on the stack"; then
  pass "empty-stack drop emits error"
else
  fail "expected empty-stack error, got rc=$RC out=$OUT"
fi

# ── Sub-test 2: push plate, make extra changes, drop ─────────────────────
echo "plate1 work" >> a.txt
STASH1=$(bash "$CLAUDE_PLUGIN_ROOT/skills/plate/scripts/snapshot-stash.sh" drop-smoke plate-1)
HEAD1=$(git rev-parse HEAD)

INSTANCE_FILE=$INSTANCE PLATE_ID=plate-1 HEAD_SHA=$HEAD1 STASH_SHA=$STASH1 \
PYTHON_DIR="$CLAUDE_PLUGIN_ROOT/common/scripts/plate" BRANCH=main \
python3 <<'PY'
import os, sys
sys.path.insert(0, os.environ['PYTHON_DIR'])
from instance_rw import load, atomic_write, new_plate
from pathlib import Path
path = Path(os.environ['INSTANCE_FILE'])
data = load(path)
p = new_plate(os.environ['PLATE_ID'], os.environ['HEAD_SHA'], os.environ['STASH_SHA'], os.environ['BRANCH'])
p['files'] = ['a.txt']
data['stack'].append(p)
atomic_write(path, data)
PY

# Add extra work that we will abandon via --drop
echo "abandoned work" >> a.txt
echo "trash" > junk.txt

bash "$CLAUDE_PLUGIN_ROOT/skills/plate/scripts/drop.sh" drop-smoke "$INSTANCE" > "$TMPTEST/drop.out" 2>&1
pass "drop.sh exited 0"

# Patch file should exist
PATCH_COUNT=$(find "$PLATE_ROOT/dropped/drop-smoke/" -name '*.patch' 2>/dev/null | wc -l | tr -d ' ')
if [ "$PATCH_COUNT" = "1" ]; then
  pass "1 patch file written"
else
  fail "expected 1 patch file, found $PATCH_COUNT"
fi

# Stash ref should be deleted
if ! git cat-file -t refs/plates/drop-smoke/plate-1 >/dev/null 2>&1; then
  pass "stash ref deleted"
else
  fail "stash ref still present"
fi

# Stack should be empty after drop
STACK_LEN=$(python3 -c "import json; print(len(json.load(open('$INSTANCE'))['stack']))")
if [ "$STACK_LEN" = "0" ]; then
  pass "stack emptied"
else
  fail "stack len $STACK_LEN (expected 0)"
fi

# Working tree should be restored to plate's snapshot state (contains plate1 work
# but NOT 'abandoned work'). Note: untracked junk.txt will NOT be removed by
# `git checkout` — drop.sh intentionally only restores tracked files.
if grep -q "plate1 work" a.txt && ! grep -q "abandoned work" a.txt; then
  pass "tracked file a.txt restored to plate snapshot"
else
  fail "a.txt not restored correctly"
  cat a.txt
fi

# Patch file should contain the abandoned work hunks so it is recoverable
PATCH_FILE=$(find "$PLATE_ROOT/dropped/drop-smoke/" -name '*.patch' | head -1)
if grep -q "abandoned work" "$PATCH_FILE"; then
  pass "patch file contains abandoned changes"
else
  fail "patch file missing abandoned changes"
fi

if [ "$FAIL" -gt 0 ]; then
  echo "${RED}$FAIL test(s) failed${RESET}"
  exit 1
fi
echo ""
echo "${GREEN}All drop smoke tests passed.${RESET}"
