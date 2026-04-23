# Feature Plan — `/debate` Resume-Aware Relaunch

**Branch:** `relaunch-with-skip`
**Created:** 2026-04-22
**Status:** Implemented. Diverged from original design on composition-mismatch handling — see Decisions 6, 18, 19, 20 below. Integration test harness at `skills/debate/tests/resume-integration-test.sh` exercises all flows (49 assertions, 10 scenarios including the user's target case: gemini-appeared resume).

**Source files:**
- `skills/debate/scripts/debate.sh` (~200 lines) — hook entrypoint
- `skills/debate/scripts/debate-tmux-orchestrator.sh` (~285 lines) — daemon
- `skills/debate/scripts/debate-build-prompts.sh` — prompt builder (consumed, minimal edits)

---

## Problem Statement

`/debate <topic>` today always spawns a fresh run: new `Debates/<ts>_<slug>/` dir, re-detect agents, re-build R1 prompts, launch all agents from scratch. If any stage fails (quota exhaustion, agent crash, timeout, daemon death), the partial work in the prior dir is orphaned. The user's only recovery is to re-type `/debate <topic>`, which creates a second, unrelated dir — `Debates/` accumulates duplicate incomplete runs (current state: 6+ `repro-test-topic` folders, none finished).

Work that was expensive (R1 outputs from agents that *did* finish) gets re-generated. Work that was cheap (R1 outputs already on disk) gets ignored. There is no way to say "same prompt, pick up where the last run died."

## Solution

Make `/debate <topic>` idempotent by **exact `topic.md` content match**. Make partial runs resumable via **per-agent-per-stage output files** as the source of truth for completion, and **`.<stage>_<agent>.lock` files containing `debate:<pane_id>`** for in-flight detection. Add pass-through companion skills `/debate-retry` and `/debate-abort` scoped by the invoking conversation's `transcript_path`.

After the change:
- Re-invoking `/debate <same topic>` on a **complete** debate short-circuits with "already done, see synthesis.md".
- Re-invoking on an **incomplete** debate resumes — launches only the agents whose output file is missing at each stage, reusing existing R1/R2/synthesis artifacts.
- Re-invoking on a **live** debate bails with a tmux target.
- `/debate-retry` and `/debate-abort` find the target dir by scanning `invoking_transcript.txt` files matching today's transcript.
- Quota-exhausted agents auto-retry through a list of fallback models (`skills/debate/scripts/assets/model-fallbacks.json`); only when all fallbacks fail does the hook surface `/debate-retry` / `/debate-abort` to the user.
- `agents.txt` is eliminated. Original composition is derived from `ls r1_instructions_*.txt`; runtime composition is passed via the `DEBATE_AGENTS` env var (already the pattern for `debate-build-prompts.sh`).

## Design Decisions (from grill-me session, 2026-04-22)

| # | Decision |
|---|---|
| 1 | Same-prompt match: exact byte equality of `topic.md` content |
| 2 | Multi-match tiebreak: most recent timestamp wins |
| 3 | Stage completion ground truth: `<stage>_<agent>.md` exists and non-empty |
| 4 | In-flight detection: `.<stage>_<agent>.lock` file containing `debate:<pane_id>` |
| 5 | Lock liveness (two gates, both must pass): (a) pane in `tmux list-panes`, (b) `pane_current_command` matches agent binary |
| 6 | Agent mismatch on resume: *permissive*. Appeared agents accepted (built just-in-time). Disappeared agents OK iff their R1+R2 outputs exist (reused). Only disappeared-with-incomplete-outputs is a hard fail. Composition drift (any appeared or reusable-disappeared) forces R2 artifact rebuild so every agent critiques the correct roster. |
| 7 | Retry/abort scoping: `invoking_transcript.txt` written at debate creation, matched against today's `transcript_path` |
| 8 | Complete-match short-circuit: `/debate <topic>` on complete dir bails with "already done, see ... or delete <path> to re-run" |
| 9 | Fallback model list: `skills/debate/scripts/assets/model-fallbacks.json`, tried in order, all-or-nothing |
| 10 | Skip logic: inline in daemon (not hook) — filesystem is always the fresh source of truth |
| 11 | Mid-debate failure: daemon writes human-readable `FAILED.txt` including pane capture; no push notification |
| 12 | Live concurrency on `/debate`: bail with tmux attach target |
| 13 | `/debate-abort` on live debate: refuse, show `tmux kill-window -t debate:<window_name>` |
| 14 | Tmux window name on resume: reuse original `debate-<ts>_<slug>` |
| 15 | `agents.txt`: eliminated. Composition derived from `r1_instructions_*.txt`; runtime via `DEBATE_AGENTS` env |
| 16 | Archive step: skip `topic.md` (keeps it discoverable for exact-match scan of complete debates) |
| 17 | FAILED.txt at resume start: delete so a successful resume leaves no failure marker |
| 18 | Per-agent instruction build: `debate-build-prompts.sh` supports `AGENT_FILTER` env so only missing files get built. Existing per-agent instruction files are preserved. |
| 19 | Composition-drift signal: debate.sh computes `composition_drifted` (0/1) before daemon fork. Daemon clears `r2_*.md` + `r2_instructions_*.txt` + `synthesis_instructions.txt` on drift so the whole post-R1 pipeline rebuilds against the current roster. |
| 20 | Integration tests: `skills/debate/tests/resume-integration-test.sh` drives both the hook-layer (debate_main against fixture Debates/ dirs) and daemon-layer (sourcing the daemon with tmux/launch_agent stubbed). 49 assertions across 10 scenarios. |

## Commits

Each commit is tiny and leaves the codebase in a coherent state — "green" is a weaker claim than it appears: the existing `skills/debate/tests/` runner spawns real external agents and is not a fast feedback signal for intermediate commits. The plan relies on **manual verification per commit** (each `Verify:` block below) plus **pure-helper unit harnesses** added alongside the commits that introduce them. Target harnesses:

- `find_matching_debate` (commit 9) — fixture: `Debates/<ts1>_*/topic.md` + `Debates/<ts2>_*/topic.md` with various multi-line / trailing-newline bytes; assert correct dir returned, tie-break on most recent timestamp.
- `any_live_lock` (commit 9) — fixture: debate dir with `.r1_claude.lock` pointing at a nonexistent pane_id vs. a real pane spawned in a throwaway tmux session; assert correct 0/1 return.
- `check_resume_composition` (commit 10) — fixture: `r1_instructions_{claude,gemini}.txt` on disk; assert pass when `AVAILABLE_AGENTS=(claude gemini)`, both "disappeared" and "appeared" branches each emit the matching error.
- `write_failed` (commit 5) — fixture: `DEBATE_DIR` with partial `r1_*.md` outputs; assert `FAILED.txt` lists exactly the missing agents and embeds a pane capture when a real pane exists.

These are ~30-line bash harnesses apiece; add each as a dedicated step in its originating commit and run before the code change that depends on it. Line numbers below are against HEAD (pre-feature) — later commits may shift by a few lines.

---

### 1. Add `skills/debate/scripts/assets/model-fallbacks.json`

New file. Static asset, no code changes. Absent key = no fallback — the consumer's `jq -r '.[$a][]?' ` short-circuits cleanly on a missing key, so there's no reason to list agents with empty lists.

```json
{
  "gemini": ["gemini-2.5-pro", "gemini-3-flash-preview"],
  "codex": []
}
```

Verify: `jq . skills/debate/scripts/assets/model-fallbacks.json` succeeds; `jq -r '.claude[]?' ...` prints nothing (not an error).

---

### 2. Refactor `detect_available_agents` to loop over `model-fallbacks.json`

**File:** `skills/debate/scripts/debate.sh` (replace lines 26–62)

Pass smoke-test commands as argv arrays, never as strings. `eval` and unquoted string expansion are forbidden — they break when any arg contains a space, quote, glob, or `$`. The `--model "$m"` flag syntax is gemini-specific; codex's model-flag form will live alongside the caller when codex grows a non-empty fallback list.

```bash
detect_available_agents() {
  AVAILABLE_AGENTS=(claude)
  GEMINI_MODEL=""
  CODEX_MODEL=""

  local fallbacks_json="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/model-fallbacks.json"

  # _try_agent_models <agent> <smoke_argv...>
  # Reads fallback models for <agent> from model-fallbacks.json. Empty list →
  # run the smoke command once unmodified. Non-empty → append '--model <m>'
  # for each model until one passes. Argv array is preserved end-to-end; no
  # string interpolation, no eval.
  _try_agent_models() {
    local agent="$1"; shift
    local -a base_cmd=("$@")
    local -a models=()
    local m
    while IFS= read -r m; do
      [ -n "$m" ] && models+=("$m")
    done < <(jq -r --arg a "$agent" '.[$a][]?' "$fallbacks_json")

    if [ "${#models[@]}" -eq 0 ]; then
      if _run_with_timeout 30 "${base_cmd[@]}" >/dev/null 2>&1; then
        echo ""
        return 0
      fi
      return 1
    fi

    for m in "${models[@]}"; do
      if _run_with_timeout 30 "${base_cmd[@]}" --model "$m" >/dev/null 2>&1; then
        echo "$m"
        return 0
      fi
      hide_errors printf '%s debate: %s model %s failed smoke test\n' \
        "$(date -Iseconds)" "$agent" "$m" >> "$LOG_FILE"
    done
    return 1
  }

  if command -v gemini >/dev/null 2>&1 && { [[ -f "$HOME/.gemini/oauth_creds.json" ]] || [[ -n "${GEMINI_API_KEY:-}" ]] || [[ -n "${GOOGLE_API_KEY:-}" ]]; }; then
    if GEMINI_MODEL=$(_try_agent_models gemini gemini -p "Reply with exactly: ok"); then
      AVAILABLE_AGENTS+=(gemini)
    fi
  fi

  if command -v codex >/dev/null 2>&1 && { [[ -f "$HOME/.codex/auth.json" ]] || [[ -n "${OPENAI_API_KEY:-}" ]]; }; then
    if CODEX_MODEL=$(_try_agent_models codex codex exec "Reply with exactly: ok" --full-auto); then
      AVAILABLE_AGENTS+=(codex)
    fi
  fi
}
```

Verify: pass a fake gemini binary that echoes its argv, confirm literal `"Reply with exactly: ok"` (quote bytes preserved) never leaks; existing gemini quota-fallback test path still works.

---

### 3. Stop generating `agents.txt`; pass composition via `DEBATE_AGENTS` env

**File:** `skills/debate/scripts/debate.sh`

Delete line 161:
```bash
printf '%s\n' "${AVAILABLE_AGENTS[@]}" > "$DEBATE_DIR/agents.txt"
```

Add to the daemon fork at line 192:
```bash
GEMINI_MODEL="$GEMINI_MODEL" CODEX_MODEL="$CODEX_MODEL" DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
  bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
    "$DEBATE_DIR" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
    >> "$orch_log" 2>&1 </dev/null &
```

**File:** `skills/debate/scripts/debate-tmux-orchestrator.sh` (replace lines 53–56)

```bash
: "${DEBATE_AGENTS:?DEBATE_AGENTS env var required}"
IFS=' ' read -r -a AGENTS <<< "$DEBATE_AGENTS"
```

Also update the daemon's header comment block at lines 5–9 — the `agents.txt` reference is stale:

```bash
# Preconditions (set up by debate.sh before forking):
#   - tmux session 'debate' exists with window $WINDOW_NAME and a keepalive pane
#   - $DEBATE_DIR/{topic.md,context.md,invoking_transcript.txt,r1_instructions_<agent>.txt} all present
#   - $DEBATE_AGENTS env var holds the space-separated agent list for this debate
#   - $SETTINGS_FILE is a claude settings.json granting writes to $DEBATE_DIR/**
```

Verify: fresh debate runs end-to-end; `ls Debates/<ts>_<slug>/` has no `agents.txt`; header comment accurately describes the daemon's inputs.

---

### 4. Stop archiving `topic.md` + `invoking_transcript.txt`

**File:** `skills/debate/scripts/debate-tmux-orchestrator.sh` (edit the archive list at lines 266–275)

```bash
for f in \
    "$DEBATE_DIR/context.md" \
    "$DEBATE_DIR/synthesis_instructions.txt" \
    "$DEBATE_DIR"/r1_instructions_*.txt \
    "$DEBATE_DIR"/r1_*.md \
    "$DEBATE_DIR"/r2_instructions_*.txt \
    "$DEBATE_DIR"/r2_*.md \
    ; do
  [ -f "$f" ] && mv "$f" "$DEBATE_DIR/archive/"
done
```

(`topic.md` + `invoking_transcript.txt` dropped from the list; `agents.txt` gone per commit 3.)

Verify: after completion, `ls Debates/<ts>_<slug>/` shows `topic.md`, `synthesis.md`, `invoking_transcript.txt` at top level.

---

### 5. Lockfile write on launch; delete on output flip; FAILED.txt on launch/send timeout

**File:** `skills/debate/scripts/debate-tmux-orchestrator.sh`

Add a shared `write_failed` helper (insert near the tmux-helper section, around line 94). Safe to call from `launch_agent`, `send_prompt`, `wait_for_outputs`, and `wait_for_file` — the caller identifies the failing stage; the helper captures every agent whose output file is still missing.

```bash
# write_failed <stage> <reason>
# Emits $DEBATE_DIR/FAILED.txt with the stage, reason, timestamp, and a
# tmux capture-pane dump of every agent whose stage output is missing.
# Multiple callers (launch_agent, send_prompt, wait_for_outputs) may invoke
# this; last writer wins, which is fine — any of them is enough signal.
write_failed() {
  local stage="$1" reason="$2"
  {
    printf '# debate FAILED\n\nstage: %s\nreason: %s\ntimestamp: %s\n\n' \
      "$stage" "$reason" "$(date -Iseconds)"
    printf '## missing agents\n'
    local agent lock pane_id
    for agent in "${AGENTS[@]}"; do
      [ -s "$DEBATE_DIR/${stage}_${agent}.md" ] && continue
      printf '\n### %s\n' "$agent"
      lock="$DEBATE_DIR/.${stage}_${agent}.lock"
      pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock" 2>/dev/null)
      if [ -n "$pane_id" ]; then
        printf '```\n'
        hide_errors tmux capture-pane -t "$pane_id" -p -S -200 || printf '(pane capture unavailable)\n'
        printf '```\n'
      else
        printf '(no pane captured — lock file missing or malformed)\n'
      fi
    done
  } > "$DEBATE_DIR/FAILED.txt"
}
```

Edit `launch_agent` signature + body (lines 96–111) to accept stage+agent, write the lock before send, and write FAILED.txt on timeout:

```bash
# launch_agent <pane_id> <stage> <agent> <launch_cmd> <ready_marker> [timeout]
launch_agent() {
  local pane_id="$1" stage="$2" agent="$3" launch_cmd="$4" ready_marker="$5"
  local timeout="${6:-30}"
  printf 'debate:%s\n' "$pane_id" > "$DEBATE_DIR/.${stage}_${agent}.lock"
  tmux_send_and_submit "$pane_id" "$launch_cmd"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$ready_marker"; then
      echo "[orch] ${stage}/${agent} ready after ${elapsed}s (pane $pane_id)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: ${stage}/${agent} not ready within ${timeout}s" >&2
  write_failed "$stage" "launch_agent timeout for $agent after ${timeout}s"
  return 1
}
```

Edit `send_prompt` signature + body (lines 114–132) to carry stage+agent and write FAILED.txt on timeout. Call sites must pass these explicitly rather than parsing a label string.

```bash
# send_prompt <pane_id> <stage> <agent> <instructions_file>
send_prompt() {
  local pane_id="$1" stage="$2" agent="$3" instructions="$4"
  tmux_send_and_submit "$pane_id" "read $instructions and perform them"
  local marker
  marker=$(basename "$instructions")
  local elapsed=0
  while [ "$elapsed" -lt 30 ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$marker"; then
      echo "[orch] ${stage}/${agent} prompt received after ${elapsed}s"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "[orch] TIMEOUT: ${stage}/${agent} did not echo prompt" >&2
  write_failed "$stage" "send_prompt timeout for $agent after 30s"
  return 1
}
```

Update all `launch_agent` / `send_prompt` call sites (lines 209–210 R1, 235–236 R2, 256–257 synthesis):

```bash
launch_agent "${R1_PANES[$i]}" r1 "$agent" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
send_prompt  "${R1_PANES[$i]}" r1 "$agent" "$DEBATE_DIR/r1_instructions_${agent}.txt" || exit 1

launch_agent "${R2_PANES[$i]}" r2 "$agent" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
send_prompt  "${R2_PANES[$i]}" r2 "$agent" "$DEBATE_DIR/r2_instructions_${agent}.txt" || exit 1

launch_agent "$SYNTH_PANE" synthesis claude "$(agent_launch_cmd claude)" "$(agent_ready_marker claude)" || exit 1
send_prompt  "$SYNTH_PANE" synthesis claude "$DEBATE_DIR/synthesis_instructions.txt" || exit 1
```

Edit `wait_for_outputs` (around line 149) to delete the lock the moment the output flips:
```bash
if [ -s "$out" ]; then
  rm -f "$DEBATE_DIR/.${prefix}_${agent}.lock"
  done_count=$((done_count + 1))
  case " $reported " in
    *" $agent "*) ;;
    *) printf '\n[orch] %s: %s wrote %s (%ds)\n' "$prefix" "$agent" "$(basename "$out")" "$elapsed"
       reported="$reported $agent" ;;
  esac
fi
```

For synthesis, add a parallel `wait_for_file` lock-cleanup at line 177:
```bash
if [ -s "$path" ]; then
  rm -f "$DEBATE_DIR/.synthesis_claude.lock"
  printf '\n[orch] %s present after %ds\n' "$(basename "$path")" "$elapsed"
  return 0
fi
```

Verify: (a) during a run, `ls $DEBATE_DIR/.*.lock` shows live locks and on normal completion zero locks remain; (b) kill the tmux window mid-launch so `launch_agent` times out — `FAILED.txt` lands with the pane capture.

---

### 6. Stale-lock cleanup at each stage start

**File:** `skills/debate/scripts/debate-tmux-orchestrator.sh`

New helper (add after the tmux-helper section, around line 94):

```bash
# clean_stale_locks <stage>
# For each .<stage>_<agent>.lock, verify (a) pane_id still exists and
# (b) pane_current_command matches the expected agent binary. Any failure
# → rm the lock. Matches Q3/Q5 liveness semantics.
clean_stale_locks() {
  local stage="$1"
  local lock agent pane_id current
  for lock in "$DEBATE_DIR"/.${stage}_*.lock; do
    [ -f "$lock" ] || continue
    agent=$(basename "$lock" .lock)
    agent="${agent#.${stage}_}"
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    if [ -z "$pane_id" ]; then rm -f "$lock"; continue; fi
    if ! hide_errors tmux list-panes -t "$WINDOW_TARGET" -F '#{pane_id}' | grep -qFx "$pane_id"; then
      rm -f "$lock"; continue
    fi
    current=$(hide_errors tmux display-message -p -t "$pane_id" '#{pane_current_command}')
    if [ "$current" != "$agent" ]; then rm -f "$lock"; fi
  done
}
```

Call it at the top of each stage, before the launch loop (insertion points: before line 201 for R1, before line 226 for R2, before line 252 for synthesis):
```bash
clean_stale_locks r1     # or r2 / synthesis
```

Verify: `echo "debate:%99" > $DEBATE_DIR/.r1_claude.lock` with no pane `%99` → daemon removes the lock on stage entry.

---

### 7. Skip launch when output exists or live lock exists; synthesis-present jumps to archive

**File:** `skills/debate/scripts/debate-tmux-orchestrator.sh`

Extract the archive block (currently inlined at lines 264–277) into a function `archive_debate` so the synthesis-present case can jump to it rather than `exit 0` before archive runs.

```bash
archive_debate() {
  echo "[orch] archiving intermediate files to $DEBATE_DIR/archive/"
  mkdir -p "$DEBATE_DIR/archive"
  local f
  for f in \
      "$DEBATE_DIR/context.md" \
      "$DEBATE_DIR/synthesis_instructions.txt" \
      "$DEBATE_DIR"/r1_instructions_*.txt \
      "$DEBATE_DIR"/r1_*.md \
      "$DEBATE_DIR"/r2_instructions_*.txt \
      "$DEBATE_DIR"/r2_*.md \
      ; do
    [ -f "$f" ] && mv "$f" "$DEBATE_DIR/archive/"
  done
  [ -f "$DEBATE_DIR/orchestrator.log" ] && mv "$DEBATE_DIR/orchestrator.log" "$DEBATE_DIR/archive/"
}
```

Per-stage for-loop (lines 207–211 for R1, 233–237 for R2) guards the launch per agent:

```bash
for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  if [ -s "$DEBATE_DIR/r1_${agent}.md" ]; then
    echo "[orch] r1/${agent} already complete, skipping launch"
    hide_errors tmux_kill_pane "${R1_PANES[$i]}"
    continue
  fi
  if [ -f "$DEBATE_DIR/.r1_${agent}.lock" ]; then
    echo "[orch] r1/${agent} lock held by live pane, skipping launch (wait_for_outputs will observe)"
    hide_errors tmux_kill_pane "${R1_PANES[$i]}"
    continue
  fi
  launch_agent "${R1_PANES[$i]}" r1 "$agent" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt  "${R1_PANES[$i]}" r1 "$agent" "$DEBATE_DIR/r1_instructions_${agent}.txt" || exit 1
done
```

(Extra pre-allocated panes for skipped agents are killed; retile already runs inside `new_empty_pane`. Replicate the same block for R2.)

For synthesis (single-agent), detect pre-existing completion and jump to archive instead of exiting:

```bash
if [ -s "$DEBATE_DIR/synthesis.md" ]; then
  echo "[orch] synthesis already complete, skipping launch; running archive step"
  archive_debate
  echo "[orch] DEBATE COMPLETE — synthesis at $DEBATE_DIR/synthesis.md"
  exit 0
fi
```

Verify: (a) `touch $DEBATE_DIR/r1_claude.md && echo test > $DEBATE_DIR/r1_claude.md`, fork daemon — claude's R1 pane is spawned then immediately killed with no send; (b) seed a `DEBATE_DIR` with `synthesis.md` present but no `archive/` directory, fork daemon — `archive/` is created and populated, synthesis.md stays at top level.

---

### 8. Skip rebuild of instruction files when **every expected agent** has one

Glob existence (`ls r1_instructions_*.txt`) is the wrong check: a partial prior run plus a newly-authenticated agent produces existing-but-incomplete files, and the daemon would send an instruction file that was never generated. Loop over the current `AVAILABLE_AGENTS` set and rebuild if any agent's file is missing.

**File:** `skills/debate/scripts/debate.sh` (wrap the R1 build at line 173):

```bash
_need_r1_build=0
for _a in "${AVAILABLE_AGENTS[@]}"; do
  [ -f "$DEBATE_DIR/r1_instructions_${_a}.txt" ] || { _need_r1_build=1; break; }
done
if [ "$_need_r1_build" = 1 ]; then
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
fi
```

**File:** `skills/debate/scripts/debate-tmux-orchestrator.sh` (wrap R2 build at line 223 and synthesis build at line 249):

```bash
_need_r2_build=0
for _a in "${AGENTS[@]}"; do
  [ -f "$DEBATE_DIR/r2_instructions_${_a}.txt" ] || { _need_r2_build=1; break; }
done
if [ "$_need_r2_build" = 1 ]; then
  DEBATE_AGENTS="${AGENTS[*]}" bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
    r2 "$DEBATE_DIR" "$PLUGIN_ROOT"
fi
```

```bash
if [ ! -f "$DEBATE_DIR/synthesis_instructions.txt" ]; then
  DEBATE_AGENTS="${AGENTS[*]}" bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
    synthesis "$DEBATE_DIR" "$PLUGIN_ROOT"
fi
```

Verify: (a) seed a `DEBATE_DIR` with only `r1_instructions_claude.txt` then boot daemon with `DEBATE_AGENTS="claude gemini codex"` — R1 builder runs and produces the two missing files without clobbering claude's; (b) on a fully-populated `DEBATE_DIR`, existing SHA256 sums are unchanged after boot.

---

### 9. Extract `init_hook_context` + `debate_start_or_resume`; exact-topic match + dir-reuse

This commit restructures `debate.sh` so the same setup + daemon-fork body is shared between `debate_main` (`/debate <topic>`) and the future `debate_retry_main` (commit 14). Topic equality uses `cmp` so it survives multi-line topics; the tmux window name and the emit-block path are both derived from `$DEBATE_DIR` so resume lands on the reused window and prints an accurate path.

**File:** `skills/debate/scripts/debate.sh`

Add three new helpers before `debate_main`:

```bash
# init_hook_context
# Reads hook JSON from stdin and sets shared globals. Sources the common
# libs. Called by debate_main, debate_retry_main, debate_abort_main.
init_hook_context() {
  : "${CLAUDE_PLUGIN_ROOT:?debate plugin env not set}"
  : "${CLAUDE_PLUGIN_DATA:?debate plugin env not set}"
  SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${DEBATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/debate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"

  INPUT=${INPUT:-$(cat)}
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
}

# find_matching_debate <repo_root> <topic>
# Prints the matching debate dir path, or empty if none. Uses cmp so
# multi-line topics and trailing-newline edge cases work correctly.
# Most-recent dir (lexicographic timestamp) wins.
find_matching_debate() {
  local repo_root="$1" topic="$2"
  local dir match_ts="" best=""
  for dir in "$repo_root"/Debates/*/; do
    [ -f "$dir/topic.md" ] || continue
    if printf '%s\n' "$topic" | hide_errors cmp -s - "$dir/topic.md"; then
      local ts; ts=$(basename "$dir")
      if [[ "$ts" > "$match_ts" ]]; then
        match_ts="$ts"
        best="${dir%/}"
      fi
    fi
  done
  printf '%s' "$best"
}

# any_live_lock <debate_dir> → 0 if a live lock exists, 1 otherwise.
any_live_lock() {
  local dir="$1" lock pane_id
  for lock in "$dir"/.*.lock; do
    [ -f "$lock" ] || continue
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    [ -n "$pane_id" ] && hide_errors tmux list-panes -a -F '#{pane_id}' | grep -qFx "$pane_id" && return 0
  done
  return 1
}
```

Add `debate_start_or_resume` — the shared body. Caller must set `TOPIC`, `DEBATE_DIR`, `RESUMING` (`0`|`1`), `AVAILABLE_AGENTS`, `GEMINI_MODEL`, `CODEX_MODEL` before calling.

```bash
debate_start_or_resume() {
  # Window name derived from the debate dir — works for fresh spawn AND
  # resume. On resume, basename($DEBATE_DIR) is the original ts_slug, so
  # tmux finds (or creates) the same window the original daemon used.
  local window_name
  window_name="debate-$(basename "$DEBATE_DIR")"

  # R1 instruction build (per-agent completeness check from commit 8).
  local _a need_r1_build=0
  for _a in "${AVAILABLE_AGENTS[@]}"; do
    [ -f "$DEBATE_DIR/r1_instructions_${_a}.txt" ] || { need_r1_build=1; break; }
  done
  if [ "$need_r1_build" = 1 ]; then
    DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
      bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
  fi

  debate_build_claude_cmd

  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate keepalive]\n"; exec tail -f /dev/null'\'''
  tmux_ensure_session debate "$window_name" "$CWD" "$keepalive_cmd" 'debate: keepalive'
  hide_errors tmux resize-window -t "debate:${window_name}" -x 200 -y 60

  local orch_log="$DEBATE_DIR/orchestrator.log"
  GEMINI_MODEL="$GEMINI_MODEL" CODEX_MODEL="$CODEX_MODEL" DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
      "$DEBATE_DIR" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
      >> "$orch_log" 2>&1 </dev/null &
  disown

  spawn_terminal_if_needed "debate" "$LOG_FILE" "debate"

  # Emit path derived from $DEBATE_DIR — correct for both fresh and resume.
  # Verb differentiates so the user sees the right state.
  local agents_str="${AVAILABLE_AGENTS[*]}"
  local rel="Debates/$(basename "$DEBATE_DIR")"
  local verb="spawned"
  [ "$RESUMING" = 1 ] && verb="resumed"
  emit_block "/debate ${verb} (${agents_str// /, }) → ${rel}/synthesis.md (~10-30 min). View: tmux attach -t debate:${window_name}"
}
```

Rewrite `debate_main` (replaces lines 92–203) to use the shared helpers:

```bash
debate_main() {
  init_hook_context
  check_requirements "debate" jq python3 tmux claude

  case "$INPUT" in *'"/debate'*) ;; *) exit 0 ;; esac
  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
  PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"
  [[ "$PROMPT" == "/debate" || "$PROMPT" == "/debate "* ]] || exit 0

  TOPIC="${PROMPT#/debate}"
  TOPIC="${TOPIC# }"
  [ -z "$TOPIC" ] && { emit_block "debate: no topic provided. Usage: /debate <topic>"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "debate requires a git repository."; exit 0; }

  trap 'rc=$?; emit_block "debate crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  detect_available_agents

  local existing
  existing=$(find_matching_debate "$REPO_ROOT" "$TOPIC")
  RESUMING=0
  if [ -n "$existing" ]; then
    if [ -f "$existing/synthesis.md" ]; then
      emit_block "/debate: already complete, see $existing/synthesis.md — or 'rm -rf $existing' to re-run"; exit 0
    fi
    if any_live_lock "$existing"; then
      emit_block "/debate: already running for this topic → tmux attach -t debate:debate-$(basename "$existing")"; exit 0
    fi
    DEBATE_DIR="$existing"
    RESUMING=1
  else
    if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
      emit_block "debate requires at least 2 agents. Found: ${AVAILABLE_AGENTS[*]}. Install or authenticate gemini or codex."
      exit 0
    fi
    local TIMESTAMP slug
    TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)
    slug=$(printf '%s' "$TOPIC" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//')
    DEBATE_DIR="$REPO_ROOT/Debates/${TIMESTAMP}_${slug}"
    mkdir -p "$DEBATE_DIR"
    printf '%s\n' "$TOPIC" > "$DEBATE_DIR/topic.md"
    [ -n "$TRANSCRIPT_PATH" ] && printf '%s\n' "$TRANSCRIPT_PATH" > "$DEBATE_DIR/invoking_transcript.txt"

    # context.md capture — identical to the existing block (lines 164–170).
    local capture_script="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/capture-conversation.py"
    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] && [ -f "$capture_script" ]; then
      hide_errors python3 "$capture_script" "$TRANSCRIPT_PATH" > "$DEBATE_DIR/context.md"
    else
      printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"
    fi
  fi

  # Composition mismatch check (commit 10) + FAILED.txt delete (commit 11)
  # live here between the branch and debate_start_or_resume.

  debate_start_or_resume
  exit 0
}
```

Verify: (a) new topic → new dir, window `debate-<ts>_<slug>`, emit path matches that dir; (b) same topic + complete → short-circuit; (c) same topic + incomplete → reuse dir, reuse window name, emit verb says "resumed"; (d) multi-line topic round-trips through `find_matching_debate` correctly (`printf '%s\n' "$topic" | cmp -s -` matches the write format).

---

### 10. Hard-fail on agent composition mismatch (resume only)

Extract as a helper so `debate_main` (commit 9) and `debate_retry_main` (commit 13) can both call it. Original composition is derived from `r1_instructions_<agent>.txt` filenames (commit 3 removed `agents.txt`).

**File:** `skills/debate/scripts/debate.sh` (add helper alongside `find_matching_debate`)

```bash
# check_resume_composition
# Expects $DEBATE_DIR and AVAILABLE_AGENTS set. Hard-fails if the original
# composition (from r1_instructions_*.txt) doesn't match today's availability
# exactly — symmetric in both directions:
#   - Original has agent X, today doesn't → "agent disappeared"
#   - Today has agent Y, original doesn't → "agent appeared"
# Silently adding Y would mean R2/synthesis prompts reference a Y R1 file
# that doesn't exist; silently dropping X invalidates the debate.
# Either path tells the user to /debate-abort and re-run.
check_resume_composition() {
  local -a original=()
  local f agent
  for f in "$DEBATE_DIR"/r1_instructions_*.txt; do
    [ -f "$f" ] || continue
    agent=$(basename "$f" .txt)
    agent="${agent#r1_instructions_}"
    original+=("$agent")
  done

  local orig missing="" appeared=""
  for orig in "${original[@]}"; do
    case " ${AVAILABLE_AGENTS[*]} " in
      *" $orig "*) ;;
      *) missing="$missing $orig" ;;
    esac
  done
  local avail
  for avail in "${AVAILABLE_AGENTS[@]}"; do
    case " ${original[*]} " in
      *" $avail "*) ;;
      *) appeared="$appeared $avail" ;;
    esac
  done

  if [ -n "$missing" ]; then
    emit_block "/debate: cannot resume, these original agents are unavailable:${missing}. All their fallback models failed smoke tests. Next: '/debate-retry' later when quotas reset, or '/debate-abort' to clean up."
    exit 0
  fi
  if [ -n "$appeared" ]; then
    emit_block "/debate: cannot resume, these agents appeared since the original run:${appeared}. Resuming with a changed composition would corrupt R2/synthesis prompts. Next: '/debate-abort' to delete and re-run fresh, including the new agent(s)."
    exit 0
  fi
}
```

Call it from `debate_main` (commit 9 placeholder: between the `RESUMING=1` branch and `debate_start_or_resume`) and from `debate_retry_main` (commit 13 placeholder: after `detect_available_agents`):

```bash
[ "$RESUMING" = 1 ] && check_resume_composition
```

Verify: simulate `codex` unavailable on a codex-inclusive resume (both via `/debate <same topic>` and `/debate-retry`) → both paths exit with the same composed error that references `/debate-retry` and `/debate-abort`.

---

### 11. Delete `FAILED.txt` at resume start

**File:** `skills/debate/scripts/debate.sh` (add inside the `RESUMING=1` branch, after composition check)

```bash
rm -f "$DEBATE_DIR/FAILED.txt"
```

Verify: after failed → resumed → succeeded cycle, `FAILED.txt` is absent.

---

### 12. Call `write_failed` on `wait_for_outputs` / `wait_for_file` timeout

`write_failed` is already defined in commit 5 and already called from `launch_agent` / `send_prompt`. Add the same call at the remaining two timeout sites so stage-output timeouts and synthesis-file timeouts also produce `FAILED.txt`.

**File:** `skills/debate/scripts/debate-tmux-orchestrator.sh`

`wait_for_outputs` timeout (line 166):
```bash
printf '\n[orch] TIMEOUT: %s outputs incomplete after %ds\n' "$prefix" "$timeout" >&2
write_failed "$prefix" "wait_for_outputs timeout after ${timeout}s"
return 1
```

`wait_for_file` timeout (line 184, synthesis path):
```bash
printf '\n[orch] TIMEOUT: %s never written after %ds\n' "$(basename "$path")" "$timeout" >&2
write_failed synthesis "wait_for_file timeout after ${timeout}s ($(basename "$path") missing)"
return 1
```

Verify: kill the codex pane mid-R1 → after 15 min timeout, `$DEBATE_DIR/FAILED.txt` contains the codex pane capture (produced by `write_failed`'s pane-capture loop).

---

### 13. Add `/debate-retry` companion skill (outer dispatch + new orchestrator)

Dispatch for `/debate-retry` lives in the outer hook dispatcher at `scripts/orchestrator.sh`, **not** inside `debate.sh`. The outer dispatcher routes to a dedicated entrypoint script that sources `debate.sh` and calls `debate_retry_main`. `debate_retry_main` finds the target dir, seeds `TOPIC`/`DEBATE_DIR`/`RESUMING=1`, runs the composition check, and delegates to `debate_start_or_resume` (from commit 9).

**New file:** `skills/debate-retry/SKILL.md`

```markdown
---
name: debate-retry
description: Resume the most recent incomplete debate invoked from this conversation.
---

# Task:
do nothing. the UserPromptSubmit outer orchestrator dispatches to debate-retry-orchestrator.sh.
```

**New file:** `skills/debate-retry/scripts/debate-retry-orchestrator.sh`

```bash
#!/bin/bash
# debate-retry-orchestrator.sh — UserPromptSubmit hook entry for /debate-retry.
# Sources debate.sh (shared init + helpers + functions), calls debate_retry_main.
set -euo pipefail
DEBATE_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../debate/scripts" && pwd)"
# shellcheck source=../../debate/scripts/debate.sh
. "$DEBATE_SCRIPTS_DIR/debate.sh"
debate_retry_main
```

**File:** `scripts/orchestrator.sh` (add new case after line 38, alongside `/debate`)

```bash
  "/debate-retry"|"/debate-retry "*|$'/debate-retry\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/debate-retry/scripts/debate-retry-orchestrator.sh"
    ;;
```

**File:** `skills/debate/scripts/debate.sh` (add `debate_retry_main` alongside `debate_main`; no in-file dispatch case is needed — outer orchestrator handles routing)

```bash
debate_retry_main() {
  init_hook_context
  check_requirements "debate-retry" jq python3 tmux claude

  [ -z "$TRANSCRIPT_PATH" ] && { emit_block "/debate-retry: no transcript_path in hook payload"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "/debate-retry requires a git repository"; exit 0; }

  trap 'rc=$?; emit_block "debate-retry crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  local dir best_ts="" best=""
  for dir in "$REPO_ROOT"/Debates/*/; do
    [ -f "$dir/invoking_transcript.txt" ] || continue
    [ "$(cat "$dir/invoking_transcript.txt")" = "$TRANSCRIPT_PATH" ] || continue
    local ts; ts=$(basename "$dir")
    if [[ "$ts" > "$best_ts" ]]; then best_ts="$ts"; best="${dir%/}"; fi
  done
  [ -z "$best" ] && { emit_block "/debate-retry: no debate found in this conversation"; exit 0; }

  if [ -f "$best/synthesis.md" ]; then
    emit_block "/debate-retry: already complete, see $best/synthesis.md"; exit 0
  fi
  if any_live_lock "$best"; then
    emit_block "/debate-retry: still running → tmux attach -t debate:debate-$(basename "$best")"; exit 0
  fi

  DEBATE_DIR="$best"
  TOPIC=$(cat "$best/topic.md")
  RESUMING=1

  detect_available_agents
  # Composition-mismatch hard-fail (commit 10) lives here, reading the
  # original agent set from $DEBATE_DIR/r1_instructions_*.txt.

  rm -f "$DEBATE_DIR/FAILED.txt"
  debate_start_or_resume
  exit 0
}
```

Verify: (a) grep `scripts/orchestrator.sh` confirms the new case; (b) after a failed `/debate foo`, typing `/debate-retry` in the same conversation re-invokes the same `DEBATE_DIR` and the emit message says "resumed"; (c) `/debate-retry` from a conversation that never ran `/debate` emits "no debate found in this conversation".

---

### 14. Add `/debate-abort` companion skill (outer dispatch + new orchestrator)

Same pattern as commit 13: outer dispatch in `scripts/orchestrator.sh`, dedicated entrypoint script, `debate_abort_main` added to `debate.sh`.

**New file:** `skills/debate-abort/SKILL.md`

```markdown
---
name: debate-abort
description: Delete the most recent incomplete debate from this conversation.
---

# Task:
do nothing. the UserPromptSubmit outer orchestrator dispatches to debate-abort-orchestrator.sh.
```

**New file:** `skills/debate-abort/scripts/debate-abort-orchestrator.sh`

```bash
#!/bin/bash
# debate-abort-orchestrator.sh — UserPromptSubmit hook entry for /debate-abort.
# Sources debate.sh (shared init + helpers + functions), calls debate_abort_main.
set -euo pipefail
DEBATE_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../debate/scripts" && pwd)"
# shellcheck source=../../debate/scripts/debate.sh
. "$DEBATE_SCRIPTS_DIR/debate.sh"
debate_abort_main
```

**File:** `scripts/orchestrator.sh` (add new case alongside `/debate-retry` from commit 13)

```bash
  "/debate-abort"|"/debate-abort "*|$'/debate-abort\n'*)
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/skills/debate-abort/scripts/debate-abort-orchestrator.sh"
    ;;
```

**File:** `skills/debate/scripts/debate.sh` (add `debate_abort_main` alongside `debate_retry_main`)

```bash
debate_abort_main() {
  init_hook_context
  check_requirements "debate-abort" jq tmux

  [ -z "$TRANSCRIPT_PATH" ] && { emit_block "/debate-abort: no transcript_path in hook payload"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "/debate-abort requires a git repository"; exit 0; }

  local dir best_ts="" best=""
  for dir in "$REPO_ROOT"/Debates/*/; do
    [ -f "$dir/invoking_transcript.txt" ] || continue
    [ "$(cat "$dir/invoking_transcript.txt")" = "$TRANSCRIPT_PATH" ] || continue
    local ts; ts=$(basename "$dir")
    if [[ "$ts" > "$best_ts" ]]; then best_ts="$ts"; best="${dir%/}"; fi
  done
  [ -z "$best" ] && { emit_block "/debate-abort: no debate found in this conversation"; exit 0; }

  if any_live_lock "$best"; then
    emit_block "/debate-abort: debate is running. to force-kill: tmux kill-window -t debate:debate-$(basename "$best")"
    exit 0
  fi
  rm -rf "$best"
  emit_block "/debate-abort: deleted $best"
  exit 0
}
```

Verify: (a) grep `scripts/orchestrator.sh` confirms the new case; (b) `/debate-abort` after a failed run deletes the dir; (c) on a live run, it refuses and shows the exact `tmux kill-window` command.

---

### 15. Surface fallback-exhausted to the user (fresh-debate path only)

The resume-time composition mismatch already references `/debate-retry` and `/debate-abort` via `check_resume_composition` (commit 10). Only the fresh-debate "not enough agents" branch still needs updating.

**File:** `skills/debate/scripts/debate.sh` (edit the "not enough agents" branch inside `debate_main`, reached only when no matching dir exists — i.e. there is nothing to retry against. The message acknowledges that.)

```bash
if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
  emit_block "/debate: needs ≥2 agents, got: ${AVAILABLE_AGENTS[*]}. All fallback models for missing agents failed smoke tests. Fix credentials/quota and re-run '/debate <topic>'."
  exit 0
fi
```

Verify: temporarily set both gemini fallback models to bogus strings; invoke `/debate foo` (on a never-seen topic); confirm the emitted message names the auth/quota fix path, not `/debate-retry`.

## Verification

After commit 15, the full resume flow works end-to-end. Manual verification scenario:

1. Start a 3-agent debate; kill the daemon after R1 claude+gemini finish but before codex finishes.
2. Re-invoke `/debate <same topic>` → confirm only codex's R1 pane spawns (claude+gemini outputs are reused).
3. Debate completes normally through R2 + synthesis.
4. `ls Debates/<ts>_<slug>/` shows `synthesis.md` + `topic.md` + `invoking_transcript.txt` at top level; everything else in `archive/`.
5. Re-invoke `/debate <same topic>` → short-circuit with "already done" message.
6. `/debate-abort` in the same conversation → refuses (if live) or deletes (if not).

## Out of Scope

- Mid-debate quota detection via pane pattern-matching (Q9 decision: user runs `/debate-retry` after timeout; fallback-models are re-evaluated at hook time).
- **Pre-lock race during `detect_available_agents`.** Each agent's smoke test has a 30s timeout; on a fresh-dir invocation the lockfiles don't yet exist until the daemon forks, so two `/debate <same topic>` invocations that fire within the detection window (up to 30s × 3 agents = ~90s worst case) both classify as fresh runs, both compute non-colliding `TIMESTAMP_slug` dir names (second-resolution timestamps differ), and both proceed. Accepted: (a) this requires two human invocations seconds apart on the same machine, (b) the resulting duplicate dirs are harmless — one completes, the other completes, `/debate <topic>` the next day matches the earlier-timestamped complete dir and short-circuits. A `hook_in_progress.$$` sentinel written at the top of `debate_main` could close the window at the cost of brittle cleanup if `debate_main` crashes mid-detection. Not worth it for a two-humans-same-second bug.
- Archiving strategy for aborted debates (Q12: hard delete via `rm -rf`).
- Per-agent model override UI (Q5 variant: users don't hand-edit; fallback list in asset file is the control surface).
- **Template-drift detection across resumes.** A prior run's `r{1,2}_instructions_*.txt` built against an older prompt template will be reused as-is after the commit-9 completeness check. A future `.template_sha256` marker could force a rebuild on template change; deferred to v2.
