#!/bin/bash
# orchestrator-err-trap-test.sh — verify ERR traps propagate into functions
# for every hook orchestrator.
#
# Bash 3.2 (macOS default) does not inherit ERR traps into functions unless
# `set -E` (aka `set -o errtrace`) is enabled. Without it, a failure inside
# a function silently exits rc=1 with the trap handler never running — the
# exact symptom that masked the /debate tmux-target bug: hook exited non-zero
# with empty stderr, so Claude Code reported "failed with non-blocking status
# code: no stderr output" and the user had no signal about what went wrong.
#
# This test guards that every orchestrator entry point keeps -E set so any
# future failure inside a function produces a visible diagnostic.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

ORCHESTRATORS=(
  "$REPO_ROOT/scripts/orchestrator.sh"
  "$REPO_ROOT/skills/debate/scripts/debate-orchestrator.sh"
  "$REPO_ROOT/skills/jot/scripts/jot-orchestrator.sh"
  "$REPO_ROOT/skills/plate/scripts/plate-orchestrator.sh"
)

# Static check: every orchestrator must enable errtrace (set -E or
# equivalents). The grep matches `set -...E...` or `set -o errtrace`.
for f in "${ORCHESTRATORS[@]}"; do
  name=$(basename "$f")
  if ! [ -f "$f" ]; then
    fail "$name does not exist"
    continue
  fi
  if grep -Eq '^set [^#]*-[a-zA-Z]*E|^set -o errtrace' "$f"; then
    pass "$name enables ERR trap inheritance"
  else
    fail "$name missing -E / errtrace — ERR trap will not fire inside functions on bash 3.2"
  fi
done

# Dynamic check: confirm -E actually propagates the trap in the current bash.
# The trap prints a marker WITHOUT `exit 0` — an exit inside the trap would
# run in the `$(...)` subshell and swallow the failure before the parent's
# ERR state is reached, making the test pass spuriously.
tmp=$(mktemp /tmp/err-trap-test.XXXXXX.sh)
cat > "$tmp" <<'EOF'
set -eEuo pipefail
trap 'echo "TRAP_FIRED rc=$?"' ERR
inner() {
  local output
  output=$(false 2>&1)
  echo "POST_ASSIGN_INNER"
}
inner
echo "POST_INNER_CALL"
EOF
dyn_out=$(bash "$tmp" 2>&1) || true
rm -f "$tmp"
if printf '%s' "$dyn_out" | grep -q "TRAP_FIRED"; then
  pass "ERR trap fires inside function with set -eE ($(bash --version | head -1 | awk '{print $4}'))"
else
  fail "ERR trap did NOT fire inside function under set -eE — output was: $dyn_out"
fi

# Negative control: without -E, the trap must NOT fire. This proves that -E
# is load-bearing and the static check above is testing something real.
tmp=$(mktemp /tmp/err-trap-test.XXXXXX.sh)
cat > "$tmp" <<'EOF'
set -euo pipefail
trap 'echo "TRAP_FIRED rc=$?"' ERR
inner() {
  local output
  output=$(false 2>&1)
  echo "POST_ASSIGN_INNER"
}
inner
echo "POST_INNER_CALL"
EOF
neg_out=$(bash "$tmp" 2>&1) || true
rm -f "$tmp"
if printf '%s' "$neg_out" | grep -q "TRAP_FIRED"; then
  fail "negative control: trap fired without -E (test cannot distinguish fixed vs broken)"
else
  pass "negative control: trap correctly silent without -E"
fi

printf "orchestrator_err_trap_tests: PASS=%d FAIL=%d\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
