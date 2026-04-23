# Round 1 — Codex Analysis

## Position

The plan is directionally good, and the core architecture is sound:

- using `topic.md` as the idempotence key,
- using output files as completion truth,
- using per-stage lock files for in-flight detection,
- keeping `topic.md` unarchived,
- and removing `agents.txt`.

The problem is that the plan is **not implementation-ready as written**. Several snippets either fail outright or leave major design decisions only partially implemented. The line anchors are mostly close to current HEAD; the bigger issue is logic correctness, not anchor drift.

## Findings

### 1. `/debate-retry` and `/debate-abort` do not work as written

This is the biggest issue. The proposed retry/abort path relies on state and functions that do not exist in the current control flow.

Current `skills/debate/scripts/debate.sh` initializes `CWD`, `REPO_ROOT`, and the sourced helpers **inside `debate_main`**:

```bash
debate_main() {
  : "${CLAUDE_PLUGIN_ROOT:?debate plugin env not set}"
  : "${CLAUDE_PLUGIN_DATA:?debate plugin env not set}"

  local SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${DEBATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/debate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"

  INPUT=$(cat)
  ...
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  ...
  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
```

But the plan adds this:

```bash
debate_retry_main() {
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  [ -z "$TRANSCRIPT_PATH" ] && { emit_block "/debate-retry: no transcript path in hook payload"; return; }

  local dir best_ts="" best=""
  for dir in "$REPO_ROOT"/Debates/*/; do
    [ -f "$dir/invoking_transcript.txt" ] || continue
    [ "$(cat "$dir/invoking_transcript.txt")" = "$TRANSCRIPT_PATH" ] || continue
    local ts; ts=$(basename "$dir")
    if [[ "$ts" > "$best_ts" ]]; then best_ts="$ts"; best="${dir%/}"; fi
  done

  [ -z "$best" ] && { emit_block "/debate-retry: no debate found in this conversation"; return; }
  if [ -f "$best/synthesis.md" ]; then
    emit_block "/debate-retry: last debate is already complete, see $best/synthesis.md"; return
  fi
  if any_live_lock "$best"; then
    emit_block "/debate-retry: debate is still running → tmux attach -t debate:$(basename "$best")"; return
  fi

  TOPIC=$(cat "$best/topic.md")
  # Delegate to the standard resume path.
  debate_main_resume "$best"
}
```

Problems:

- `REPO_ROOT` is used, but this snippet never computes it.
- `debate_main_resume` does not exist anywhere in the repo.
- the tmux target is wrong: current window names are `debate-${TIMESTAMP}_${slug}`, so `tmux attach -t debate:$(basename "$best")` omits the `debate-` prefix.
- the abort snippet has the same wrong target problem: `tmux kill-window -t debate:$(basename "$best")`.

This needs a real shared entrypoint, not a hand-wave. The safe shape is:

```bash
init_hook_context() {
  INPUT=$(cat)
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
}

debate_start_or_resume() {
  # shared body of current debate_main after prompt parsing
}

debate_retry_main() {
  init_hook_context
  local best
  best=$(find_latest_debate_for_transcript "$REPO_ROOT" "$TRANSCRIPT_PATH")
  ...
  TOPIC=$(cat "$best/topic.md")
  DEBATE_DIR="$best"
  RESUMING=1
  debate_start_or_resume
}
```

Without that refactor, commits 14 and 15 are not executable.

### 2. The resume path does not actually implement “reuse original tmux window name”

Decision 14 says:

> Tmux window name on resume: reuse original `debate-<ts>_<slug>`

But commit 10 only reuses `DEBATE_DIR`. It does not update the later window naming logic in current `debate.sh`:

```bash
# Ensure tmux session and window with keepalive pane
local window_name="debate-${TIMESTAMP}_${slug}"
local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate keepalive]\n"; exec tail -f /dev/null'\'''
tmux_ensure_session debate "$window_name" "$CWD" "$keepalive_cmd" 'debate: keepalive'
local window_target="debate:${window_name}"
```

That means a resumed debate would still launch into a **new** window name based on the current timestamp, not the original debate dir. The plan’s live-run messages and abort instructions assume the opposite.

The implementation needs an explicit branch:

```bash
local window_name
if [ "$RESUMING" = 1 ]; then
  window_name="debate-$(basename "$DEBATE_DIR")"
else
  window_name="debate-${TIMESTAMP}_${slug}"
fi
```

The success message also needs the same treatment. Current code prints:

```bash
emit_block "/debate spawned (${agents_str// /, }) → Debates/${TIMESTAMP}_${slug}/synthesis.md (~10-30 min). View: tmux attach -t debate"
```

On resume, that path would be wrong unless it is changed to use `$(basename "$DEBATE_DIR")`.

### 3. Commit 2’s fallback helper is shell-broken because it stores commands as strings

The proposed `_try_agent_models` passes a shell command as a single string:

```bash
_try_agent_models() {
  local agent="$1"; shift
  local smoke_cmd="$1"; shift
  ...
  if [ "${#models[@]}" -eq 0 ]; then
    if _run_with_timeout 30 $smoke_cmd >/dev/null 2>&1; then
      echo ""
      return 0
    fi
    return 1
  fi
  ...
  for m in "${models[@]}"; do
    if _run_with_timeout 30 $smoke_cmd --model "$m" >/dev/null 2>&1; then
      echo "$m"
      return 0
    fi
```

and then calls it like this:

```bash
if GEMINI_MODEL=$(_try_agent_models gemini 'gemini -p "Reply with exactly: ok"'); then
  AVAILABLE_AGENTS+=(gemini)
fi

if CODEX_MODEL=$(_try_agent_models codex 'codex exec "Reply with exactly: ok" --full-auto'); then
  AVAILABLE_AGENTS+=(codex)
fi
```

That does not preserve quoting. Shell quotes inside a variable are just literal characters, not syntax. The safe implementation must carry commands as arrays:

```bash
_try_agent_models() {
  local agent="$1"; shift
  local -a base_cmd=("$@")
  local -a models
  IFS=$'\n' read -r -d '' -a models < <(jq -r --arg a "$agent" '.[$a][]?' "$fallbacks_json" && printf '\0')

  if [ "${#models[@]}" -eq 0 ]; then
    _run_with_timeout 30 "${base_cmd[@]}" >/dev/null 2>&1
    return $?
  fi

  local m
  for m in "${models[@]}"; do
    if _run_with_timeout 30 "${base_cmd[@]}" --model "$m" >/dev/null 2>&1; then
      printf '%s\n' "$m"
      return 0
    fi
  done
  return 1
}

if GEMINI_MODEL=$(_try_agent_models gemini gemini -p "Reply with exactly: ok"); then
  AVAILABLE_AGENTS+=(gemini)
fi

if CODEX_MODEL=$(_try_agent_models codex codex exec "Reply with exactly: ok" --full-auto); then
  AVAILABLE_AGENTS+=(codex)
fi
```

As written in the plan, commit 2 is not safe to paste in.

### 4. The instruction rebuild guard is too coarse and will fail on partial debates

Commit 9 proposes:

```bash
if ! ls "$DEBATE_DIR"/r1_instructions_*.txt >/dev/null 2>&1; then
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
fi
```

The same pattern is used for R2.

That only checks whether **any** matching file exists. It does not check whether the instruction set is complete for the current agent list. In a partial debate directory, this can easily leave missing instruction files behind, and the daemon later blindly sends them:

```bash
for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  launch_agent "${R1_PANES[$i]}" "$agent(r1)" "$(agent_launch_cmd "$agent")" "$(agent_ready_marker "$agent")" || exit 1
  send_prompt  "${R1_PANES[$i]}" "$agent(r1)" "$DEBATE_DIR/r1_instructions_${agent}.txt" || exit 1
done
```

If only `r1_instructions_claude.txt` exists, the guard skips the rebuild, but `send_prompt` still tries `r1_instructions_codex.txt` and `r1_instructions_gemini.txt`.

This needs a completeness check, not an existence check:

```bash
have_all_r1_instructions() {
  local agent
  for agent in "${AGENTS[@]}"; do
    [ -f "$DEBATE_DIR/r1_instructions_${agent}.txt" ] || return 1
  done
}

if ! have_all_r1_instructions; then
  DEBATE_AGENTS="${AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "$CLAUDE_PLUGIN_ROOT"
fi
```

Same issue exists for the R2 guard.

### 5. The verification story is overstated; the repo does not have a real green-per-commit test loop here

The plan says:

> Run `bash skills/debate/tests/*.sh` after every commit. Order chosen so each intermediate state is coherent.

But the only test file is:

```bash
DEBATE_DIR="/Users/matkatmusicllc/Programming/Charles/Programming/authv3_vps/Debates/2026-04-20T20-52-46_identify-the-1-issue-causing-customer-au"
AGENTS=(gemini codex claude)
STAGE_TIMEOUT=$((15 * 60))  # 15 min per round
```

and later:

```bash
launch_agent "$PANE_ORCHESTRATOR" "synthesis" "claude" "Claude Code v" || exit 1
send_prompt "$PANE_ORCHESTRATOR" "synthesis" "$DEBATE_DIR/synthesis_instructions.txt" || exit 1

echo "[test] synthesis launched in pane $PANE_ORCHESTRATOR — monitor $DEBATE_DIR/synthesis.md"
```

That is a live harness with:

- a hard-coded path outside this repo,
- real external agents,
- long timeouts,
- and no deterministic pass/fail coverage for the new resume logic.

So “tiny commits that leave the codebase green” is not presently true in any strong sense. The feature plan needs either:

- targeted shell tests for helper functions like topic matching, transcript matching, and lock cleanup, or
- a smaller claim about manual verification instead of “green after every commit”.

### 6. Two smaller but real correctness gaps remain

First, the plan says “exact byte equality of `topic.md` content”, but the matching snippet is:

```bash
if [ "$(cat "$dir/topic.md")" = "$topic" ]; then
```

That is **not** byte equality. Command substitution strips trailing newlines. If the design really wants exact bytes, use a file-to-file comparison:

```bash
if printf '%s\n' "$topic" | cmp -s - "$dir/topic.md"; then
  ...
fi
```

Second, commit 14 says:

> Register the skill in the plugin manifest (`.claude-plugin/plugin.json` — location TBD, mirror the `/debate` registration).

But the current `.claude-plugin/plugin.json` is just package metadata:

```json
{
  "name": "jot",
  "version": "1.1.0",
  "description": "Capture mid-development ideas and context via '/jot', '/plate', '/todo', '/todo-list', and '/todo-clean' without losing focus. '/jot' + '/todo' write TODO files via a background Claude in tmux. '/plate' tracks WIP. '/todo-list' shows open TODOs. '/todo-clean' prunes TODOs that git history says are resolved."
}
```

In this repo, skills are discovered from `skills/*/SKILL.md`; there is no existing “mirror the `/debate` registration” mechanism in `plugin.json`. That note should be removed or replaced with the actual integration point.

## Overall Assessment

The plan’s architecture is worth keeping. I would not throw it away. But I would not implement it literally from this document either.

The minimum changes before coding are:

1. Replace the retry/abort section with a real shared-entrypoint refactor.
2. Fix commit 2 to use argv arrays, not command strings.
3. Fix resume window naming and emitted paths so they derive from `DEBATE_DIR`.
4. Replace the `ls ...*.txt` guards with completeness checks over the expected agent set.
5. Downgrade or rewrite the “green after every commit” claim unless real tests are added.

If those are corrected, the rest of the plan is mostly coherent and the line anchors are close enough to be usable.
