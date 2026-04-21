# R1 — Accuracy of the Debate Scripts Extraction from `test.sh`

## Position

**The extraction is ~85% faithful to `test.sh`.** The core R1 → R2 → synthesis loop is transplanted cleanly, with several legitimate additions (`--settings`, `wait_for_file`, `tmux resize-window`). But there are four concrete defects that would cause a production `/debate` to fail or leak, plus two divergences that weaken the belt-and-suspenders safety the test had. I recommend fixing them before treating the hook path as production-ready.

---

## What was preserved correctly

Near-verbatim port of `test.sh`'s helpers into `debate-tmux-orchestrator.sh`:

- `launch_agent` (30s ready-marker poll)
- `send_prompt` (10s echo-marker poll)
- `wait_for_outputs` (5s polling loop, per-agent "reported" tracking)
- `agent_launch_cmd` / `agent_ready_marker` case tables
- Phase ordering: spawn → launch → wait → kill → repeat

These are line-for-line copies with only the log prefix changed from `[test]` → `[orch]`. That's the right move: the functions were validated end-to-end.

Additions that genuinely improve on `test.sh`:

1. **`wait_for_file "$DEBATE_DIR/synthesis.md"`** — `test.sh` was launch-and-forget. The orchestrator correctly blocks until synthesis exists, enabling a real completion signal.
2. **`tmux resize-window -t … -x 200 -y 60`** — detached sessions default to 80×24; `test.sh` ran attached so didn't need this. Correct for the hook path.
3. **Claude `--settings` + `--add-dir`** — `test.sh` ran `claude` bare with a pre-authorized dir. Prod needs permission seeding. Correctly delegated to `debate_build_claude_cmd`.

---

## Defect 1 — Hardcoded user path (portability bug, breaks the hook for anyone else)

`debate.sh` line 152:

```bash
local capture_script="$HOME/Programming/dotfiles/claude/hooks/scripts/capture-conversation.py"
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] && [ -f "$capture_script" ]; then
  hide_errors python3 "$capture_script" "$TRANSCRIPT_PATH" > "$DEBATE_DIR/context.md"
else
  printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"
fi
```

A plugin distributed from `CLAUDE_PLUGIN_ROOT` must not reach into a specific user's private dotfiles repo. For any user whose dotfiles aren't at `~/Programming/dotfiles/`, `context.md` silently becomes `(no conversation context available)` — half of the debate's value (the R1 agents reading context) disappears without a warning.

Fix: ship the capture script inside the plugin (`common/scripts/jot/capture_transcript.py` already exists per the repo layout) and call it via `$CLAUDE_PLUGIN_ROOT`:

```bash
local capture_script="$CLAUDE_PLUGIN_ROOT/common/scripts/jot/capture_transcript.py"
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] && [ -f "$capture_script" ]; then
  hide_errors python3 "$capture_script" "$TRANSCRIPT_PATH" > "$DEBATE_DIR/context.md"
else
  printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"
fi
```

`test.sh` sidesteps this because it operates on a pre-existing `DEBATE_DIR` with `context.md` already written. The bug is in the path from hook input → new debate dir, which `test.sh` never exercised.

---

## Defect 2 — Dead detection code; agent list hardcoded

`debate.sh` defines a 27-line `detect_available_agents` function (lines 26–52) that probes binaries, credentials, and runs smoke tests — but it is **never called**. Line 134:

```bash
# Fixed agent list for the TUI-driven flow. Detection logic preserved
# above (detect_available_agents) for a future re-enable.
AVAILABLE_AGENTS=(gemini codex claude)
if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
  emit_block "debate requires at least 2 agents. Found: ${AVAILABLE_AGENTS[*]}."
  exit 0
fi
```

Consequence: a user without `gemini` auth sees `debate` spawn successfully (the hook exits 0), the daemon forks, launches three panes, sends `"gemini"` to the first, and then the `launch_agent` ready-marker loop hangs for 30s before the orchestrator exits 1 to `orchestrator.log`. From the caller's perspective the hook succeeded and the synthesis file never appears. No user-visible error.

Two acceptable fixes:

**A.** Call `detect_available_agents` and remove the hardcode:

```bash
detect_available_agents   # populates AVAILABLE_AGENTS
if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
  emit_block "debate requires at least 2 agents. Found: ${AVAILABLE_AGENTS[*]}."
  exit 0
fi
```

**B.** If keeping the hardcode, delete the unused function so there's no lie. A 27-line "preserved for a future re-enable" comment is code rot — grep will show it as live and the next reader will waste time understanding why it's dead.

This is a structural red flag: the extraction kept scaffolding for a feature (detection) that was explicitly deactivated, without collapsing the code.

---

## Defect 3 — `/tmp/debate.XXXXXX` leaks every invocation

`debate.sh` line 59:

```bash
TMPDIR_INV=$(mktemp -d /tmp/debate.XXXXXX)
SETTINGS_FILE="$TMPDIR_INV/settings.json"
```

The path is passed to the forked daemon via `$SETTINGS_FILE` and baked into the claude launch command:

```bash
claude --settings '$SETTINGS_FILE' --add-dir '$CWD' --add-dir '$REPO_ROOT'
```

There is no cleanup anywhere — not in `debate.sh` (intentional, since the daemon consumes the file), not in `debate-tmux-orchestrator.sh` (no trap, no final `rm -rf`). Every `/debate` invocation creates a permanent `/tmp/debate.XXXXXX` directory.

Two consequences, one minor one major:

- **Minor:** `/tmp` fills with stale dirs over months.
- **Major:** macOS cleans `/tmp` on some reboots and via `periodic`. If the daemon is mid-debate when the cleaner fires, the next Claude launch (R2 or synthesis) tries to read a settings file that no longer exists and either fails fast or silently applies wrong permissions.

Fix: add cleanup on the daemon's exit paths. Minimum viable version in `debate-tmux-orchestrator.sh`:

```bash
DEBATE_DIR="$1"
WINDOW_NAME="$2"
SETTINGS_FILE="$3"
# …

cleanup_tmp() {
  # SETTINGS_FILE lives in /tmp/debate.XXXXXX/settings.json — remove the parent.
  local parent
  parent=$(dirname "$SETTINGS_FILE")
  case "$parent" in
    /tmp/debate.*) rm -rf "$parent" ;;
  esac
}
trap cleanup_tmp EXIT
```

The `case` guard prevents any accident from wiping `/` or `$HOME` if future refactors change `$SETTINGS_FILE`'s location.

---

## Defect 4 — Missing `rm -f` of output files before each stage

`test.sh` deliberately clears output files **before** building each stage's prompts:

```bash
# phase 2 (R1)
for agent in "${AGENTS[@]}"; do
  rm -f "$DEBATE_DIR/r1_${agent}.md"
done
# phase 6 (R2)
for agent in "${AGENTS[@]}"; do
  rm -f "$DEBATE_DIR/r2_${agent}.md"
done
# phase 9 (synthesis)
rm -f "$DEBATE_DIR/synthesis.md" "$DEBATE_DIR/synthesis_instructions.txt"
```

`debate-tmux-orchestrator.sh` has none of these. Lines 173–175 for R2:

```bash
DEBATE_AGENTS="${AGENTS[*]}" bash "$PLUGIN_ROOT/skills/debate/scripts/debate-build-prompts.sh" \
  r2 "$DEBATE_DIR" "$PLUGIN_ROOT"
```

For a fresh `DEBATE_DIR` this is harmless — the `r2_*.md` files don't exist yet. But `wait_for_outputs` tests `[ -s "$out" ]`:

```bash
for agent in "${AGENTS[@]}"; do
  local out="$DEBATE_DIR/${prefix}_${agent}.md"
  if [ -s "$out" ]; then
    done_count=$((done_count + 1))
    # …
```

**Failure scenario:** If a future retry/resume mode is added (the OLD_DISCARD directory implies one existed), or if a user re-runs `/debate` with the same topic slug and timestamp collision, a pre-existing non-empty `r2_gemini.md` from a prior run would satisfy the `-s` test immediately. The loop would count it as "done" and kill R2 panes before gemini finished, producing a corrupt synthesis based on stale R1-from-last-debate content.

This is a latent bug, not a live one. But `test.sh`'s rm-first pattern exists specifically to prevent it, and the extraction dropped it. Re-adding:

```bash
# Before R2 build
for agent in "${AGENTS[@]}"; do
  rm -f "$DEBATE_DIR/r2_${agent}.md"
done
# Before synthesis build
rm -f "$DEBATE_DIR/synthesis.md" "$DEBATE_DIR/synthesis_instructions.txt"
```

---

## Divergence 5 — Synthesis pane lifecycle

`test.sh` creates the synthesis pane up front in phase 1 as `PANE_ORCHESTRATOR` (line 112), idle through R1/R2, then reuses it for synthesis (line 186). `debate-tmux-orchestrator.sh` creates a fresh pane at synthesis time (line 203):

```bash
SYNTH_PANE=$(new_empty_pane)
```

Functionally equivalent — no defect. But worth noting: the "persistent driver pane" from `test.sh` was abandoned in favor of the fork-and-forget daemon, which is the correct architectural call (an idle pane adds nothing). The comment at top of `debate-tmux-orchestrator.sh` (`driven from debate.sh via: bash <this> … &`) documents this choice, so the divergence is intentional.

---

## Divergence 6 — `send_prompt` marker fragility inherited verbatim

Both files rely on the TUI echoing the typed command within 10s:

```bash
marker=$(basename "$instructions")
# …
if hide_errors tmux capture-pane -t "$pane_id" -p | grep -qF "$marker"; then
```

This works for gemini/codex because they echo input into a scrollback region. For `claude`, the filename appears in the input box at the top during typing, then disappears on submit — `capture-pane -p` captures only the visible pane contents. Whether the grep hits depends on the capture timing. `test.sh` validated this empirically under one specific terminal size; detached sessions at 200×60 (set by `tmux resize-window` in `debate.sh`) may behave differently.

This isn't a defect of the extraction — it's a pre-existing fragility preserved from `test.sh`. But the risk profile changed: `test.sh` was run interactively with a human watching the panes, so a 10s timeout failure was obvious. The hook-path daemon logs to `orchestrator.log`, which nobody watches. A silent `send_prompt` timeout is a far more serious failure mode than it was in the test harness.

Mitigation: increase the send_prompt timeout from 10s to 30s (negligible cost, real margin) OR switch from a grep-based marker to a file-based readiness signal. The former is a one-line fix.

---

## Summary of fixes, in priority order

| # | Defect | Severity | Lines to change |
|---|--------|----------|-----------------|
| 1 | Hardcoded `$HOME/Programming/dotfiles` path | **Blocker** — breaks for every user but one | `debate.sh:152` |
| 2 | Dead `detect_available_agents`; hardcoded agent list | High — silent failure for users without all 3 agents | `debate.sh:134` (call it or delete it) |
| 3 | No `/tmp/debate.*` cleanup | Medium — resource leak + reboot race | Add EXIT trap in `debate-tmux-orchestrator.sh` |
| 4 | Missing `rm -f` of stage outputs | Medium-low — latent, activates on retry/collision | Add 3× `rm -f` blocks in orchestrator |
| 5 | `send_prompt` 10s timeout | Medium — silent failure in detached daemon | Bump to 30s in both `launch_agent` call sites (or the helper default) |

Everything else is faithful. The skeleton of the R1 → R2 → synthesis loop was transplanted correctly and the daemon plumbing (fork, disown, log-to-file, permissions seeding) is sound. The flaws are at the boundaries — env setup (defect 1, 2, 3) and test-vs-prod assumption drift (defect 4, divergence 6) — not in the core loop.
