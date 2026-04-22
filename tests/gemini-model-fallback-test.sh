#!/bin/bash
# gemini-model-fallback-test.sh — verify gemini falls back to
# gemini-3-flash-preview when the primary model is rate-limited.
#
# Mocks the `gemini` CLI with a shell script that fails unless `-m
# gemini-3-flash-preview` is passed, then asserts:
#   1. debate_gemini_working_model returns rc=0 and echoes the fallback.
#   2. Calling with a mock that succeeds without `-m` echoes "" (default).
#   3. Calling with a mock that always fails returns rc=1.
#
# This insulates us from real gemini quota state — the test is deterministic
# regardless of whether the operator's actual gemini key is healthy.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0
pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS + 1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL + 1)); }

# Mock gemini factory: emits a script whose args-pattern determines success.
# Args:
#   $1 = directory to place the mock in (prepended to PATH by caller)
#   $2 = behavior: "always_ok" | "always_fail" | "needs_flash_preview"
make_mock_gemini() {
  local dir="$1" behavior="$2"
  mkdir -p "$dir"
  cat > "$dir/gemini" <<EOF
#!/bin/bash
# Mock gemini — behavior: $behavior
behavior="$behavior"
EOF
  cat >> "$dir/gemini" <<'EOF'
case "$behavior" in
  always_ok)
    exit 0
    ;;
  always_fail)
    echo "QUOTA_EXHAUSTED (mocked)" >&2
    exit 1
    ;;
  needs_flash_preview)
    # Succeed iff "-m gemini-3-flash-preview" appears in args.
    if printf '%s\n' "$@" | grep -q -x -- "-m" && \
       printf '%s\n' "$@" | grep -q -x "gemini-3-flash-preview"; then
      exit 0
    fi
    echo "QUOTA_EXHAUSTED (mocked — try flash-preview)" >&2
    exit 1
    ;;
esac
EOF
  chmod +x "$dir/gemini"
}

# Runs debate_gemini_working_model with a given mock behavior and reports
# rc + stdout.
run_under_mock() {
  local behavior="$1"
  local mock_dir
  mock_dir=$(mktemp -d /tmp/gemini-mock.XXXXXX)
  make_mock_gemini "$mock_dir" "$behavior"

  # Source ONLY the functions we need, in a subshell to avoid side effects.
  local out rc
  out=$(
    PATH="$mock_dir:$PATH"
    # Minimal harness: source silencers (for hide_errors), then debate.sh
    # function definitions, then invoke the function under test.
    source "$REPO_ROOT/common/scripts/silencers.sh"
    source "$REPO_ROOT/skills/debate/scripts/debate.sh"
    # debate.sh globals that the function may reference in log paths:
    LOG_FILE=/dev/null
    debate_gemini_working_model
  )
  rc=$?
  rm -rf "$mock_dir"
  printf '%s\n%s\n' "$rc" "$out"
}

# === Case 1: primary model succeeds — no fallback needed ===
result=$(run_under_mock always_ok)
rc=$(printf '%s' "$result" | head -1)
model=$(printf '%s' "$result" | tail -n +2)
if [ "$rc" = "0" ] && [ -z "$model" ]; then
  pass "primary works → rc=0 and empty model (use default)"
else
  fail "primary works case: rc=$rc model='$model' (expected rc=0 empty)"
fi

# === Case 2: primary fails, fallback succeeds — echoes fallback model ===
result=$(run_under_mock needs_flash_preview)
rc=$(printf '%s' "$result" | head -1)
model=$(printf '%s' "$result" | tail -n +2)
if [ "$rc" = "0" ] && [ "$model" = "gemini-3-flash-preview" ]; then
  pass "primary fails, flash-preview works → rc=0 and model=gemini-3-flash-preview"
else
  fail "fallback case: rc=$rc model='$model' (expected rc=0 'gemini-3-flash-preview')"
fi

# === Case 3: both fail — returns rc=1 ===
result=$(run_under_mock always_fail)
rc=$(printf '%s' "$result" | head -1)
if [ "$rc" = "1" ]; then
  pass "both fail → rc=1"
else
  fail "both-fail case: rc=$rc (expected 1)"
fi

printf "gemini_model_fallback_tests: PASS=%d FAIL=%d\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
