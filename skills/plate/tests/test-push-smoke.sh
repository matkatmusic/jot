#!/usr/bin/env bash
# test-push-smoke.sh — headless smoke test for /plate push orchestration.
#
# Exercises: paths.sh, lock.sh, instance_rw.py, snapshot-stash.sh, push.sh
#   JSON-write body (plate mutation + INPUT_FILE generation).
#
# Skips: tmux launch + claude spawn (requires live tools). We stub `tmux`
# and `claude` with no-op fakes and verify push.sh exits 0 after writing
# state.
set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; RESET=$'\033[0m'
FAIL=0
fail() { echo "${RED}FAIL:${RESET} $*"; FAIL=$((FAIL+1)); }
pass() { echo "${GREEN}PASS:${RESET} $*"; }

CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export CLAUDE_PLUGIN_ROOT

TMPTEST=$(mktemp -d /tmp/plate-test-push.XXXXXX)
trap 'rm -rf "$TMPTEST"' EXIT

# Stub tmux + claude
STUB_BIN="$TMPTEST/stub-bin"
mkdir -p "$STUB_BIN"
cat > "$STUB_BIN/tmux" <<'STUB'
#!/usr/bin/env bash
# Record invocations then exit 0 (do not actually spawn a session)
echo "tmux $*" >> "$TMPTEST/tmux-calls.log"
case "$1" in
  has-session) exit 1 ;;  # pretend plate session does not exist
  *) exit 0 ;;
esac
STUB
cat > "$STUB_BIN/claude" <<'STUB'
#!/usr/bin/env bash
echo "claude $*" >> "$TMPTEST/claude-calls.log"
exit 0
STUB
chmod +x "$STUB_BIN"/*

# Put stubs on PATH, export TMPTEST so stubs can write logs
export PATH="$STUB_BIN:$PATH"
export TMPTEST

# Initialize a test repo
cd "$TMPTEST"
git init -q
git config user.email test@test.com
git config user.name "plate test"
echo "baseline" > README.md
git add README.md
git commit -q -m "init"

# Make uncommitted changes
echo "in progress" >> README.md
echo "new file" > feature.txt

# Set up plugin data dir
export CLAUDE_PLUGIN_DATA="$TMPTEST/.plugin-data"
mkdir -p "$CLAUDE_PLUGIN_DATA"

# Source libs + create instance
. "$CLAUDE_PLUGIN_ROOT/scripts/lib/paths.sh"
plate_discover_root
plate_ensure_dirs

python3 "$CLAUDE_PLUGIN_ROOT/python/instance_rw.py" create-instance \
  "$PLATE_ROOT/instances/push-smoke.json" push-smoke "$TMPTEST" main

# Run push.sh
if bash "$CLAUDE_PLUGIN_ROOT/scripts/push.sh" push-smoke "" "$TMPTEST"; then
  pass "push.sh exited 0"
else
  fail "push.sh exited non-zero"
fi

# Assert stash ref exists
REF_COUNT=$(git for-each-ref refs/plates/push-smoke/ | wc -l | tr -d ' ')
if [ "$REF_COUNT" = "1" ]; then
  pass "exactly 1 stash ref under refs/plates/push-smoke/"
else
  fail "expected 1 stash ref, found $REF_COUNT"
fi

# Assert instance JSON has 1 plate in stack
STACK_LEN=$(python3 -c "
import json
d=json.load(open('$PLATE_ROOT/instances/push-smoke.json'))
print(len(d.get('stack',[])))
")
if [ "$STACK_LEN" = "1" ]; then
  pass "instance stack has 1 plate"
else
  fail "expected stack len 1, got $STACK_LEN"
fi

# Assert INPUT_FILE was created with bg-agent prompt prepended
INPUT_COUNT=$(find "$PLATE_ROOT/inputs" -name 'push-smoke_*.txt' | wc -l | tr -d ' ')
if [ "$INPUT_COUNT" = "1" ]; then
  pass "INPUT_FILE created"
  INPUT_FILE=$(find "$PLATE_ROOT/inputs" -name 'push-smoke_*.txt' | head -1)
  if head -5 "$INPUT_FILE" | grep -q "You are a background agent"; then
    pass "bg-agent prompt prepended to INPUT_FILE"
  else
    fail "bg-agent prompt NOT prepended"
  fi
  if grep -q '"convo_id": "push-smoke"' "$INPUT_FILE"; then
    pass "job payload written to INPUT_FILE"
  else
    fail "job payload missing from INPUT_FILE"
  fi
else
  fail "expected 1 INPUT_FILE, found $INPUT_COUNT"
fi

# Assert tmux stub was called with new-session
if grep -q 'tmux new-session.*-s plate' "$TMPTEST/tmux-calls.log" 2>/dev/null; then
  pass "tmux new-session -s plate invoked"
else
  fail "tmux new-session not invoked"
  cat "$TMPTEST/tmux-calls.log" 2>/dev/null || true
fi

# Assert permissions.local.json was seeded (state 1: fresh install)
if [ -f "$CLAUDE_PLUGIN_DATA/permissions.local.json" ]; then
  pass "permissions.local.json seeded into CLAUDE_PLUGIN_DATA"
else
  fail "permissions.local.json not seeded"
fi
if [ -f "$CLAUDE_PLUGIN_DATA/permissions.default.sha256" ]; then
  pass "prior sha recorded"
else
  fail "prior sha not recorded"
fi

# Assert generated settings.json has expanded permissions (no ${PLATE_ROOT} literal)
# push.sh uses `mktemp -d /tmp/plate.XXXXXX` — grab the newest one created
# inside this test run.
SETTINGS=$(ls -dt /tmp/plate.*/settings.json 2>/dev/null | head -1)
if [ -n "$SETTINGS" ] && [ -f "$SETTINGS" ]; then
  if grep -q '\${PLATE_ROOT}' "$SETTINGS"; then
    fail "settings.json still has unexpanded \${PLATE_ROOT}"
  else
    pass "placeholders expanded in settings.json"
  fi
  if grep -q '"deny"' "$SETTINGS" && grep -q 'Bash' "$SETTINGS"; then
    pass "Bash(*) denied in worker settings.json"
  else
    fail "Bash(*) deny rule missing from settings.json"
  fi
else
  fail "generated settings.json not found for inspection"
fi

# Files in plate metadata should include README.md
FILES=$(python3 -c "
import json
d=json.load(open('$PLATE_ROOT/instances/push-smoke.json'))
print(','.join(d['stack'][0].get('files', [])))
")
if echo "$FILES" | grep -q "README.md"; then
  pass "plate.files contains README.md"
else
  fail "plate.files missing README.md (got: $FILES)"
fi

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "${RED}$FAIL test(s) failed${RESET}"
  exit 1
fi
echo ""
echo "${GREEN}All push smoke tests passed.${RESET}"
