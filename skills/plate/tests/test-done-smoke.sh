#!/usr/bin/env bash
# test-done-smoke.sh — headless smoke test for /plate --done replay + cascade.
set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; RESET=$'\033[0m'
FAIL=0
fail() { echo "${RED}FAIL:${RESET} $*"; FAIL=$((FAIL+1)); }
pass() { echo "${GREEN}PASS:${RESET} $*"; }

CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export CLAUDE_PLUGIN_ROOT

TMPTEST=$(mktemp -d /tmp/plate-test-done.XXXXXX)
trap 'rm -rf "$TMPTEST"' EXIT

cd "$TMPTEST"
git init -q
git config user.email test@test.com
git config user.name "plate test"
echo "v1" > a.txt
git add a.txt && git commit -q -m "init"

export CLAUDE_PLUGIN_DATA="$TMPTEST/.plugin-data"
mkdir -p "$CLAUDE_PLUGIN_DATA"
. "$CLAUDE_PLUGIN_ROOT/scripts/lib/paths.sh"
plate_discover_root
plate_ensure_dirs

INSTANCE="$PLATE_ROOT/instances/done-smoke.json"
python3 "$CLAUDE_PLUGIN_ROOT/python/instance_rw.py" create-instance "$INSTANCE" done-smoke "$TMPTEST" main

# Seed plate 1
echo "plate1 work" >> a.txt
STASH1=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-stash.sh" done-smoke plate-1)
HEAD1=$(git rev-parse HEAD)
INSTANCE_FILE=$INSTANCE PLATE_ID=plate-1 HEAD_SHA=$HEAD1 STASH_SHA=$STASH1 \
PYTHON_DIR="$CLAUDE_PLUGIN_ROOT/python" BRANCH=main \
python3 <<'PY'
import os, sys
sys.path.insert(0, os.environ['PYTHON_DIR'])
from instance_rw import load, atomic_write, new_plate
from pathlib import Path
path = Path(os.environ['INSTANCE_FILE'])
data = load(path)
p = new_plate(os.environ['PLATE_ID'], os.environ['HEAD_SHA'], os.environ['STASH_SHA'], os.environ['BRANCH'])
p['summary_action'] = 'Add plate1 work to a.txt'
p['summary_goal'] = 'demonstrate plate 1'
p['hypothesis'] = 'append is idempotent'
p['hypothesis_hedge'] = {'confidence':'high','reason':'tested locally'}
p['files'] = ['a.txt']
data['stack'].append(p)
atomic_write(path, data)
PY

# Restore working tree, seed plate 2
git checkout -- a.txt
echo "plate2 work" >> a.txt
STASH2=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-stash.sh" done-smoke plate-2)
INSTANCE_FILE=$INSTANCE PLATE_ID=plate-2 HEAD_SHA=$HEAD1 STASH_SHA=$STASH2 \
PYTHON_DIR="$CLAUDE_PLUGIN_ROOT/python" BRANCH=main \
python3 <<'PY'
import os, sys
sys.path.insert(0, os.environ['PYTHON_DIR'])
from instance_rw import load, atomic_write, new_plate
from pathlib import Path
path = Path(os.environ['INSTANCE_FILE'])
data = load(path)
p = new_plate(os.environ['PLATE_ID'], os.environ['HEAD_SHA'], os.environ['STASH_SHA'], os.environ['BRANCH'])
p['summary_action'] = 'Add plate2 work to a.txt'
p['files'] = ['a.txt']
data['stack'].append(p)
atomic_write(path, data)
PY

git checkout -- a.txt

# Run done.sh
bash "$CLAUDE_PLUGIN_ROOT/scripts/done.sh" done-smoke > "$TMPTEST/done.out" 2>&1
pass "done.sh exited 0"

# Assert 2 [plate] commits
PLATE_COMMITS=$(git log --oneline | grep -c '^\S* \[plate\]' || true)
if [ "$PLATE_COMMITS" = "2" ]; then
  pass "2 [plate] commits in git log"
else
  fail "expected 2 plate commits, got $PLATE_COMMITS"
  git log --oneline
fi

# Assert stack empty, completed has 2 entries
STACK_LEN=$(python3 -c "import json; print(len(json.load(open('$INSTANCE'))['stack']))")
DONE_LEN=$(python3 -c "import json; print(len(json.load(open('$INSTANCE'))['completed']))")
if [ "$STACK_LEN" = "0" ]; then pass "stack drained"; else fail "stack len $STACK_LEN"; fi
if [ "$DONE_LEN" = "2" ]; then pass "completed has 2 entries"; else fail "completed len $DONE_LEN"; fi

# Assert refs cleaned up
REFS=$(git for-each-ref refs/plates/done-smoke/ | wc -l | tr -d ' ')
if [ "$REFS" = "0" ]; then pass "stash refs cleaned"; else fail "$REFS refs remaining"; fi

# Assert commit messages include hypothesis + hedge
if git log -1 HEAD~1 --format=%B | grep -q 'Hypothesis: append is idempotent'; then
  pass "hypothesis included in commit message"
else
  fail "hypothesis missing from commit message"
  git log -1 HEAD~1 --format=%B
fi

# ── Cascade test ──
echo ""
echo "-- cascade: child done cleans parent delegated_to --"
CHILD_INSTANCE="$PLATE_ROOT/instances/child-cascade.json"
PARENT_INSTANCE="$PLATE_ROOT/instances/parent-cascade.json"

python3 "$CLAUDE_PLUGIN_ROOT/python/instance_rw.py" create-instance "$PARENT_INSTANCE" parent-cascade "$TMPTEST" main
python3 "$CLAUDE_PLUGIN_ROOT/python/instance_rw.py" create-instance "$CHILD_INSTANCE" child-cascade "$TMPTEST" main

# Build parent with a delegated plate
python3 <<PY
import json
p = json.load(open('$PARENT_INSTANCE'))
p['stack'] = [{
  'plate_id': 'parent-p1', 'state': 'delegated',
  'delegated_to': ['child-cascade'],
  'push_time_head_sha': '$HEAD1', 'stash_sha': '$HEAD1',
  'branch':'main','summary_action':'parent work',
  'summary_goal':'', 'hypothesis':'', 'files':[],'errors':[],
  'summary_goal_hedge':{'confidence':'low','reason':''},
  'hypothesis_hedge':{'confidence':'low','reason':''},
  'pushed_at':'2026-04-10T00:00:00Z','completed_at':None,'commit_sha':None,
  'delegated_to':['child-cascade']
}]
json.dump(p, open('$PARENT_INSTANCE','w'), indent=2)

c = json.load(open('$CHILD_INSTANCE'))
c['parent_ref'] = {'convo_id':'parent-cascade','plate_id':'parent-p1'}
c['stack'] = [{
  'plate_id':'child-p1','state':'paused','delegated_to':[],
  'push_time_head_sha':'$HEAD1','stash_sha':'$HEAD1',
  'branch':'main','summary_action':'child work',
  'summary_goal':'','hypothesis':'','files':[],'errors':[],
  'summary_goal_hedge':{'confidence':'low','reason':''},
  'hypothesis_hedge':{'confidence':'low','reason':''},
  'pushed_at':'2026-04-10T00:00:00Z','completed_at':None,'commit_sha':None,
}]
json.dump(c, open('$CHILD_INSTANCE','w'), indent=2)
PY

# Create a ref so done.sh's ref-delete doesn't fail (it tolerates missing)
git update-ref refs/plates/child-cascade/child-p1 "$HEAD1"

bash "$CLAUDE_PLUGIN_ROOT/scripts/done.sh" child-cascade > "$TMPTEST/child-done.out" 2>&1 || true

# Parent's plate should now have empty delegated_to and state=paused
PARENT_STATE=$(python3 -c "
import json
d = json.load(open('$PARENT_INSTANCE'))
p = d['stack'][0]
print(p['state'], len(p.get('delegated_to',[])))
")
if [ "$PARENT_STATE" = "paused 0" ]; then
  pass "parent plate flipped back to paused, delegated_to empty"
else
  fail "parent state = '$PARENT_STATE' (expected 'paused 0')"
fi

if [ "$FAIL" -gt 0 ]; then
  echo "${RED}$FAIL test(s) failed${RESET}"
  exit 1
fi
echo ""
echo "${GREEN}All done smoke tests passed.${RESET}"
