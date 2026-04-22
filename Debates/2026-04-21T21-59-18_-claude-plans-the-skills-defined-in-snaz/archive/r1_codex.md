# Round 1 — Codex Analysis

## Verdict

The migration direction is right. Splitting the three commands by UX is the correct call:

- `/todo`: foreground clarification, background write
- `/todo-clean`: foreground-only
- `/todo-list`: synchronous hook block

I would not ship the plan as written. `/todo` still has one addressability bug and one real concurrency bug, and the proposed permissions file carries forward an existing path-anchor mistake.

## What Is Good

The plan is strongest where it reuses existing patterns instead of inventing new ones:

- Extending [scripts/orchestrator.sh](/Users/matkatmusicllc/Programming/jot/scripts/orchestrator.sh) for `/todo` and `/todo-list` is consistent with the current `/jot`, `/plate`, `/debate` dispatch model.
- Keeping `/todo-clean` out of the hook path is correct. It needs `AskUserQuestion`, so it should behave like the interactive side of `/plate`, not like `/jot`.
- Copying lifecycle hooks into a per-invocation temp dir is the right durability pattern. [skills/jot/scripts/jot.sh](/Users/matkatmusicllc/Programming/jot/skills/jot/scripts/jot.sh) already proves why that matters during plugin updates.

## Blocking Issues

### 1. The foreground `/todo` skill has no reliable way to locate `pending-<session_id>.json`

The plan makes the hook write a session-scoped file:

```bash
PENDING_FILE="$STATE_DIR/pending-${SESSION_ID}.json"
```

Then the proposed `skills/todo/SKILL.md` says the foreground model must read:

```text
Todos/.todo-state/pending-<session_id>.json
```

and claims the current session id is “available in the transcript metadata”.

That is the weak point. The working foreground pattern in this repo does **not** depend on the model rediscovering its own session id. `/plate` avoids that entirely by writing a stable handoff file:

```bash
cat > "${PLATE_ROOT}/pending-command.json" <<CMD
{
  "variant": "--done",
  "session_id": "$SESSION_ID",
  "cwd": "$CWD",
  "plate_scripts_dir": "$SCRIPTS_DIR",
  "plate_plugin_root": "$CLAUDE_PLUGIN_ROOT",
  "python_dir": "$PYTHON_DIR"
}
CMD
```

That is addressable from the skill body with no hidden runtime dependency. The `/todo` design, by contrast, assumes a session-id lookup mechanism the plan never demonstrates.

My recommendation: change the handoff so the skill body can find it deterministically without reconstructing session identity. Either:

- mirror `/plate` and use a stable `pending-command.json`, or
- have the hook also write a stable pointer file that contains the exact pending JSON path.

Without that, `/todo` is one runtime assumption away from “rerun /todo” loops.

### 2. ID allocation is racy in exactly the place this design adds concurrency

The proposed allocator is:

```bash
max=0
for f in "$TODOS"/[0-9][0-9][0-9]_*.md "$DONE"/[0-9][0-9][0-9]_*.md; do
  base=$(basename "$f")
  n="${base:0:3}"
  n=$((10#$n))
  if [ "$n" -gt "$max" ]; then max="$n"; fi
done

next=$((max + 1))
printf '%03d\n' "$next"
```

That is fine in a single-threaded world. This plan explicitly creates a multi-pane background-worker world. Two `/todo` invocations close together can both read the same max id before either writes its file.

The plan already contains the correct fix later:

```bash
sentinel="$REPO_ROOT/Todos/.todo-state/id-${next_padded}.claim"
while ! (set -C; : > "$sentinel") 2>/dev/null; do
  next=$((next + 1))
  next_padded=$(printf '%03d' "$next")
  sentinel="$REPO_ROOT/Todos/.todo-state/id-${next_padded}.claim"
done
printf '%s\n' "$next_padded"
```

I would move that from “known risk / low priority” into the initial implementation. The architecture is parallel by design, so atomic ID claiming is not optional polish.

### 3. The proposed worker permissions inherit a path-anchor bug

The current bundled jot permissions file documents the anchor semantics itself:

```json
"_doc": "... // = filesystem absolute, ~ = home, / = project root, bare = cwd-relative ..."
```

The proposed `/todo` permissions include:

```json
"Read(${HOME}/.claude/projects/**)"
```

[common/scripts/jot/expand_permissions.py](/Users/matkatmusicllc/Programming/jot/common/scripts/jot/expand_permissions.py) expands `${HOME}` literally:

```python
expanded = [
    item
      .replace("${CWD}", os.environ["CWD"])
      .replace("${HOME}", os.environ["HOME"])
      .replace("${REPO_ROOT}", repo_root)
    for item in allow
]
```

So that rule becomes `Read(/Users/.../.claude/projects/**)`. Per the repo’s own anchor comment, a single leading `/` is project-root anchored, not filesystem-absolute. The result is the wrong rule.

Recommendation: do not expand `${HOME}` here at all. Use Claude’s home anchor directly:

```json
"Read(~/.claude/projects/**)"
```

If you want templating, then add a dedicated home-absolute expansion path that emits `//...`, not `/...`.

## Secondary Notes

- The plan text drifts a bit on artifacts: the target tree omits `scan-open-todos.sh` and `format_open_todos.py`, but later sections require both. That is documentation drift, not an architecture problem.
- `/todo-launcher.sh` searching for the pending file by probing `$PWD` and `git rev-parse --show-toplevel` is serviceable, but if you keep the session-scoped file model, pass the exact pending-file path into the launcher instead. That removes another discovery step.

## Position

I support the migration, but only with three amendments folded into the first implementation pass:

1. Make the foreground `/todo` handoff deterministically addressable from the skill body.
2. Make numeric ID assignment atomic now, not later.
3. Fix the home-directory permission rule to use the correct anchor.

With those changes, the plan is coherent and fits the existing jot/plate/debate architecture. Without them, `/todo` will be flaky in the exact scenarios this migration is supposed to improve.
