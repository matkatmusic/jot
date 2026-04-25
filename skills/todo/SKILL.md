---
name: todo
description: Capture a mid-development TODO via "/todo <idea>". Reads a pending-context JSON file left by the UserPromptSubmit hook, asks clarifying questions if the idea is vague, then spawns a background Claude worker in tmux that scans git context and writes the final numbered TODO file. Use when user says "/todo", "park this idea", "save this for later", or "add a todo".
argument-hint: <idea>
---

# /todo — Idea Parking Lot

You are the foreground claude that received a `/todo` prompt. The UserPromptSubmit hook has written a pending-context file — you must read it, optionally clarify, then invoke the launcher.

## Step 1 — Load pending context

Use the `Glob` tool (NOT `Bash ls`) to find files matching `Todos/.todo-state/pending-*.json`. `Glob` sorts by modification time (newest first), so to pick the **oldest** you want the last entry in the Glob result. If only one file matches, use it.

Read that one file with the `Read` tool. It contains:
- `session_id`, `transcript_path`, `cwd`, `repo_root`, `idea`, `timestamp`, `todo_plugin_root`, `todo_scripts_dir`, `pending_file`

Why oldest-first: the hook uses `mktemp` for a per-invocation unique name so same-session reruns never collide. Oldest-first matches FIFO order of user invocations.

If no pending file exists, reply `todo: no pending context — rerun /todo <idea>` and stop.

## Step 2 — Clarify if vague

Inspect the `idea` field. If it is empty, or clearly underspecified (examples of vague: "fix that thing", "do the thing", "clean up stuff", "add a feature"), use `AskUserQuestion` with 1–3 targeted questions. Sample questions:
- "Which feature, file, or system does this TODO affect?"
- "Is this a bug fix, new behavior, refactor, or something else?"
- "Is there a specific function, branch, or ticket this relates to?"

Stop asking as soon as the user signals enough detail. Do NOT over-ask.

If the idea was already clear (contains a verb, a noun, and enough specificity for an implementer to start), skip this step entirely.

Merge the clarification answers (if any) into a single refined idea string.

## Step 3 — Launch the background worker

Invoke the launcher via Bash — this is the **only** Bash call this skill needs:

```
bash <todo_scripts_dir>/todo-launcher.sh <session_id> <refined_idea> <pending_file>
```

Substitute the actual `todo_scripts_dir`, `session_id`, and `pending_file` values from the pending JSON; pass the refined idea as the second argument (quote it). The launcher:
1. writes `Todos/<timestamp>_input.txt` with the full context block,
2. spawns a per-invocation tmux pane with the background Claude worker,
3. **deletes the pending file** after a successful spawn — you do NOT need to clean up.

Capture the launcher's stdout — it prints the absolute path of the input.txt it wrote.

## Step 4 — Reply

Reply in exactly one line (no preamble, no headers):

```
[todo] captured in <input_file_path> — background worker writing final TODO file
```

## Rules

- NEVER write the final TODO file yourself — the background worker does that.
- NEVER call `emit_block` or any hook-output JSON.
- Do NOT use `Bash ls` or `Bash rm` in this skill — use `Glob` for Step 1 and let the launcher handle cleanup.
- If the user cancels clarification (answers with "cancel" or "nevermind"), still call the launcher with the original idea so the pending file is cleaned up, then reply `[todo] cancelled`.
- Do NOT source or call `$CLAUDE_PLUGIN_ROOT` — always resolve scripts via `todo_scripts_dir` from the pending JSON (other plugins may have set a different value in the shell env).
