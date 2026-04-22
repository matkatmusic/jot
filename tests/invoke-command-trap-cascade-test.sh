#!/bin/bash
# invoke-command-trap-cascade-test.sh — verify invoke_command + ERR trap
# produces exactly one clean diagnostic on failure.
#
# With `set -eE` active (as required by orchestrator-err-trap-test), the ERR
# trap is inherited into the `$(...)` subshell inside `invoke_command`. If the
# subshell's failing command triggers the trap there, its diagnostic output
# gets captured into `$output`, then re-emitted by invoke_command's success
# branch — producing duplicate block messages on stdout AND leaking the raw
# command stderr. The caller's parent-shell trap then fires on the *next*
# dependent command, adding a third diagnostic.
#
# This test simulates a real hook's pattern (set -eEuo pipefail + ERR trap +
# invoke_command with a failing command) and asserts:
#   1. Exactly one block JSON is emitted.
#   2. No raw command stderr leaks alongside the block.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

tmp=$(mktemp /tmp/invoke-cascade.XXXXXX.sh)
cat > "$tmp" <<EOF
#!/bin/bash
set -eEuo pipefail
source "$REPO_ROOT/common/scripts/invoke_command.sh"
source "$REPO_ROOT/common/scripts/hook-json.sh"
trap 'rc=\$?; [ "\$BASH_SUBSHELL" -gt 0 ] && exit "\$rc"; emit_block "test crashed (rc=\$rc)"; exit 0' ERR

# Simulate a command guaranteed to fail with a recognizable stderr marker.
failing_cmd() { echo "RAW_STDERR_MARKER" >&2; return 42; }

outer_fn() {
  invoke_command failing_cmd
}
outer_fn
EOF
out_stdout=$(mktemp /tmp/invoke-cascade-out.XXXXXX)
out_stderr=$(mktemp /tmp/invoke-cascade-err.XXXXXX)
bash "$tmp" >"$out_stdout" 2>"$out_stderr"
rc=$?
rm -f "$tmp"

stdout_content=$(cat "$out_stdout")
stderr_content=$(cat "$out_stderr")
rm -f "$out_stdout" "$out_stderr"

# A hook's stdout is the decision channel — it must contain exactly one
# block JSON and nothing else leaked from the failing command.
block_count=$(printf '%s\n' "$stdout_content" | grep -c '"decision"' || true)
if [ "$block_count" -eq 1 ]; then
  pass "stdout emits exactly one block decision on failure"
else
  fail "expected 1 block decision on stdout, got $block_count"
  printf 'actual stdout:\n%s\n---\n' "$stdout_content" >&2
fi

if printf '%s\n' "$stdout_content" | grep -q "RAW_STDERR_MARKER"; then
  fail "raw command stderr leaked to hook stdout (contaminates decision channel)"
  printf 'actual stdout:\n%s\n---\n' "$stdout_content" >&2
else
  pass "raw command stderr does not leak to hook stdout"
fi

# The diagnostic on stderr is desired — it's how operators see WHAT broke.
# Verify invoke_command's diagnostic actually reaches stderr.
if printf '%s\n' "$stderr_content" | grep -q "RAW_STDERR_MARKER"; then
  pass "failed-command diagnostic reaches stderr (for operator visibility)"
else
  fail "invoke_command diagnostic missing from stderr — operator has no visibility into what broke"
  printf 'actual stderr:\n%s\n---\n' "$stderr_content" >&2
fi

if [ "$rc" -eq 0 ]; then
  pass "exits rc=0 after trap handles failure"
else
  fail "expected rc=0 after trap, got rc=$rc"
fi

printf "invoke_command_trap_tests: PASS=%d FAIL=%d\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
