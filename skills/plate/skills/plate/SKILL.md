---
name: plate
description: Stack-of-plates WIP tracker — handles parent selection (/plate) and finalization (/plate --done).
argument-hint: [<empty>] [--done] [--drop] [--next] [--show]
---

# Plate — Skill Body

You are the foreground claude that received a `/plate` prompt. The hook passed this prompt through because it requires your interaction capabilities (AskUserQuestion, tool use).

## Variant Detection

Check the user's prompt:
- If `/plate --done` → follow the **Done** section below
- If `/plate` (no flag) → follow the **Parent Selection** section below

---

# Done

The user wants to finalize their plate stack — replay all stacked plates as sequential commits.

## Step 1 — Load command context

Read the command context file the hook dropped:

```
.plate/pending-command.json
```

It contains:
- `session_id` — your current session ID (`$SID`)
- `plate_scripts_dir` — absolute path to the plate scripts directory (`$SCRIPTS`)
- `python_dir` — absolute path to the plate python directory (`$PYDIR`)
- `plate_plugin_root` — absolute path to the plugin root (`$PLUGIN_ROOT`)

If the file is missing, reply: `plate: no command context — rerun /plate --done` and stop.

## Step 2 — Check for open children

Run:
```
INSTANCE_FILE=".plate/instances/<session_id>.json" python3 <python_dir>/check_live_children.py
```

If the output is `yes`, delegated children are still open. Call `AskUserQuestion`:
- question: `Delegated children are still open. How do you want to proceed?`
- options: `["Cancel — do not finalize", "Orphan children — finalize anyway", "Keep links — finalize and preserve child references"]`

If the user picks Cancel, reply `plate --done cancelled` and stop. Otherwise proceed.

## Step 3 — Run done.sh

Export the plugin environment, then run the done script:

```bash
export CLAUDE_PLUGIN_ROOT=<plate_plugin_root>
export CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/plate-jot-dev
bash <plate_scripts_dir>/done.sh <session_id>
```

## Step 4 — Relay output

The script prints a commit summary and resume pointer. Relay this output to the user verbatim.

## Step 5 — Cleanup

Delete `.plate/pending-command.json`.

---

# Parent Selection

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
