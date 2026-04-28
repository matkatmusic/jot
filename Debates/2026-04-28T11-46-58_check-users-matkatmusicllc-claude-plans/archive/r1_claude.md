# R1 — Independent Analysis: `calm-squishing-eclipse.md`

## Verdict

**Approve with one required fix and two recommended changes.** The plan's structure and risk-reasoning are sound; the parallelism approach is correct for bash 3.2. However, the atomicity fix in §4 contains a **latent bug that defeats its own purpose**, and two observability gaps weaken the verification story.

---

## What the plan gets right

1. **Backgrounding the full `launch_agent + send_prompt` pair (Decision 1).** Splitting only `launch_agent` would re-serialize on `send_prompt`, recovering perhaps half the win. The pair scope is correct.
2. **Wait-all-then-check (Decision 2).** `wait -n` is unavailable on macOS bash 3.2 (verified: `BASH_VERSION` empty / `BASHPID=UNSET` → bash 3.2 path). Iterating PIDs with positional `wait $pid` is the right portable pattern.
3. **Subshell isolation analysis is accurate.** `_stash` writes to `CURRENT_MODEL_<agent>` only inside `wait_for_outputs` (line 364–366 → `retry_pane_with_next_model` → `_stash`), which runs in the **main shell after launch**. Subshell-only mutations (lock files at line 289, stage outputs from agent CLIs) are filesystem-mediated, so the parent re-reads them after `wait`. No state crosses the subshell boundary that needs to.
4. **`tmux send-keys` server-side serialization.** The tmux server is single-threaded for command processing; concurrent `send-keys` from 3 subshells is safe.
5. **Test-harness ordering claim verified.**
   - `resume-integration-test.sh:275` writes via `>>` (atomic append for short lines, no torn writes).
   - Line 342, 347, 394 all sort before compare. Order-independent. ✓

---

## Critical issue (REQUIRED FIX): tempfile naming in `write_failed`

The plan's §4 acknowledges a `$$` collision concern and offers `$BASHPID` as a fallback. Both are broken on the target environment.

### Evidence

```
$ bash -c '( echo "child BASHPID=${BASHPID:-UNSET} dollar=$$" )'
child BASHPID=UNSET dollar=43762
```

`BASHPID` is unset on macOS system bash (3.2.57). And `$$` returns the **parent daemon's PID** in every backgrounded subshell — POSIX-mandated behavior:

> `$$` shall expand to the decimal process ID of the invoked shell. **Within a subshell, $$ shall expand to the same value as that of the current shell.**

So with the plan's code, all three concurrent `write_failed` calls compute:

```
tmpfile="$DEBATE_DIR/.FAILED.txt.$$"   # identical across subshells
```

…and clobber each other's tempfile mid-write. Sequence:

```
t=0  subshell-A: open .FAILED.txt.12345 with O_TRUNC, begin streaming agent dumps
t=1  subshell-B: open .FAILED.txt.12345 with O_TRUNC  ← truncates A's in-flight write
t=2  subshell-A: continues writing (now appending into B's freshly-opened file)
t=3  subshell-A: mv .FAILED.txt.12345 → FAILED.txt   (interleaved A+B content)
t=4  subshell-B: writes its own content (no longer to the moved tempfile;
                 actually behaves as if file was unlinked-while-open;
                 mv would then ENOENT)
```

The atomicity fix as written produces **the same torn output it claims to prevent**, plus a spurious `mv` failure on the late writer.

The plan's parenthetical "harmlessly overwrites each other's tempfile" is wrong: the writes are **concurrent**, not sequential. Two redirects to the same path with `>` create a race on the inode, not a serialized append.

### Required fix: use `mktemp`

`mktemp` is available on every macOS shipping bash, returns a guaranteed-unique path, and works identically in subshells:

```bash
write_failed() {
  local stage="$1" reason="$2"
  local tmpfile
  tmpfile=$(mktemp "$DEBATE_DIR/.FAILED.txt.XXXXXX") || return 1
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
        hide_errors tmux capture-pane -t "$pane_id" -p -S -200 \
          || printf '(pane capture unavailable)\n'
        printf '```\n'
      else
        printf '(no pane captured — lock file missing or malformed)\n'
      fi
    done
  } > "$tmpfile"
  mv "$tmpfile" "$DEBATE_DIR/FAILED.txt"
}
```

`mktemp template-with-XXXXXX` is portable across BSD (macOS) and GNU. Each subshell gets its own path; `mv` is atomic; last-rename-wins is preserved with no torn intermediate state.

Verification §7 (no `.FAILED.txt.*` lingering) is now meaningful — with `$$`, all three subshells targeted the same path and the test would pass even with the bug.

---

## Recommended change 1: keep the timing instrumentation permanent

Plan §3 says:

> Add `date +%s` capture immediately before and after `launch_agents_parallel r1` (temporary, removed before commit).

Removing observability that costs ~1 line is a regression. Future debugging of "is this still parallel?" or "did something drift back to serial?" needs this signal. Make it permanent in the helper itself:

```bash
launch_agents_parallel() {
  local stage="$1" panes_var="$2"
  local pids=() agents_run=() i agent pane_id fail=0
  local t0; t0=$(date +%s)
  # ... existing body ...
  local t1; t1=$(date +%s)
  echo "[orch] ${stage} parallel launch wall-clock: $((t1 - t0))s (${#pids[@]} agents)"
  return "$fail"
}
```

This costs nothing, is line-buffered safe (short line, well below PIPE_BUF=4096), and gives a continuous regression signal in `orchestrator.log`. If a future change reintroduces serialization, the wall-clock jumps from ~150s to ~450s and the line makes it obvious.

---

## Recommended change 2: tighten verification §6 to fail-loudly on the real bug

The plan's verification §6 checks for "exactly one `# debate FAILED` header." With `$$` collision (current plan code), three concurrent writes to the **same** tempfile path could in some interleavings still produce a single well-formed-looking output if writes happen to align — i.e., the test is **non-deterministic** on the buggy code path. With `mktemp`, it is deterministic.

Add a stricter assertion that exercises the failure mode directly:

```bash
# In test setup: stub launch_agent to call write_failed concurrently.
# Spawn 3 concurrent write_failed calls with distinguishable agent rosters.
# Assert: exactly one of the three wrote the final FAILED.txt (last-wins),
# AND no .FAILED.txt.* tempfiles remain,
# AND the surviving FAILED.txt parses cleanly with all 3 ### sections.
( write_failed r1 "reason A" ) &
( write_failed r1 "reason B" ) &
( write_failed r1 "reason C" ) &
wait
[ -f "$DEBATE_DIR/FAILED.txt" ] || fail "no final file"
ls "$DEBATE_DIR"/.FAILED.txt.* 2>/dev/null && fail "stray tempfile"
grep -c '^# debate FAILED$' "$DEBATE_DIR/FAILED.txt" | grep -qx 1 \
  || fail "header count != 1 → torn output"
grep -c '^### ' "$DEBATE_DIR/FAILED.txt" | grep -qx 3 \
  || fail "section count != 3 → torn or truncated"
```

With `$$`, this test is flaky-to-passing depending on timing. With `mktemp`, it is reliably passing.

---

## Minor observations (non-blocking)

1. **`agents_run` array indexing is correct.** When agents are skipped (already-complete or lock-held branches), `pids[]` and `agents_run[]` are appended together; the wait loop iterates `pids` indices. Both arrays stay aligned. Worth a one-line comment in the helper to prevent future drift:
   ```bash
   # pids[i] and agents_run[i] are kept aligned: every &-fork appends to both,
   # skipped agents append to neither. Do not iterate AGENTS for the wait loop.
   ```

2. **`agent_launch_cmd "$agent"` runs inside the subshell.** It calls `_lookup CURRENT_MODEL "$a"` which `eval`s `${CURRENT_MODEL_<agent>:-}`. The subshell inherits these scalars at fork time (set by `init_agent_models` at line 416, before any backgrounding). Correct as-is. No fix needed.

3. **STAGE_TIMEOUT (900s) is unchanged.** With serial launch consuming up to 360s of the 900s budget, parallel launch frees ~210s for actual agent work. Net win, no resize required.

4. **Concurrent `[orch]` log lines to orchestrator.log.** Daemon was forked with `>> orchestrator.log 2>&1`. All subshell `echo`s are well below PIPE_BUF (4096 bytes on macOS), so write(2) is atomic per line. No interleaving within a line. Safe.

5. **Pane creation loop (lines 432–435, 474–477).** Plan correctly leaves this serial — `new_empty_pane` calls `tmux_retile`, which mutates window layout; serializing pane creation is desirable. Each `new_empty_pane` is sub-second. Not a parallelism candidate.

---

## Summary

| Item | Status | Action |
|------|--------|--------|
| Helper structure (Decision 1+2+3) | Correct | Ship as designed |
| Subshell isolation analysis | Correct | Ship as designed |
| `tmux send-keys` concurrency | Safe | Ship as designed |
| `write_failed` `$$` tempfile | **Broken on macOS bash 3.2** | **Replace with `mktemp`** |
| Timing instrumentation | Plan removes before commit | Keep permanent in helper |
| Verification §6 determinism | Flaky on `$$`, fine on `mktemp` | Strengthen to triple-concurrent assertion |
| Pane-creation serial | Correct, intentional | No change |

Without the `mktemp` fix, the plan ships the exact race condition §4 was added to prevent. With it, the plan is good to execute.
