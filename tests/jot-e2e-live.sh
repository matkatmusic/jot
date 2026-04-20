#!/bin/bash
# jot-e2e-live.sh — headless end-to-end test runner for the jot skill.
#
# Unlike jot-test-suite.sh (unit tests with stubbed tmux + JOT_SKIP_LAUNCH=1),
# this helper fires REAL /jot invocations against a REAL tmux-pinned claude
# and polls for PROCESSED: markers + audit.log SUCCESS lines.
#
# Usage:
#   jot-e2e-live.sh <scenario>   # single scenario
#   jot-e2e-live.sh all          # run all 6 scenarios
#   jot-e2e-live.sh cleanup      # wipe test state, no tests run
#
# Scenarios: cold_start, warm_idle, transcript_fallback, cross_project,
#            crash_recovery, diag_collector
#
# Exit: 0 if all requested scenarios PASS, 1 otherwise.

set -uo pipefail

# Plugin-env vars: required (jot.sh asserts). Default to derived-from-this-file
# so the suite can run from a local checkout without a formal plugin install.
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/.." && pwd)"
: "${CLAUDE_PLUGIN_ROOT:=$REPO_ROOT}"
: "${CLAUDE_PLUGIN_DATA:=$REPO_ROOT/.e2e-data}"
mkdir -p "$CLAUDE_PLUGIN_DATA"
export CLAUDE_PLUGIN_ROOT CLAUDE_PLUGIN_DATA

# Test fixtures. Both are env-overridable.
# TEST_PROJECT must be an existing, Claude Code-trusted directory for the
# primary scenarios. CROSS_PROJECT is a second dir used by the cross_project
# scenario only — default under CLAUDE_PLUGIN_DATA so it's isolated per-install.
TEST_PROJECT="${TEST_PROJECT:?set TEST_PROJECT to an absolute path for a Claude Code-trusted test project}"
CROSS_PROJECT="${CROSS_PROJECT:-${CLAUDE_PLUGIN_DATA}/e2e/cross-project-test}"

SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts"
# shellcheck source=../common/scripts/tmux-launcher.sh
. "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
JOT_SH="$SCRIPTS_DIR/jot-orchestrator.sh"
DIAG_SH="$THIS_DIR/jot-diag-collect.sh"
JOB_TIMEOUT="${JOB_TIMEOUT:-300}"

# Scenario results captured for summary output.
declare -a RESULTS

# ── Helpers ───────────────────────────────────────────────────────────────

_ts() { date +%s; }
_iso() { date +%Y-%m-%dT%H-%M-%S; }

_slug_cwd() {
  # Claude Code's per-project transcript dir format: path with "/" → "-"
  # and a leading "-" for the absolute path's leading slash.
  printf '%s' "$1" | sed 's|/|-|g'
}

_state_dir() { printf '%s/Todos/.jot-state' "$1"; }

_audit_log() { printf '%s/Todos/.jot-state/audit.log' "$1"; }

fire_jot() {
  # Args: <project_dir> <idea>
  # Side effects: writes fixture .jsonl transcript, pipes HOOK_INPUT JSON to jot.sh.
  # Returns: newest *_input.txt path in <project_dir>/Todos/ (after fire).
  local project="$1" idea="$2"
  local session_id slug transcripts_dir transcript
  session_id=$(uuidgen | tr 'A-Z' 'a-z')
  slug=$(_slug_cwd "$project")
  transcripts_dir="$HOME/.claude/projects/$slug"
  transcript="$transcripts_dir/$session_id.jsonl"

  mkdir -p "$transcripts_dir"
  # Minimal one-user-turn fixture so capture-conversation.py has something to read.
  printf '{"type":"user","uuid":"%s","sessionId":"%s","timestamp":"%s","message":{"role":"user","content":[{"type":"text","text":"fixture turn for jot e2e — generic project context"}]}}\n' \
    "$(uuidgen)" "$session_id" "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" > "$transcript"

  # Marker so we can find the *_input.txt the hook writes (mtime-based).
  local marker
  marker=$(mktemp /tmp/jot-e2e-marker.XXXXXX)
  touch -d "-1 second" "$marker" 2>/dev/null || touch -t "$(date -v-1S +%Y%m%d%H%M.%S)" "$marker"

  # HOOK_INPUT payload. jot.sh reads via: INPUT=$(cat); jq '.prompt/.cwd/...'
  local payload
  payload=$(jq -nc \
    --arg sid "$session_id" \
    --arg tp "$transcript" \
    --arg cwd "$project" \
    --arg prompt "/jot $idea" \
    '{session_id:$sid,transcript_path:$tp,cwd:$cwd,prompt:$prompt,hook_event_name:"UserPromptSubmit"}')

  printf '%s' "$payload" | bash "$JOT_SH" >/dev/null 2>&1 || true

  # Find the newest input.txt created after the marker.
  local found
  found=$(find "$project/Todos" -maxdepth 1 -name '*_input.txt' -newer "$marker" -type f 2>/dev/null | sort | tail -1)
  rm -f "$marker"
  printf '%s' "$found"
}

wait_for_processed() {
  # Args: <input_txt_path> [timeout_sec=$JOB_TIMEOUT]
  local path="$1" timeout="${2:-$JOB_TIMEOUT}"
  local start elapsed head1
  start=$(_ts)
  while :; do
    [ -f "$path" ] && head1=$(head -n 1 "$path" 2>/dev/null || echo "")
    case "$head1" in
      PROCESSED:*) return 0 ;;
    esac
    elapsed=$(( $(_ts) - start ))
    [ "$elapsed" -ge "$timeout" ] && return 1
    sleep 2
  done
}

wait_for_active_job_empty() {
  local state_dir="$1" timeout="${2:-30}"
  local start elapsed aj
  start=$(_ts)
  while :; do
    aj="$state_dir/active_job.txt"
    [ ! -f "$aj" ] && return 0
    [ ! -s "$aj" ] && return 0
    elapsed=$(( $(_ts) - start ))
    [ "$elapsed" -ge "$timeout" ] && return 1
    sleep 1
  done
}

wait_for_active_job_nonempty() {
  local state_dir="$1" timeout="${2:-30}"
  local start elapsed aj
  start=$(_ts)
  while :; do
    aj="$state_dir/active_job.txt"
    [ -f "$aj" ] && [ -s "$aj" ] && return 0
    elapsed=$(( $(_ts) - start ))
    [ "$elapsed" -ge "$timeout" ] && return 1
    sleep 1
  done
}

assert_todo_file() {
  # Args: <project_dir> <input_txt_path>
  # Extracts slug from the PROCESSED: marker's first line, asserts the referenced
  # TODO file exists with the required sections + frontmatter fields.
  local project="$1" input_txt="$2"
  local first todo_rel todo_abs
  first=$(head -n 1 "$input_txt" 2>/dev/null || echo "")
  case "$first" in
    "PROCESSED: "*)
      todo_rel="${first#PROCESSED: }"
      ;;
    "PROCESSED:"*)
      todo_rel="${first#PROCESSED:}"
      todo_rel="${todo_rel# }"
      ;;
    *) echo "FAIL: no PROCESSED marker in $input_txt"; return 1 ;;
  esac
  case "$todo_rel" in
    /*) todo_abs="$todo_rel" ;;
    *)  todo_abs="$project/$todo_rel" ;;
  esac
  [ -f "$todo_abs" ] || { echo "FAIL: todo file missing: $todo_abs"; return 1; }
  grep -q '^## Idea' "$todo_abs"          || { echo "FAIL: ## Idea missing in $todo_abs"; return 1; }
  grep -q '^## Context' "$todo_abs"       || { echo "FAIL: ## Context missing in $todo_abs"; return 1; }
  grep -q '^## Conversation' "$todo_abs"  || { echo "FAIL: ## Conversation missing in $todo_abs"; return 1; }
  head -15 "$todo_abs" | grep -q '^id:'     || { echo "FAIL: frontmatter id missing"; return 1; }
  head -15 "$todo_abs" | grep -q '^title:'  || { echo "FAIL: frontmatter title missing"; return 1; }
  head -15 "$todo_abs" | grep -q '^status: open' || { echo "FAIL: frontmatter status: open missing"; return 1; }
  head -15 "$todo_abs" | grep -q '^branch:' || { echo "FAIL: frontmatter branch missing"; return 1; }
  return 0
}

assert_audit_success() {
  # Args: <project_dir> <expected_input_txt_path> [timeout_sec=60]
  # Polls audit.log until a SUCCESS line referencing the specific input_txt appears.
  # jot-stop.sh writes the SUCCESS line AFTER the background claude writes the
  # PROCESSED marker, so there is a measurable gap (~1-3s) between wait_for_processed
  # returning and the audit line being written. Always poll.
  local project="$1" expected="$2" timeout="${3:-60}"
  local audit start elapsed
  audit=$(_audit_log "$project")
  start=$(_ts)
  while :; do
    if [ -f "$audit" ] && grep -F " SUCCESS $expected" "$audit" >/dev/null 2>&1; then
      return 0
    fi
    elapsed=$(( $(_ts) - start ))
    [ "$elapsed" -ge "$timeout" ] && return 1
    sleep 1
  done
}

run_scenario() {
  local name="$1" func="$2"
  local start end dur result
  echo
  echo "════════ SCENARIO: $name ════════"
  start=$(_ts)
  if "$func"; then
    result="PASS"
  else
    result="FAIL"
    (cd "$TEST_PROJECT" && bash "$DIAG_SH" "/tmp/jot-e2e-fail-${name}-$(_iso).log") >/dev/null 2>&1 || true
    echo "  diag report: /tmp/jot-e2e-fail-${name}-$(_iso).log"
  fi
  end=$(_ts)
  dur=$(( end - start ))
  RESULTS+=("$name|$result|${dur}s")
  echo "RESULT: $name → $result (${dur}s)"
}

# ── Scenarios ─────────────────────────────────────────────────────────────

scenario_cold_start() {
  # Own setup: kill any existing jot session; authv3_vps starts with no Todos/.
  tmux_kill_session jot
  rm -rf "$TEST_PROJECT/Todos"
  # Sanity: no session, no attached client.
  tmux list-clients -t jot 2>/dev/null | grep -q . && { echo "FAIL: jot session still has clients after kill"; return 1; }
  # Fire.
  local input_txt
  input_txt=$(fire_jot "$TEST_PROJECT" "cold start test — verify background claude spawns")
  [ -n "$input_txt" ] && [ -f "$input_txt" ] || { echo "FAIL: no input.txt after fire_jot"; return 1; }
  echo "  input.txt: $input_txt"
  wait_for_processed "$input_txt" || { echo "FAIL: PROCESSED timeout for $input_txt"; return 1; }
  assert_todo_file "$TEST_PROJECT" "$input_txt" || return 1
  assert_audit_success "$TEST_PROJECT" "$input_txt" || { echo "FAIL: no SUCCESS for $input_txt in audit.log"; return 1; }
  return 0
}

scenario_warm_idle() {
  # In the ephemeral-per-jot architecture, "warm idle" just means "second
  # independent /jot fired shortly after the first". Each invocation gets
  # its own tmux window + claude instance; they coexist briefly then each
  # window self-destructs via its Stop hook. We verify that the second
  # invocation processes cleanly with no cross-contamination.
  local input_txt
  input_txt=$(fire_jot "$TEST_PROJECT" "warm idle second independent jot")
  [ -n "$input_txt" ] && [ -f "$input_txt" ] || { echo "FAIL: no input.txt after fire_jot"; return 1; }
  echo "  input.txt: $input_txt"
  wait_for_processed "$input_txt" || { echo "FAIL: PROCESSED timeout"; return 1; }
  assert_todo_file "$TEST_PROJECT" "$input_txt" || return 1
  assert_audit_success "$TEST_PROJECT" "$input_txt" || { echo "FAIL: no SUCCESS for $input_txt in audit.log"; return 1; }
  return 0
}

scenario_transcript_fallback() {
  # Unrelated idea against the fixture. Accept either: claude extracted something
  # relevant (invented), or the literal fallback string. Log which branch fired.
  local state_dir
  state_dir=$(_state_dir "$TEST_PROJECT")
  wait_for_active_job_empty "$state_dir" 60 || { echo "FAIL: active_job never cleared"; return 1; }
  local input_txt
  input_txt=$(fire_jot "$TEST_PROJECT" "remember to check SSL cert renewal")
  [ -n "$input_txt" ] && [ -f "$input_txt" ] || { echo "FAIL: no input.txt"; return 1; }
  wait_for_processed "$input_txt" || { echo "FAIL: PROCESSED timeout"; return 1; }
  assert_todo_file "$TEST_PROJECT" "$input_txt" || return 1
  assert_audit_success "$TEST_PROJECT" "$input_txt" || return 1
  # Inspect ## Conversation section of the produced TODO for which branch fired.
  local first todo_rel todo_abs conv
  first=$(head -n 1 "$input_txt")
  todo_rel="${first#PROCESSED: }"
  todo_rel="${todo_rel#PROCESSED:}"
  case "$todo_rel" in /*) todo_abs="$todo_rel" ;; *) todo_abs="$TEST_PROJECT/$todo_rel" ;; esac
  conv=$(awk '/^## Conversation/{f=1;next} /^## /{f=0} f' "$todo_abs" 2>/dev/null || echo "")
  if printf '%s' "$conv" | grep -q 'no relevant prior context found in transcript'; then
    echo "  branch: FALLBACK (literal string written)"
  else
    echo "  branch: EXTRACTED (claude found/invented a pair)"
  fi
  return 0
}

scenario_cross_project() {
  # Ephemeral-per-jot architecture: windows are short-lived, so we can't
  # assert concurrent window count. Instead verify that each project has
  # its OWN independent state dir with its OWN audit.log entry, and that
  # the two state dirs don't cross-contaminate.
  # Stable dir under $HOME; trust is accepted once and persists. Do NOT
  # rm -rf the whole dir (that would lose the trust grant and .git history).
  if [ ! -d "$CROSS_PROJECT/.git" ]; then
    mkdir -p "$CROSS_PROJECT"
    (cd "$CROSS_PROJECT" && git init -q && echo hi > README && git add -A && \
      git -c user.email=e2e@jot -c user.name=jot-e2e commit -q -m init) \
      || { echo "FAIL: unable to initialize $CROSS_PROJECT as git repo"; return 1; }
  fi
  rm -rf "$CROSS_PROJECT/Todos"
  local input_txt
  input_txt=$(fire_jot "$CROSS_PROJECT" "cross project isolation test")
  [ -n "$input_txt" ] && [ -f "$input_txt" ] || { echo "FAIL: no input.txt"; return 1; }
  echo "  input.txt: $input_txt"
  wait_for_processed "$input_txt" || { echo "FAIL: PROCESSED timeout"; return 1; }
  assert_todo_file "$CROSS_PROJECT" "$input_txt" || return 1
  assert_audit_success "$CROSS_PROJECT" "$input_txt" || return 1
  # Independent state dirs.
  [ -d "$TEST_PROJECT/Todos/.jot-state" ] || { echo "FAIL: $TEST_PROJECT state dir missing"; return 1; }
  [ -d "$CROSS_PROJECT/Todos/.jot-state" ] || { echo "FAIL: $CROSS_PROJECT state dir missing"; return 1; }
  # Cross-contamination check: authv3_vps's audit.log should NOT contain
  # any CROSS_PROJECT input.txt paths, and vice-versa.
  if grep -F "$CROSS_PROJECT" "$TEST_PROJECT/Todos/.jot-state/audit.log" 2>/dev/null; then
    echo "FAIL: $TEST_PROJECT audit.log leaked CROSS_PROJECT paths"
    return 1
  fi
  if grep -F "$TEST_PROJECT" "$CROSS_PROJECT/Todos/.jot-state/audit.log" 2>/dev/null; then
    echo "FAIL: $CROSS_PROJECT audit.log leaked $TEST_PROJECT paths"
    return 1
  fi
  return 0
}

scenario_crash_recovery() {
  # Ephemeral-per-jot architecture: killing a window SIGKILLs claude before
  # Stop can fire → no PROCESSED marker, no SUCCESS audit line, no retry
  # machinery (there is no shared queue to recover from). The only correct
  # behavior is that (a) the killed jot's input.txt stays PENDING and
  # (b) a subsequent unrelated /jot fires cleanly in its own new window.
  local input1
  input1=$(fire_jot "$TEST_PROJECT" "crash test — will be killed mid-process")
  [ -n "$input1" ] && [ -f "$input1" ] || { echo "FAIL: no input1"; return 1; }
  echo "  input1: $input1"
  # Give claude 3s to launch + start reading, then kill its window.
  sleep 3
  # Derive the window name from input1's timestamp prefix.
  local ts1 window_name1
  ts1=$(basename "$input1" | sed 's/_input\.txt$//')
  window_name1="$(basename "$TEST_PROJECT")-${ts1}"
  tmux kill-window -t "jot:${window_name1}" 2>/dev/null || true
  # After kill, input1 MUST still lack the PROCESSED marker (kill was
  # faster than claude's full response). If claude already finished, we
  # picked a race too late; skip the assertion but continue.
  sleep 2
  local head1
  head1=$(head -1 "$input1" 2>/dev/null || echo "")
  case "$head1" in
    PROCESSED:*)
      echo "  NOTE: kill raced past completion (claude finished first)" ;;
    *)
      echo "  verified: input1 still PENDING after kill" ;;
  esac
  # Fire a fresh jot — should succeed independently.
  local input2
  input2=$(fire_jot "$TEST_PROJECT" "crash test — fresh jot after kill")
  [ -n "$input2" ] && [ -f "$input2" ] || { echo "FAIL: no input2"; return 1; }
  echo "  input2: $input2"
  wait_for_processed "$input2" || { echo "FAIL: input2 never processed after kill"; return 1; }
  assert_todo_file "$TEST_PROJECT" "$input2" || return 1
  assert_audit_success "$TEST_PROJECT" "$input2" || return 1
  return 0
}

scenario_diag_collector() {
  # Read-only — no new jots. Assert report is produced and contains expected sections.
  local out="/tmp/jot-e2e-diag.log"
  rm -f "$out"
  (cd "$TEST_PROJECT" && bash "$DIAG_SH" "$out") >/dev/null 2>&1 || { echo "FAIL: diag collector exited non-zero"; return 1; }
  [ -f "$out" ] || { echo "FAIL: diag report missing"; return 1; }
  grep -q 'tmux' "$out"       || { echo "FAIL: no tmux section in diag"; return 1; }
  grep -q 'audit' "$out"      || { echo "FAIL: no audit section in diag"; return 1; }
  grep -q 'active_job' "$out" || { echo "FAIL: no active_job section in diag"; return 1; }
  local succ
  succ=$(grep -c ' SUCCESS ' "$TEST_PROJECT/Todos/.jot-state/audit.log" 2>/dev/null || echo 0)
  [ "$succ" -ge 2 ] || { echo "FAIL: expected ≥2 SUCCESS lines, got $succ"; return 1; }
  echo "  diag: $out ($(wc -l < "$out" | tr -d ' ') lines)"
  return 0
}

# ── Cleanup subcommand ────────────────────────────────────────────────────

do_cleanup() {
  echo "Cleaning jot e2e state..."
  tmux_kill_session jot
  rm -rf "$TEST_PROJECT/Todos"
  # Wipe cross-project Todos/ but keep the dir itself + .git so Claude Code's
  # workspace trust (stored per-path) stays accepted across runs.
  rm -rf "$CROSS_PROJECT/Todos"
  rm -f /tmp/jot-e2e-diag.log /tmp/jot-e2e-fail-*.log /tmp/jot-e2e-marker.*
  echo "  killed jot session"
  echo "  removed $TEST_PROJECT/Todos"
  echo "  removed $CROSS_PROJECT/Todos (preserved .git + trust)"
  echo "  removed /tmp/jot-e2e-* artifacts"
}

# ── Summary + entry point ─────────────────────────────────────────────────

print_summary() {
  echo
  echo "════════════════════════════════════════"
  printf '%-22s %-6s %s\n' TEST RESULT DURATION
  echo "════════════════════════════════════════"
  local pass=0 fail=0 r name result dur
  for r in "${RESULTS[@]:-}"; do
    [ -z "$r" ] && continue
    IFS='|' read -r name result dur <<< "$r"
    printf '%-22s %-6s %s\n' "$name" "$result" "$dur"
    [ "$result" = "PASS" ] && pass=$(( pass + 1 ))
    [ "$result" = "FAIL" ] && fail=$(( fail + 1 ))
  done
  echo "════════════════════════════════════════"
  echo "TOTAL: PASS=$pass FAIL=$fail"
  [ "$fail" -eq 0 ] && return 0 || return 1
}

main() {
  local cmd="${1:-all}"
  # Sanity: required binaries.
  for t in jq tmux uuidgen claude; do
    command -v "$t" >/dev/null 2>&1 || { echo "HALT: missing $t" >&2; exit 2; }
  done
  [ -x "$JOT_SH" ] || { echo "HALT: jot.sh not executable at $JOT_SH" >&2; exit 2; }
  [ -x "$DIAG_SH" ] || { echo "HALT: jot-diag-collect.sh not executable at $DIAG_SH" >&2; exit 2; }

  case "$cmd" in
    cleanup) do_cleanup; exit 0 ;;
    cold_start)          run_scenario cold_start          scenario_cold_start ;;
    warm_idle)           run_scenario warm_idle           scenario_warm_idle ;;
    transcript_fallback) run_scenario transcript_fallback scenario_transcript_fallback ;;
    cross_project)       run_scenario cross_project       scenario_cross_project ;;
    crash_recovery)      run_scenario crash_recovery      scenario_crash_recovery ;;
    diag_collector)      run_scenario diag_collector      scenario_diag_collector ;;
    all)
      run_scenario cold_start          scenario_cold_start
      run_scenario warm_idle           scenario_warm_idle
      run_scenario transcript_fallback scenario_transcript_fallback
      run_scenario cross_project       scenario_cross_project
      run_scenario crash_recovery      scenario_crash_recovery
      run_scenario diag_collector      scenario_diag_collector
      ;;
    *) echo "Usage: $0 {cold_start|warm_idle|transcript_fallback|cross_project|crash_recovery|diag_collector|all|cleanup}" >&2; exit 2 ;;
  esac
  print_summary
}

main "$@"
