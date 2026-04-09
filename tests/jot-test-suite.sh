#!/bin/bash
# jot-test-suite.sh — comprehensive canary tests for jot.sh + the four
# Phase 2 hook scripts. Does NOT spawn real claude or osascript — uses
# JOT_SKIP_LAUNCH=1 for the Phase 1 portion and tests the hook scripts
# directly against a stub tmux session for the Phase 2 portion.
#
# Usage: bash jot-test-suite.sh [phase1|phase2|all]
#
# Environment:
#   JOT_SCRIPT         Path to jot.sh under test (default: $CLAUDE_PLUGIN_ROOT/scripts/jot.sh)
#   JOT_SCRIPTS_DIR    Path to the scripts/ dir   (default: $CLAUDE_PLUGIN_ROOT/scripts)
#   JOT_TEST_TRANSCRIPT  Absolute path to a .jsonl transcript for the capture tests
#   CLAUDE_PLUGIN_ROOT / CLAUDE_PLUGIN_DATA — must be set for jot.sh to run (it asserts)
set -uo pipefail

# Paths under test. Default to the installed plugin layout via CLAUDE_PLUGIN_ROOT;
# allow an explicit override so you can point the suite at a work-in-progress
# checkout outside the installed plugin.
: "${CLAUDE_PLUGIN_ROOT:?set CLAUDE_PLUGIN_ROOT to the jot plugin install dir (or the repo root for local test runs)}"
: "${CLAUDE_PLUGIN_DATA:=${CLAUDE_PLUGIN_ROOT}/.test-data}"
mkdir -p "$CLAUDE_PLUGIN_DATA"
export CLAUDE_PLUGIN_ROOT CLAUDE_PLUGIN_DATA

JOT="${JOT_SCRIPT:-${CLAUDE_PLUGIN_ROOT}/scripts/jot.sh}"
SCRIPTS="${JOT_SCRIPTS_DIR:-${CLAUDE_PLUGIN_ROOT}/scripts}"
CAPTURE="$SCRIPTS/capture-conversation.py"
TRANSCRIPT="${JOT_TEST_TRANSCRIPT:-}"
STUB_SESSION="jot-test-stub"
PASS=0
FAIL=0

# Point jot.sh's LOG_FILE at a throwaway file so synthetic test runs
# don't pollute the real log with bogus entries.
export JOT_LOG_FILE="/tmp/jot-test-log.$$.txt"

pass() { printf "PASS: %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "FAIL: %s\n" "$1"; FAIL=$((FAIL+1)); }

cleanup() {
  tmux kill-session -t "$STUB_SESSION" 2>/dev/null || true
  for d in /tmp/jot.*; do [ -d "$d" ] && rm -rf "$d"; done 2>/dev/null
  rm -rf /tmp/jot-test-* /tmp/empty.jsonl 2>/dev/null
  rm -f "$JOT_LOG_FILE" "$JOT_LOG_FILE".* 2>/dev/null
}
trap cleanup EXIT
touch /tmp/empty.jsonl

# ════════════════════════════════════════════════════════════════════════
# PHASE 1 TESTS (run with JOT_SKIP_LAUNCH=1 — no Phase 2 launch)
# ════════════════════════════════════════════════════════════════════════
phase1_tests() {
  echo "═══ Phase 1 tests (JOT_SKIP_LAUNCH=1) ═══"
  local TEST_DIR
  TEST_DIR=$(mktemp -d /tmp/jot-test-p1.XXXXXX)
  export JOT_SKIP_LAUNCH=1
  cd "$TEST_DIR"
  git init -q

  # 1a-d: canary capture + section presence
  echo '{"prompt":"/jot CANARY_42","transcript_path":"/tmp/empty.jsonl","cwd":"'$TEST_DIR'","session_id":"t"}' \
    | bash "$JOT" >/dev/null 2>&1
  grep -rq "CANARY_42" "$TEST_DIR/Todos/" && pass "1a: canary captured" || fail "1a"
  grep -rq "## Git State" "$TEST_DIR/Todos/" && pass "1b: Git State present" || fail "1b"
  grep -rq "## Transcript Path" "$TEST_DIR/Todos/" && pass "1c: Transcript Path present" || fail "1c"
  grep -rq "## Instructions" "$TEST_DIR/Todos/" && pass "1d: Instructions present" || fail "1d"

  # 1e: Instructions appears at the TOP (line 3, after # Jot Task + blank)
  local F
  F=$(ls "$TEST_DIR"/Todos/*_input.txt | head -1)
  local INSTR_LINE GIT_LINE
  INSTR_LINE=$(grep -n '^## Instructions' "$F" | head -1 | cut -d: -f1)
  GIT_LINE=$(grep -n '^## Git State' "$F" | head -1 | cut -d: -f1)
  if [ -n "$INSTR_LINE" ] && [ -n "$GIT_LINE" ] && [ "$INSTR_LINE" -lt "$GIT_LINE" ]; then
    pass "1e: Instructions appears BEFORE Git State (line $INSTR_LINE < $GIT_LINE)"
  else
    fail "1e: Instructions not at top (INSTR=$INSTR_LINE GIT=$GIT_LINE)"
  fi

  # 2: /jotfoo passes through silently
  R=$(echo '{"prompt":"/jotfoo","transcript_path":"/tmp/empty.jsonl","cwd":"'$TEST_DIR'","session_id":"t"}' | bash "$JOT" 2>&1)
  [ -z "$R" ] && pass "2: /jotfoo passes through" || fail "2: $R"

  # 3: bare /jot returns 'no idea provided'
  R=$(echo '{"prompt":"/jot","transcript_path":"/tmp/empty.jsonl","cwd":"'$TEST_DIR'","session_id":"t"}' | bash "$JOT" 2>&1)
  echo "$R" | grep -q "no idea provided" && pass "3: bare /jot" || fail "3: $R"

  # 4: non-/jot pass-through
  R=$(echo '{"prompt":"hello","transcript_path":"/tmp/empty.jsonl","cwd":"'$TEST_DIR'","session_id":"t"}' | bash "$JOT" 2>&1)
  [ -z "$R" ] && pass "4: pass-through silent" || fail "4: $R"

  # 5: durability in non-git dir
  rm -rf /tmp/jot-test-nongit; mkdir -p /tmp/jot-test-nongit
  echo '{"prompt":"/jot DURABLE","transcript_path":"/tmp/missing.jsonl","cwd":"/tmp/jot-test-nongit","session_id":"t"}' | bash "$JOT" >/dev/null 2>&1
  grep -rq "DURABLE" /tmp/jot-test-nongit/Todos/ && pass "5: durable in non-git" || fail "5"
  rm -rf /tmp/jot-test-nongit

  # 6: multi-line indentation preserved
  printf '%s' '{"prompt":"/jot def foo():\n    return 42","transcript_path":"/tmp/empty.jsonl","cwd":"'$TEST_DIR'","session_id":"t"}' | bash "$JOT" >/dev/null 2>&1
  grep -rq "    return 42" "$TEST_DIR"/Todos/ && pass "6: indentation preserved" || fail "6"

  # 7: log gating — non-/jot prompts not logged (check the test log, not real)
  PRE=$(wc -l < "$JOT_LOG_FILE" 2>/dev/null || echo 0)
  TOK="PRIVATE_SECRET_$$"
  echo "{\"prompt\":\"$TOK\",\"transcript_path\":\"/tmp/empty.jsonl\",\"cwd\":\"$TEST_DIR\",\"session_id\":\"t\"}" | bash "$JOT" >/dev/null 2>&1
  POST=$(wc -l < "$JOT_LOG_FILE" 2>/dev/null || echo 0)
  [ "$PRE" = "$POST" ] && pass "7a: non-/jot did not grow log" || fail "7a"
  grep -q "$TOK" "$JOT_LOG_FILE" 2>/dev/null && fail "7b: secret leaked" || pass "7b: secret NOT in log"

  # 8: requirements check fires when tools missing
  # env -i must forward the plugin-env vars or jot.sh's assertions will exit early.
  R=$(env -i HOME="$HOME" PATH="/usr/bin:/bin" \
        CLAUDE_PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT" \
        CLAUDE_PLUGIN_DATA="$CLAUDE_PLUGIN_DATA" \
        JOT_SKIP_LAUNCH=1 JOT_LOG_FILE="$JOT_LOG_FILE" \
        bash "$JOT" <<< "{\"prompt\":\"/jot req\",\"transcript_path\":\"/tmp/empty.jsonl\",\"cwd\":\"$TEST_DIR\",\"session_id\":\"x\"}" 2>&1)
  echo "$R" | grep -q '"decision"' && echo "$R" | grep -q '"block"' && pass "8a: req check blocked" || fail "8a: $R"
  echo "$R" | grep -q 'jot needs:' && pass "8b: req check msg" || fail "8b"

  # 9: capture-conversation extracts 5 user turns (skipped if no test transcript)
  if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
    TURNS=$(python3 "$CAPTURE" "$TRANSCRIPT" 2>/dev/null | grep -c '^=== USER (turn')
    [ "$TURNS" = "5" ] && pass "9: capture extracts 5 user turns" || fail "9: got $TURNS"
  else
    echo "SKIP: 9: no JOT_TEST_TRANSCRIPT env var set, skipping capture test"
  fi

  # 10: Instructions does NOT tell claude to run rm
  F=$(ls "$TEST_DIR"/Todos/*_input.txt | head -1)
  grep -qE 'run: rm |FINAL step.*rm |rm \$\{INPUT' "$F" && fail "10: rm command in Instructions" || pass "10: no rm command"

  # 11: Instructions DOES mention PROCESSED marker
  grep -q 'PROCESSED:' "$F" && pass "11: PROCESSED marker mentioned" || fail "11"

  cd /tmp
  rm -rf "$TEST_DIR"
  unset JOT_SKIP_LAUNCH
}

# ════════════════════════════════════════════════════════════════════════
# PHASE 2 TESTS (hook scripts directly, against stub tmux session)
# ════════════════════════════════════════════════════════════════════════
phase2_tests() {
  echo
  echo "═══ Phase 2 tests (hook scripts against stub tmux) ═══"

  # Ensure we're in a stable CWD (Phase 1 may have just deleted its test dir).
  cd /tmp

  # Set up stub tmux session that just runs a long-lived shell (no real
  # claude). The hook scripts will send-keys to this session.
  tmux kill-session -t "$STUB_SESSION" 2>/dev/null || true
  tmux new-session -d -s "$STUB_SESSION" -n stub "bash -i"
  tmux set-option -t "$STUB_SESSION" remain-on-exit on >/dev/null

  local STATE_DIR
  STATE_DIR=$(mktemp -d /tmp/jot-test-state.XXXXXX)
  local QUEUE="$STATE_DIR/queue.txt"
  local ACTIVE="$STATE_DIR/active_job.txt"
  local AUDIT="$STATE_DIR/audit.log"
  touch "$QUEUE" "$ACTIVE" "$AUDIT"

  # ── lock helper round-trip ────────────────────────────────────────────
  . "$SCRIPTS/jot-state-lib.sh"
  jot_lock_acquire "$STATE_DIR/test.lock" 1 && pass "P2.lock1: acquire" || fail "P2.lock1"
  jot_lock_acquire "$STATE_DIR/test.lock" 1 && fail "P2.lock2: 2nd acquire should fail" || pass "P2.lock2: 2nd acquire blocked"
  jot_lock_release "$STATE_DIR/test.lock"
  jot_lock_acquire "$STATE_DIR/test.lock" 1 && pass "P2.lock3: re-acquire after release" || fail "P2.lock3"
  jot_lock_release "$STATE_DIR/test.lock"

  # ── jot_queue_pop_first round-trip ────────────────────────────────────
  printf 'first\nsecond\nthird\n' > "$QUEUE"
  : > "$ACTIVE"
  popped=$(jot_queue_pop_first "$STATE_DIR")
  [ "$popped" = "first" ] && pass "P2.pop1: pop returns first line" || fail "P2.pop1: $popped"
  [ "$(cat $ACTIVE)" = "first" ] && pass "P2.pop2: active_job has first" || fail "P2.pop2"
  [ "$(wc -l < $QUEUE | tr -d ' ')" = "2" ] && pass "P2.pop3: queue has 2 lines left" || fail "P2.pop3"
  : > "$ACTIVE"
  : > "$QUEUE"

  # ── jot-stop.sh: SUCCESS path (PROCESSED marker present) ─────────────
  # New architecture: jot-stop takes INPUT_FILE, TMUX_TARGET, STATE_DIR.
  # It appends SUCCESS to audit.log and schedules a background window kill.
  # We can't observe the window kill here (no real tmux), but we CAN verify
  # the audit line, which is the canonical source of truth.
  PROCESSED_TEST="/tmp/jot-test-processed.txt"
  printf 'PROCESSED: Todos/foo.md\n' > "$PROCESSED_TEST"
  : > "$AUDIT"
  bash "$SCRIPTS/jot-stop.sh" "$PROCESSED_TEST" "$STUB_SESSION" "$STATE_DIR" 2>&1
  grep -q "SUCCESS $PROCESSED_TEST" "$AUDIT" && pass "P2.stop1: SUCCESS logged" || fail "P2.stop1: audit=$(cat $AUDIT)"
  rm -f "$PROCESSED_TEST"

  # ── jot-stop.sh: FAIL path (no PROCESSED marker) ─────────────────────
  PENDING_TEST="/tmp/jot-test-pending.txt"
  printf '# Jot Task\n## Idea\nfoo\n' > "$PENDING_TEST"
  : > "$AUDIT"
  bash "$SCRIPTS/jot-stop.sh" "$PENDING_TEST" "$STUB_SESSION" "$STATE_DIR" 2>&1
  grep -q "FAIL $PENDING_TEST" "$AUDIT" && pass "P2.stop2: FAIL logged" || fail "P2.stop2: audit=$(cat $AUDIT)"
  rm -f "$PENDING_TEST"

  # ── jot-stop.sh: FAIL path (input.txt missing entirely) ──────────────
  MISSING_INPUT="/tmp/jot-test-missing.txt"
  rm -f "$MISSING_INPUT"
  : > "$AUDIT"
  bash "$SCRIPTS/jot-stop.sh" "$MISSING_INPUT" "$STUB_SESSION" "$STATE_DIR" 2>&1
  grep -q "FAIL $MISSING_INPUT" "$AUDIT" && pass "P2.stop3: FAIL on missing input.txt" || fail "P2.stop3: audit=$(cat $AUDIT)"

  # ── audit.log rotation ───────────────────────────────────────────────
  python3 -c 'print("\n".join(f"line{i}" for i in range(1500)))' > "$AUDIT"
  jot_audit_rotate "$AUDIT" 1000
  LINES=$(wc -l < "$AUDIT" | tr -d ' ')
  [ "$LINES" = "1000" ] && pass "P2.rotate: trimmed to 1000 lines" || fail "P2.rotate: got $LINES"

  # ── jot-session-end.sh: safety guard refuses non-/tmp/jot.* paths ────
  R=$(bash "$SCRIPTS/jot-session-end.sh" /etc 2>&1)
  echo "$R" | grep -q "refusing to rm" && [ -d /etc ] && pass "P2.end1: safety guard works" || fail "P2.end1: $R"

  # ── jot-session-end.sh: legitimate /tmp/jot.* removal ────────────────
  TMP=$(mktemp -d /tmp/jot.XXXXXX)
  echo '{}' > "$TMP/settings.json"
  bash "$SCRIPTS/jot-session-end.sh" "$TMP" 2>&1
  [ ! -d "$TMP" ] && pass "P2.end2: legitimate cleanup" || fail "P2.end2: $TMP still exists"

  # ── jot.sh SKIP_LAUNCH path: writes input.txt but skips Phase 2 entirely
  P2_TEST_DIR=$(mktemp -d /tmp/jot-test-enq.XXXXXX)
  cd "$P2_TEST_DIR"; git init -q
  export JOT_SKIP_LAUNCH=1
  echo '{"prompt":"/jot skip test","transcript_path":"/tmp/empty.jsonl","cwd":"'$P2_TEST_DIR'","session_id":"t"}' | bash "$JOT" >/dev/null 2>&1
  unset JOT_SKIP_LAUNCH
  # SKIP_LAUNCH exits BEFORE phase2_enqueue_and_launch, so:
  #   - Phase 1 output (input.txt) MUST exist
  #   - State dir / queue.txt MUST NOT exist (Phase 2 didn't run)
  ls "$P2_TEST_DIR"/Todos/*_input.txt >/dev/null 2>&1 && pass "P2.skip1: Phase 1 output exists" || fail "P2.skip1: no input.txt"
  [ ! -d "$P2_TEST_DIR/Todos/.jot-state" ] && pass "P2.skip2: state dir NOT created (Phase 2 skipped)" || fail "P2.skip2: state dir leaked"
  cd /tmp
  rm -rf "$P2_TEST_DIR"

  rm -rf "$STATE_DIR"
  tmux kill-session -t "$STUB_SESSION" 2>/dev/null
}

case "${1:-all}" in
  phase1) phase1_tests ;;
  phase2) phase2_tests ;;
  all)    phase1_tests; phase2_tests ;;
  *) echo "usage: $0 [phase1|phase2|all]"; exit 1 ;;
esac

echo
echo "════════════════════════════════════════"
echo "TOTAL:  PASS=$PASS  FAIL=$FAIL"
echo "════════════════════════════════════════"
[ "$FAIL" = "0" ]
