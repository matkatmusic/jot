# Independent Analysis of `debate-resume.md` Plan

Overall, the plan correctly addresses the problem of orphaned partial debate runs and adds robust idempotency and resuming mechanisms. The state machine defined by lockfiles, stage outputs, and exact `topic.md` matching is conceptually sound. 

However, there are **four critical bugs** in the provided code snippets that will cause runtime failures or silent exits if implemented exactly as written. 

---

## 1. Word Splitting Bug in `_try_agent_models` (Commit 2)

**Risk:** The string variable `$smoke_cmd` contains quoted arguments (e.g. `'gemini -p "Reply with exactly: ok"'`). When passed unquoted to `_run_with_timeout`, bash performs word splitting but **does not evaluate the quotes**. The quotes are passed as literal characters to the agent binary, which will cause the smoke test to fail because the prompt string is shattered into multiple arguments.

**Evidence of Risk:**
If `$smoke_cmd` is evaluated as `_run_with_timeout 30 $smoke_cmd`, the executable `gemini` receives the arguments: `-p`, `"Reply`, `with`, `exactly:`, `ok"`. The quotes remain intact, breaking the CLI parser.

**Solution:**
You must use `eval` so bash properly parses the string into an argument array before invoking the timeout command.

```bash
# Correct Implementation for _try_agent_models (Commit 2):
    if [ "${#models[@]}" -eq 0 ]; then
      if eval "_run_with_timeout 30 $smoke_cmd" >/dev/null 2>&1; then
        echo ""
        return 0
      fi
      return 1
    fi

    local m
    for m in "${models[@]}"; do
      # Note the escaped quotes around $m
      if eval "_run_with_timeout 30 $smoke_cmd --model \"\$m\"" >/dev/null 2>&1; then
        echo "$m"
        return 0
      fi
      hide_errors printf '%s debate: %s model %s failed smoke test\n' "$(date -Iseconds)" "$agent" "$m" >> "$LOG_FILE"
    done
```

---

## 2. Hallucinated Function `debate_main_resume` (Commit 14)

**Risk:** In `/debate-retry`, the script attempts to call `debate_main_resume "$best"`. This function is never defined in the plan, nor does it exist in the current codebase.

Additionally, simply calling `debate_main` after setting `TOPIC` is dangerous: `debate_main` does a global search for the *most recent* debate matching the exact topic text. But `/debate-retry` finds the debate associated with the *current conversation transcript*. They could resolve to different directories!

**Solution:**
Allow `debate_main` to accept an explicit `DEBATE_DIR` override to bypass the global search, guaranteeing we resume the exact directory found by the transcript search.

```bash
# Correct Implementation for debate.sh (Commit 10 - override support):
local existing
if [ -n "$FORCE_RESUME_DIR" ] && [ -d "$FORCE_RESUME_DIR" ]; then
  existing="$FORCE_RESUME_DIR"
else
  existing=$(find_matching_debate "$REPO_ROOT" "$TOPIC")
fi

# Correct Implementation for debate_retry_main (Commit 14):
  TOPIC=$(cat "$best/topic.md")
  FORCE_RESUME_DIR="$best" debate_main
```

---

## 3. Exact Topic Match Fails on Trailing Newlines (Commit 10)

**Risk:** `find_matching_debate` uses `if [ "$(cat "$dir/topic.md")" = "$topic" ]; then`. The `$(cat ...)` command substitution strips **all** trailing newlines from the file's content. Because the plan writes to the file using `printf '%s\n' "$TOPIC"`, if `$TOPIC` itself contains a trailing newline, the string equality check will fail, breaking idempotency entirely.

**Solution:**
Use `cmp -s` with process substitution to compare the exact bytes on disk against the exact string in memory, including all newlines.

```bash
# Correct Implementation for find_matching_debate (Commit 10):
find_matching_debate() {
  local repo_root="$1" topic="$2"
  local dir match_ts=""
  local best=""
  for dir in "$repo_root"/Debates/*/; do
    [ -f "$dir/topic.md" ] || continue
    # Safe, exact byte comparison handling newlines and NULs properly
    if cmp -s "$dir/topic.md" <(printf '%s\n' "$topic"); then
      local ts
      ts=$(basename "$dir")
      if [[ "$ts" > "$match_ts" ]]; then
        match_ts="$ts"
        best="${dir%/}"
      fi
    fi
  done
  printf '%s' "$best"
}
```

---

## 4. Silent Exit on Launch Timeout (Commit 6 & 13)

**Risk:** Commit 13 explicitly adds a mechanism to write a detailed `FAILED.txt` when a stage times out in `wait_for_outputs`. However, if `launch_agent` times out while waiting for the `ready_marker` (Commit 6), it returns `1`. The call site is `launch_agent ... || exit 1`. This immediately terminates the daemon, leaving behind a live lockfile, no `FAILED.txt`, and giving the user no feedback on why the run stalled.

**Solution:**
Ensure `launch_agent` writes a `FAILED.txt` or signals the error appropriately before returning, or handle the `exit 1` gracefully.

```bash
# Correct Implementation for launch_agent (Commit 6):
  while [ "$elapsed" -lt "$timeout" ]; do
    if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$ready_marker"; then
      echo "[orch] ${stage}/${agent} ready after ${elapsed}s (pane $pane_id)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  
  # Ensure failure is captured before exit
  echo "[orch] TIMEOUT: ${stage}/${agent} not ready within ${timeout}s" >&2
  printf '# debate FAILED\n\nstage: %s launch\nagent: %s\nreason: launch timeout' "$stage" "$agent" > "$DEBATE_DIR/FAILED.txt"
  return 1
```

## Position
The overall architectural plan is excellent and should be executed, but the script snippets must be corrected with the modifications above before proceeding, to prevent broken smoke tests and incomplete state transitions.