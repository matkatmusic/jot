# plate

Stack-of-plates WIP tracker for Claude Code. Snapshots your current working state (uncommitted changes, conversation intent, files touched) without modifying the working tree. Later, `--done` replays snapshots as structured commits.

Your files stay exactly as they are — plate only records, never resets.

## The mental model

You are debugging auth. A production alert fires. You `/plate` to capture what you were doing and why, then pivot to logging. When you come back, `--done` replays your auth snapshot as a commit with full context.

```
/plate            # snapshots auth work + intent — working tree unchanged
# ... pivot to logging, commit, push
/plate --done     # replays the auth snapshot as a structured commit
```

The stack grows when you push multiple plates. `--done` replays them oldest-first as sequential commits, each with extracted context (what, why, hypothesis, hedged confidence).

## Commands

Here are the current commands that are currently implemented (git stash create step 3 test)

| Command | Behavior |
|---|---|
| `/plate` | Snapshot current git state (non-destructive — working tree untouched). Background agent extracts intent fields from transcript. |
| `/plate --done` | Replay stack as sequential commits. Cascade up through delegated parents. |
| `/plate --drop` | Abandon top plate. Work saved as recoverable patch file in `.plate/dropped/`. |
| `/plate --next` | Walk parent delegation chain upward, print resume command for next paused ancestor. |
| `/plate --show` | Regenerate `.plate/tree.md` and open in `$EDITOR`. |

The list is small but will get bigger, potentially.

## What gets captured

Every plate push writes to `<repo>/.plate/instances/<convoID>.json`:

- `push_time_head_sha` / `stash_sha` — exact git state for replay
- `summary_action`, `summary_goal`, `hypothesis` — extracted by a background Claude
- Hedge fields (`confidence` + `reason`) when extraction certainty < 90%
- `files` changed since the previous plate
- `errors` encountered during this plate's work

Git-level durability lives under `.git/refs/plates/<convoID>/<plate-id>`, keeping stash commits alive against `git gc`.

## Requirements

| Tool | Install |
|---|---|
| `claude` | [claude.ai/download](https://claude.ai/download) |
| `jq`, `python3`, `tmux` (3.0+) | `brew install jq python@3 tmux` |
| Git repo | plate aborts outside a git worktree |

## Architecture

Matches jot: one background `claude` instance per `/plate` invocation, running in its own tmux window under a shared `plate` session. The worker reads `INPUT_FILE`, extracts structured metadata from the transcript, writes fields into the instance JSON, marks `INPUT_FILE` as `PROCESSED:`, and its `Stop` hook kills the window.

See `DESIGN.md` for the full rationale and `IMPLEMENTATION.md` for the phased build plan.

## Three-state permissions seeding

`plate` ships a bundled default permission allowlist at `assets/permissions.default.json`. On first `/plate`, the three-state seeder copies it to `${CLAUDE_PLUGIN_DATA}/permissions.local.json` and records its SHA. On plugin upgrade:

- **user never touched it** (SHA matches prior) → safe to overwrite with newer default
- **user edited it** (SHA diverged) → leave alone, log one-line diff hint

The worker's per-invocation `settings.json` is generated from this template with `${PLATE_ROOT}` / `${HOME}` placeholders expanded and a `Bash(*)` deny rule injected so the bg-agent cannot shell out.

## Data layout

```
<worktree>/.plate/
├── instances/<convoID>.json    # per-session source of truth
├── dropped/<convoID>/*.patch   # recoverable abandoned work
├── inputs/<convoID>_<ts>.txt   # background agent job payloads
└── tree.md                     # derived view, regenerated lazily

.git/refs/plates/<convoID>/<plate-id>   # named refs (NOT under .plate/)
```

`.plate/` is auto-gitignored on first creation.

## Testing

```bash
bash tests/test-push-smoke.sh   # hook → snapshot → JSON mutation → tmux launch stub
bash tests/test-done-smoke.sh   # replay 2 plates → 2 commits + cascade
bash tests/test-drop-smoke.sh   # abandon → patch file + working-tree restore
```

All three suites run headless (tmux/claude stubbed).

## Status

**0.1.0-dev** — Phases 0–8 implemented. E2E bg-agent + path-3 dropdown testing requires a live `claude` install; see the task list in-session or `IMPLEMENTATION.md §8` for the remaining punch-list.
