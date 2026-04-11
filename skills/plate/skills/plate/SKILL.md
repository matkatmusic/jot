---
name: plate
description: Stack-of-plates WIP tracker — path-3 parent selection for a new session entering a repo with existing plate state.
---

# Plate — Parent Selection

You are the foreground claude that received a `/plate` prompt. The hook has determined this is a new session in a repo where other plate instances already exist ("path 3" in the design). You must present a parent-selection dropdown before pushing.

## Step 1 — Load registration context

Read the pending registration file the hook dropped for you:

```
.plate/pending-registration.json
```

It contains:
- `session_id` — your current session ID (call this `$SID`)
- `transcript_path` — path to your conversation transcript (`$TP`)
- `cwd` — absolute working directory (`$CWD`)
- `plate_scripts_dir` — absolute path to the plate plugin's `scripts/` directory (`$SCRIPTS`)

**Do NOT use `$CLAUDE_PLUGIN_ROOT` or any bash env variable to locate plate scripts.** The user may have other plugins loaded that set that variable to a different plugin's path. Always use `plate_scripts_dir` from the registration JSON.

## Step 2 — Enumerate candidate parents

Run this bash command (substituting the actual path from the registration JSON):

```
bash <plate_scripts_dir>/list-paused-plates.sh
```

Each output row is pipe-delimited: `convoID|plateID|label|synopsis|pushed_at`.

## Step 3 — Branch on output

**If output is EMPTY** (no paused plates anywhere):
1. Register as top-level:
   `bash <plate_scripts_dir>/register-parent.sh <session_id> none`
2. Push:
   `bash <plate_scripts_dir>/push.sh <session_id> <transcript_path> <cwd>`
3. Delete `.plate/pending-registration.json`
4. Reply: `plate registered + pushed (top-level)`

**If output has 1+ rows**:
1. Build options for `AskUserQuestion`:
   - For each row, format as: `<label> → "<synopsis>" (paused at <pushed_at>)`
   - Prepend `Top-level (no parent)` as the first option
2. Call `AskUserQuestion` with:
   - header: `Parent`
   - question: `Pick a parent plate (or top-level)`
   - multiSelect: false
3. Parse the user's selection. Extract the `convoID` and `plateID` from the row they picked (or pass `none ""` for top-level).
4. Register:
   `bash <plate_scripts_dir>/register-parent.sh <session_id> <parent_convo> <parent_plate>`
5. Push:
   `bash <plate_scripts_dir>/push.sh <session_id> <transcript_path> <cwd>`
6. Delete `.plate/pending-registration.json`
7. Reply in one line: `plate registered + pushed: <synopsis>`

## Rules

- NEVER push before registration completes — parent_ref must be set first.
- NEVER skip the `AskUserQuestion` step when paused plates exist — the user must explicitly choose.
- If the pending-registration file is missing, reply: `plate: no registration context — rerun /plate` and stop.
- Always resolve script paths via `plate_scripts_dir` from the registration JSON. Do not trust `$CLAUDE_PLUGIN_ROOT` in the shell env — it may point at a different plugin.
- When running push.sh, you MUST export `CLAUDE_PLUGIN_ROOT=<plate_plugin_root>` and `CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/plate-jot-dev` (or the appropriate plate data dir) so the script can find its lib + python helpers. Use `plate_plugin_root` from the registration JSON.
