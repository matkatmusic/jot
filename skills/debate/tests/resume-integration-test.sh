#!/bin/bash
# resume-integration-test.sh — fixture-driven integration tests for the
# /debate resume flow. Two layers:
#
#   HOOK LAYER (T1–T6): drives debate_main against pre-seeded Debates/ dirs.
#     Stubs debate_start_or_resume so the real daemon never forks; asserts
#     RESUMING, composition drift, agent set, instruction-file materialization.
#
#   DAEMON LAYER (T7–T10): sources debate-tmux-orchestrator.sh, stubs tmux ops
#     + launch_agent + send_prompt so agent pane behavior is emulated
#     (instead of spawning real agents, the stubs write the expected
#     rX_<agent>.md / synthesis.md directly). Calls daemon_main; asserts
#     final filesystem state.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

COUNTER_FILE=$(mktemp /tmp/debate-test-counter.XXXXXX)
echo "0 0" > "$COUNTER_FILE"
pass() {
  printf '  \033[32mPASS\033[0m %s\n' "$1"
  read -r p f < "$COUNTER_FILE"; echo "$((p+1)) $f" > "$COUNTER_FILE"
}
fail() {
  printf '  \033[31mFAIL\033[0m %s\n' "$1"
  read -r p f < "$COUNTER_FILE"; echo "$p $((f+1))" > "$COUNTER_FILE"
}

# Sets TEST_REPO + exports. Must be called WITHOUT command substitution so
# the exports land in the caller's shell.
mk_test_env() {
  TEST_REPO=$(mktemp -d /tmp/debate-integration.XXXXXX)
  ( cd "$TEST_REPO" && git init -q && git config user.email "t@t" && git config user.name "t" && git commit --allow-empty -q -m init )
  CLAUDE_PLUGIN_DATA="$TEST_REPO/data"; mkdir -p "$CLAUDE_PLUGIN_DATA"
  DEBATE_LOG_FILE="$CLAUDE_PLUGIN_DATA/log"
  STATE_DIR="$TEST_REPO/state"; mkdir -p "$STATE_DIR"
  export TEST_REPO CLAUDE_PLUGIN_DATA DEBATE_LOG_FILE STATE_DIR
}
state() { cat "$STATE_DIR/$1" 2>/dev/null || true; }

# ══════════════════════ HOOK LAYER (debate_main) ══════════════════════

run_debate_main() {
  local input="$1"
  (
    . "$PLUGIN_ROOT/skills/debate/scripts/debate.sh"

    init_hook_context() {
      SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts"
      LOG_FILE="${DEBATE_LOG_FILE}"
      mkdir -p "$(dirname "$LOG_FILE")"
      . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
      INPUT=${INPUT:-$(cat)}
      CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
      [ -z "$CWD" ] && CWD="$PWD"
      TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
      REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
    }
    check_requirements() { :; }
    emit_block() { printf '%s' "$*" > "$STATE_DIR/emit"; }
    detect_available_agents() {
      # HARNESS_AGENTS_STR is a space-separated string; arrays can't be
      # passed cleanly via inline env assignment.
      read -r -a AVAILABLE_AGENTS <<< "$HARNESS_AGENTS_STR"
      GEMINI_MODEL=""
      CODEX_MODEL=""
    }

    debate_start_or_resume() {
      echo "$DEBATE_DIR" > "$STATE_DIR/debate_dir"
      echo "$RESUMING" > "$STATE_DIR/resuming"
      echo "${AVAILABLE_AGENTS[*]}" > "$STATE_DIR/available_agents"

      local composition_drifted=0
      if [ "$RESUMING" = 1 ]; then
        local -a _original=()
        local _f _aa
        for _f in "$DEBATE_DIR"/r1_instructions_*.txt; do
          [ -f "$_f" ] || continue
          _aa=$(basename "$_f" .txt); _aa="${_aa#r1_instructions_}"
          _original+=("$_aa")
        done
        local _os _ns
        _os=$(printf '%s\n' "${_original[@]}" | sort -u | tr '\n' ' ')
        _ns=$(printf '%s\n' "${AVAILABLE_AGENTS[@]}" | sort -u | tr '\n' ' ')
        [ "$_os" != "$_ns" ] && composition_drifted=1
      fi
      echo "$composition_drifted" > "$STATE_DIR/composition_drifted"

      local _a
      for _a in "${AVAILABLE_AGENTS[@]}"; do
        [ -f "$DEBATE_DIR/r1_instructions_${_a}.txt" ] && continue
        DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" AGENT_FILTER="$_a" \
          bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}" >/dev/null 2>&1
      done
      echo called > "$STATE_DIR/stub_ran"

      # Mirror the real debate_start_or_resume's emit.
      local verb="spawned"
      [ "$RESUMING" = 1 ] && verb="resumed"
      emit_block "/debate ${verb} (${AVAILABLE_AGENTS[*]}) → ..."
    }

    trap - ERR
    INPUT="$input"
    debate_main || true
  )
}

test_t1_fresh() {
  mk_test_env; local repo="$TEST_REPO"
  HARNESS_AGENTS_STR="claude gemini codex" \
    run_debate_main '{"cwd":"'"$repo"'","prompt":"/debate hello world","transcript_path":"/tmp/t1.jsonl"}'
  [ "$(state stub_ran)" = called ] && pass "T1: stub invoked" || { fail "T1: stub not invoked, emit=$(state emit)"; rm -rf "$repo"; return; }
  [ "$(state resuming)" = 0 ] && pass "T1: RESUMING=0" || fail "T1: RESUMING=$(state resuming)"
  [ "$(state composition_drifted)" = 0 ] && pass "T1: drift=0" || fail "T1: drift=$(state composition_drifted)"
  local d; d=$(state debate_dir)
  [ -f "$d/topic.md" ] && pass "T1: topic.md written" || fail "T1: no topic.md"
  [ -f "$d/invoking_transcript.txt" ] && pass "T1: transcript.txt written" || fail "T1: no transcript.txt"
  local count; count=$(ls "$d"/r1_instructions_*.txt 2>/dev/null | wc -l | tr -d ' ')
  [ "$count" = 3 ] && pass "T1: 3 r1_instructions built" || fail "T1: $count built"
  case "$(state emit)" in *spawned*) pass "T1: emit says spawned" ;; *) fail "T1: emit=$(state emit)" ;; esac
  rm -rf "$repo"
}

test_t2_complete_shortcircuit() {
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_hello-world"
  mkdir -p "$d"
  printf 'hello world\n' > "$d/topic.md"
  echo "existing synthesis" > "$d/synthesis.md"
  HARNESS_AGENTS_STR="claude gemini codex" \
    run_debate_main '{"cwd":"'"$repo"'","prompt":"/debate hello world","transcript_path":"/tmp/t2.jsonl"}'
  [ -z "$(state stub_ran)" ] && pass "T2: short-circuited" || fail "T2: stub ran"
  case "$(state emit)" in *"already complete"*) pass "T2: emit says already complete" ;; *) fail "T2: emit=$(state emit)" ;; esac
  rm -rf "$repo"
}

test_t3_partial_r1_resume() {
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_partial"
  mkdir -p "$d"
  printf 'partial topic\n' > "$d/topic.md"
  touch "$d/r1_instructions_claude.txt" "$d/r1_instructions_codex.txt"
  echo "r1 claude" > "$d/r1_claude.md"
  HARNESS_AGENTS_STR="claude codex" \
    run_debate_main '{"cwd":"'"$repo"'","prompt":"/debate partial topic","transcript_path":"/tmp/t3.jsonl"}'
  [ "$(state stub_ran)" = called ] && pass "T3: stub invoked" || { fail "T3: stub not invoked, emit=$(state emit)"; rm -rf "$repo"; return; }
  [ "$(state resuming)" = 1 ] && pass "T3: RESUMING=1" || fail "T3: RESUMING=$(state resuming)"
  [ "$(state available_agents)" = "claude codex" ] && pass "T3: 2 agents unchanged" || fail "T3: agents=$(state available_agents)"
  [ "$(state composition_drifted)" = 0 ] && pass "T3: drift=0" || fail "T3: drift=$(state composition_drifted)"
  # macOS symlinks /tmp → /private/tmp, so compare basenames only.
  [ "$(basename "$(state debate_dir)")" = "$(basename "$d")" ] && pass "T3: reused dir" || fail "T3: dir=$(state debate_dir)"
  case "$(state emit)" in *resumed*) pass "T3: emit says resumed" ;; *) fail "T3: emit=$(state emit)" ;; esac
  rm -rf "$repo"
}

test_t4_agent_appeared() {
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_appeared"
  mkdir -p "$d"
  printf 'appeared topic\n' > "$d/topic.md"
  printf 'OLD_CLAUDE_R1_INSTR\n' > "$d/r1_instructions_claude.txt"
  printf 'OLD_CODEX_R1_INSTR\n' > "$d/r1_instructions_codex.txt"
  echo "r1" > "$d/r1_claude.md"; echo "r1" > "$d/r1_codex.md"
  echo "r2" > "$d/r2_claude.md"; echo "r2" > "$d/r2_codex.md"
  HARNESS_AGENTS_STR="claude gemini codex" \
    run_debate_main '{"cwd":"'"$repo"'","prompt":"/debate appeared topic","transcript_path":"/tmp/t4.jsonl"}'
  [ "$(state stub_ran)" = called ] && pass "T4: stub invoked" || { fail "T4: stub not invoked, emit=$(state emit)"; rm -rf "$repo"; return; }
  [ "$(state resuming)" = 1 ] && pass "T4: RESUMING=1" || fail "T4: RESUMING=$(state resuming)"
  [ "$(state available_agents)" = "claude gemini codex" ] && pass "T4: gemini added" || fail "T4: agents=$(state available_agents)"
  [ "$(state composition_drifted)" = 1 ] && pass "T4: drift=1" || fail "T4: drift=$(state composition_drifted)"
  [ -s "$d/r1_instructions_gemini.txt" ] && pass "T4: gemini r1_instructions built" || fail "T4: gemini r1_instructions missing/empty"
  [ "$(cat "$d/r1_instructions_claude.txt")" = "OLD_CLAUDE_R1_INSTR" ] && pass "T4: claude r1_instructions preserved" || fail "T4: claude r1_instructions overwritten"
  rm -rf "$repo"
}

test_t5_disappeared_usable() {
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_dis-usable"
  mkdir -p "$d"
  printf 'dis usable topic\n' > "$d/topic.md"
  touch "$d/r1_instructions_claude.txt" "$d/r1_instructions_codex.txt" "$d/r1_instructions_gemini.txt"
  echo "r1c" > "$d/r1_claude.md"; echo "r1co" > "$d/r1_codex.md"; echo "r1g" > "$d/r1_gemini.md"
  echo "r2c" > "$d/r2_claude.md"; echo "r2co" > "$d/r2_codex.md"; echo "r2g" > "$d/r2_gemini.md"
  HARNESS_AGENTS_STR="claude gemini" \
    run_debate_main '{"cwd":"'"$repo"'","prompt":"/debate dis usable topic","transcript_path":"/tmp/t5.jsonl"}'
  [ "$(state stub_ran)" = called ] && pass "T5: stub invoked" || { fail "T5: stub not invoked, emit=$(state emit)"; rm -rf "$repo"; return; }
  case " $(state available_agents) " in
    *" codex "*) pass "T5: codex re-added (reusable disappeared)" ;;
    *) fail "T5: codex dropped, agents=$(state available_agents)" ;;
  esac
  rm -rf "$repo"
}

test_t6_disappeared_unusable() {
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_dis-bad"
  mkdir -p "$d"
  printf 'dis bad topic\n' > "$d/topic.md"
  touch "$d/r1_instructions_claude.txt" "$d/r1_instructions_codex.txt" "$d/r1_instructions_gemini.txt"
  echo "r1co" > "$d/r1_codex.md"
  HARNESS_AGENTS_STR="claude gemini" \
    run_debate_main '{"cwd":"'"$repo"'","prompt":"/debate dis bad topic","transcript_path":"/tmp/t6.jsonl"}'
  [ -z "$(state stub_ran)" ] && pass "T6: hard-fail" || fail "T6: stub ran"
  case "$(state emit)" in *"cannot resume"*"codex"*) pass "T6: emit names unusable codex" ;; *) fail "T6: emit=$(state emit)" ;; esac
  rm -rf "$repo"
}

# ══════════════════════ DAEMON LAYER (daemon_main) ══════════════════════

# Source the daemon with overrides. Stubs emulate agent/tmux behavior.
# After daemon_main returns, test asserts filesystem state at $DEBATE_DIR.
run_daemon_main() {
  local debate_dir="$1"; shift
  local agents_env="$1"; shift
  local drift="$1"; shift
  (
    export DEBATE_DAEMON_SOURCED=1
    DEBATE_DIR="$debate_dir"
    WINDOW_NAME="debate-$(basename "$DEBATE_DIR")"
    SETTINGS_FILE="/tmp/fake-settings.json"
    CWD="$DEBATE_DIR"
    REPO_ROOT="$DEBATE_DIR"
    PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT"
    DEBATE_AGENTS="$agents_env"
    COMPOSITION_DRIFTED="$drift"
    GEMINI_MODEL=""
    CODEX_MODEL=""

    . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"

    # Stub tmux ops to no-ops (returning a fake pane id per allocation).
    __PANE_COUNTER=0
    new_empty_pane() {
      __PANE_COUNTER=$((__PANE_COUNTER + 1))
      echo "%$__PANE_COUNTER"
    }
    tmux_retile() { :; }
    tmux_kill_pane() { :; }
    tmux_kill_window() { :; }
    tmux_ensure_session() { :; }
    # Silence sleep across the daemon so tests run fast.
    sleep() { :; }

    # Stub cleanup so trap EXIT doesn't touch real tmux / tmpdirs.
    cleanup() { :; }

    # Emulated launch_agent: just writes the lock file. No real agent spawned.
    launch_agent() {
      local pane_id="$1" stage="$2" agent="$3"
      printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
      return 0
    }

    # Emulated send_prompt: writes the stage output the real agent would have
    # produced. This is the heart of the integration harness — it makes the
    # daemon's skip/launch/wait loop observable without running agents.
    send_prompt() {
      local pane_id="$1" stage="$2" agent="$3" instructions="$4"
      local out
      case "$stage" in
        r1)        out="$DEBATE_DIR/r1_${agent}.md" ;;
        r2)        out="$DEBATE_DIR/r2_${agent}.md" ;;
        synthesis) out="$DEBATE_DIR/synthesis.md" ;;
      esac
      # Record which agent/stage were invoked for later assertion.
      printf '%s %s\n' "$stage" "$agent" >> "$DEBATE_DIR/.harness_invocations"
      printf 'FAKE %s output from %s\n' "$stage" "$agent" > "$out"
      return 0
    }

    # write_failed uses tmux capture-pane — stub it too.
    tmux() { :; }  # nuclear but fine for harness

    daemon_main
  )
}

test_t7_daemon_fresh_3agent() {
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_fresh3"
  mkdir -p "$d"
  printf 'topic\n' > "$d/topic.md"
  # Fresh run: r1 instructions already built by debate.sh before daemon fork.
  for a in claude gemini codex; do
    DEBATE_AGENTS="claude gemini codex" AGENT_FILTER="$a" \
      bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" r1 "$d" "$PLUGIN_ROOT" >/dev/null 2>&1
  done

  run_daemon_main "$d" "claude gemini codex" 0 >/dev/null 2>&1

  # After archive_debate, r1_*.md and r2_*.md moved to archive/.
  for a in claude gemini codex; do
    [ -s "$d/archive/r1_${a}.md" ] && pass "T7: r1_${a}.md produced+archived" || fail "T7: r1_${a}.md missing"
  done
  for a in claude gemini codex; do
    [ -s "$d/archive/r2_${a}.md" ] && pass "T7: r2_${a}.md produced+archived" || fail "T7: r2_${a}.md missing"
  done
  [ -s "$d/synthesis.md" ] && pass "T7: synthesis.md produced at top level" || fail "T7: synthesis.md missing"
  # After archive, r1/r2 outputs move to archive/. Verify cleanup.
  [ -d "$d/archive" ] && pass "T7: archive/ created" || fail "T7: no archive/"
  rm -rf "$repo"
}

test_t8_daemon_resume_missing_gemini() {
  # Simulate user's target scenario: claude+codex R1/R2 complete, gemini
  # never ran. Composition drifted = 1 (gemini appeared). Daemon should:
  #   - R1: skip claude+codex, launch gemini → r1_gemini.md produced
  #   - Drift cleared r2_*.md + r2_instructions_*.txt, so R2 launches all 3
  #   - Synthesis runs, produces synthesis.md
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_resume"
  mkdir -p "$d"
  printf 'topic\n' > "$d/topic.md"
  # Pre-existing R1 outputs for claude+codex.
  printf 'existing r1 claude\n' > "$d/r1_claude.md"
  printf 'existing r1 codex\n' > "$d/r1_codex.md"
  # Pre-existing r1_instructions for all 3 (built by debate.sh before daemon).
  for a in claude gemini codex; do
    DEBATE_AGENTS="claude gemini codex" AGENT_FILTER="$a" \
      bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" r1 "$d" "$PLUGIN_ROOT" >/dev/null 2>&1
  done
  # Old r2 outputs + instructions (2-agent composition) — drift clearing should remove.
  printf 'OLD_R2_CLAUDE\n' > "$d/r2_claude.md"
  printf 'OLD_R2_CODEX\n' > "$d/r2_codex.md"
  printf 'OLD_R2_INSTR_CLAUDE\n' > "$d/r2_instructions_claude.txt"
  printf 'OLD_R2_INSTR_CODEX\n' > "$d/r2_instructions_codex.txt"
  printf 'OLD_SYNTH_INSTR\n' > "$d/synthesis_instructions.txt"

  run_daemon_main "$d" "claude gemini codex" 1 > "$d/.daemon.log" 2>&1

  # R1: only gemini should have been invoked (claude+codex have outputs).
  local r1_invocations
  r1_invocations=$(grep '^r1 ' "$d/.harness_invocations" 2>/dev/null | sort | tr '\n' ' ')
  [ "$r1_invocations" = "r1 gemini " ] && pass "T8: R1 launched only gemini" || fail "T8: R1 invocations='$r1_invocations'"

  # Drift cleared r2 artifacts; all 3 agents re-ran R2.
  local r2_invocations
  r2_invocations=$(grep '^r2 ' "$d/.harness_invocations" 2>/dev/null | sort | tr '\n' ' ')
  [ "$r2_invocations" = "r2 claude r2 codex r2 gemini " ] && pass "T8: R2 launched all 3 agents (drift cleared)" || fail "T8: R2 invocations='$r2_invocations'"

  # R2 outputs all present and are NEW (not the "OLD" sentinel).
  for a in claude gemini codex; do
    [ -s "$d/archive/r2_${a}.md" ] && pass "T8: r2_${a}.md produced+archived" || fail "T8: r2_${a}.md missing"
    if [ -f "$d/archive/r2_${a}.md" ]; then
      if grep -q OLD_R2 "$d/archive/r2_${a}.md"; then
        fail "T8: r2_${a}.md contains OLD sentinel (drift clear didn't fire)"
      else
        pass "T8: r2_${a}.md is fresh content"
      fi
    fi
  done

  # synthesis.md present at top level.
  [ -s "$d/synthesis.md" ] && pass "T8: synthesis.md present" || fail "T8: synthesis.md missing"
  # Synthesis invocation happened.
  grep -q '^synthesis claude$' "$d/.harness_invocations" && pass "T8: synthesis launched" || fail "T8: no synthesis invocation"

  # Old synthesis_instructions.txt cleared → rebuilt for 3 agents. Confirm
  # the new synthesis_instructions reference all 3 (in archive after archive_debate ran).
  if [ -f "$d/archive/synthesis_instructions.txt" ]; then
    grep -q 'claude' "$d/archive/synthesis_instructions.txt" && grep -q 'gemini' "$d/archive/synthesis_instructions.txt" && grep -q 'codex' "$d/archive/synthesis_instructions.txt" && pass "T8: new synthesis_instructions references all 3 agents" || fail "T8: synthesis_instructions composition wrong"
  else
    fail "T8: no archive/synthesis_instructions.txt"
  fi

  rm -rf "$repo"
}

test_t9_daemon_resume_nondrift_partial_r1() {
  # Composition unchanged. Claude R1 done, codex R1 missing. Daemon launches
  # only codex for R1. R2 runs all 3 (no r2 outputs pre-seeded).
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_nondrift"
  mkdir -p "$d"
  printf 'topic\n' > "$d/topic.md"
  printf 'existing r1 claude\n' > "$d/r1_claude.md"
  for a in claude codex; do
    DEBATE_AGENTS="claude codex" AGENT_FILTER="$a" \
      bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" r1 "$d" "$PLUGIN_ROOT" >/dev/null 2>&1
  done

  run_daemon_main "$d" "claude codex" 0 > "$d/.daemon.log" 2>&1

  local r1_invocations
  r1_invocations=$(grep '^r1 ' "$d/.harness_invocations" 2>/dev/null | sort | tr '\n' ' ')
  [ "$r1_invocations" = "r1 codex " ] && pass "T9: R1 launched only codex" || fail "T9: R1 invocations='$r1_invocations'"
  [ -s "$d/synthesis.md" ] && pass "T9: synthesis.md produced" || fail "T9: synthesis.md missing"
  rm -rf "$repo"
}

test_t10_daemon_resume_synth_present() {
  # synthesis.md exists top-level but nothing archived. Daemon should skip
  # synthesis launch and jump to archive.
  mk_test_env; local repo="$TEST_REPO"
  local d="$repo/Debates/2025-01-01T00-00-00_synth-present"
  mkdir -p "$d"
  printf 'topic\n' > "$d/topic.md"
  for a in claude codex; do
    DEBATE_AGENTS="claude codex" AGENT_FILTER="$a" \
      bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" r1 "$d" "$PLUGIN_ROOT" >/dev/null 2>&1
  done
  printf 'r1c\n' > "$d/r1_claude.md"; printf 'r1co\n' > "$d/r1_codex.md"
  # Pre-seed r2 instructions + r2 outputs so R2 stage skips all.
  for a in claude codex; do
    DEBATE_AGENTS="claude codex" AGENT_FILTER="$a" \
      bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" r2 "$d" "$PLUGIN_ROOT" >/dev/null 2>&1
  done
  printf 'r2c\n' > "$d/r2_claude.md"; printf 'r2co\n' > "$d/r2_codex.md"
  # Pre-seed synthesis.
  printf 'existing synthesis\n' > "$d/synthesis.md"

  run_daemon_main "$d" "claude codex" 0 > "$d/.daemon.log" 2>&1

  # No invocations at all — everything skipped.
  if [ -f "$d/.harness_invocations" ]; then
    fail "T10: daemon shouldn't have launched anything, invocations=$(cat "$d/.harness_invocations")"
  else
    pass "T10: no launches (all skipped)"
  fi
  [ -d "$d/archive" ] && pass "T10: archive ran" || fail "T10: archive skipped"
  [ -s "$d/synthesis.md" ] && pass "T10: synthesis.md preserved at top level" || fail "T10: synthesis.md gone"
  rm -rf "$repo"
}

# ══════════════════════ Runner ══════════════════════

printf '\n\033[1m== HOOK LAYER ==\033[0m\n'
printf '\n\033[1m%s\033[0m\n' "T1: fresh /debate <topic>"; test_t1_fresh
printf '\n\033[1m%s\033[0m\n' "T2: complete short-circuit"; test_t2_complete_shortcircuit
printf '\n\033[1m%s\033[0m\n' "T3: partial R1 resume, same composition"; test_t3_partial_r1_resume
printf '\n\033[1m%s\033[0m\n' "T4: agent appeared (gemini added)"; test_t4_agent_appeared
printf '\n\033[1m%s\033[0m\n' "T5: disappeared agent w/ complete outputs"; test_t5_disappeared_usable
printf '\n\033[1m%s\033[0m\n' "T6: disappeared agent w/ incomplete outputs"; test_t6_disappeared_unusable

printf '\n\033[1m== DAEMON LAYER ==\033[0m\n'
printf '\n\033[1m%s\033[0m\n' "T7: daemon fresh 3-agent run"; test_t7_daemon_fresh_3agent
printf '\n\033[1m%s\033[0m\n' "T8: daemon resume — gemini appeared (user's target case)"; test_t8_daemon_resume_missing_gemini
printf '\n\033[1m%s\033[0m\n' "T9: daemon resume — partial R1, same composition"; test_t9_daemon_resume_nondrift_partial_r1
printf '\n\033[1m%s\033[0m\n' "T10: daemon resume — synthesis already present"; test_t10_daemon_resume_synth_present

read -r PASS FAIL < "$COUNTER_FILE"
rm -f "$COUNTER_FILE"
printf '\n\033[1m%d passed, %d failed\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ] && exit 0 || exit 1
