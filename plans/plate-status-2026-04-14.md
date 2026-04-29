# `/plate` skill — state snapshot 2026-04-14

Captured at the request of the user, after a long historic conversation that drafted the design (`IMPLEMENTATION.md`), implemented phases 0–8, and then the user did a major restructure I was not present for.

## Headline

**v1.0.0 has shipped** (`15db5d3 release(1.0.0): fix /plate --done, tighten push.sh, update docs`). The skill is meaningfully further along than where this conversation left it. Several open issues remain — see "Open items" below.

## Commits since this conversation last touched plate

Oldest → newest:

| Commit | Summary |
|---|---|
| `9434c4c` | fix(jot,plate): split send-keys text and Enter in all remaining call sites |
| `e3daee9` | refactor(jot,plate): extract tmux send-keys to scripts/lib/tmux-send.sh |
| `d6c88a7` | refactor(jot,plate): consolidate shared libs, eliminate `\|\| true` and `>/dev/null` |
| `d5712ea` | refactor(plate): eliminate `\|\| true` and raw `>/dev/null` across all plate scripts |
| `0e63e8c` | refactor(plate): extract all inline python heredocs to standalone .py files |
| `db93f5e` | refactor(jot,plate): split into function files + orchestrator entry points |
| `0b6662d` | refactor: consolidate directory structure — scripts/jot/, scripts/plate/, python/plate/ |
| `bc4f8ee` | fix(plate): retarget dev-marketplace symlink to repo root, wire --done/--show/--next |
| `1b5ab83` | WIP |
| `94c6bd8` | finished reorganizing files for jot and plate |
| `15db5d3` | release(1.0.0): fix /plate --done, tighten push.sh, update docs |
| `5079476` | added usage docs for each common script (shell/python) |
| `d7ec23d` | moved skill-specific tests to their skill/test folder |

## Current layout (verified)

### `skills/plate/scripts/` (19 shell scripts)
```
assets/permissions.default.json
assets/permissions.default.json.sha256
branch-snapshot.sh             # v1 — STILL has the `git stash create -u` bug
branch-snapshot.v2.sh          # v2 — fix using temp-index trick (NOT wired in)
done.sh
drop.sh
list-paused-plates.sh
next.sh
paths.sh
plate-orchestrator.sh          # new entry point
plate-session-start.sh
plate-worker-end.sh
plate-worker-start.sh
plate-worker-stop.sh
plate.sh
prompts/bg-agent.md
prompts/drift-judge.md
push.sh                        # tightened in v1.0.0
register-parent.sh
render-tree.sh
show.sh
snapshot-stash.sh              # still in use; uses `git stash create` (no -u)
```

### `common/scripts/plate/` (16 Python helpers, all standalone — no inline heredocs)
```
append_plate_to_stack.py
build_settings_json.py
cascade_parent_chain.py
check_drift_alert.py
check_live_children.py
check_rolling_intent_refresh.py
clear_drift_alert.py
commit_message.py
instance_rw.py
list_paused_plates.py
next_resume_point.py
print_resume_pointer.py
register_parent.py
render_tree.py
transcript_parse.py
verify_stash_refs.py
USAGE.md
```

### `common/scripts/` (shared shell libs)
```
claude-launcher.sh
git.sh
hook-json.sh
invoke_command.sh
lock.sh
permissions-seed.sh
platform.sh
silencers.sh
tmux-launcher.sh
tmux-send.sh
tmux.sh
USAGE.md
```

### `skills/plate/`
- `SKILL.md` — at this path now (was `skills/plate/skills/plate/SKILL.md` in v0.1)
- `DESIGN.md`, `IMPLEMENTATION.md`, `README.md` — present
- `tests/` — `test-{push,done,drop}-smoke.sh`, `plate-e2e-live.sh`, `plate-claude-e2e.sh`, `fixtures/sample-transcript.jsonl`

## What's working (per release notes)

- `/plate` push (snapshot via `snapshot-stash.sh`, named ref under `refs/plates/<convoID>/<plate-id>`)
- `/plate --done` — the v1.0.0 release explicitly fixed this
- `/plate --drop` — patch + restore via `drop.sh`
- `/plate --next` and `/plate --show` — wired in `bc4f8ee`
- Background agent flow (orchestrator + per-window settings.json + tmux dispatch)
- Three-state permissions seeding (now lives in `common/scripts/permissions-seed.sh`)
- All inline python heredocs replaced by standalone modules under `common/scripts/plate/`
- Path-3 parent selection (SKILL.md + pending-registration handoff)

## Open items / known gaps

1. **`branch-snapshot.sh` still has the `-u` bug.** v1 (`git stash create -u "$MSG"`) silently drops untracked files. Fix exists in `branch-snapshot.v2.sh` (temp-index approach) but was never promoted. Neither is wired into `push.sh` — production still uses `snapshot-stash.sh` which has the same `-u`-doesn't-work behavior (it doesn't pass `-u`, so untracked files were never expected to be captured).

2. **`skills/plate/hooks/hooks.json` missing on disk.** SessionStart system-reminder showed it pointing at `${CLAUDE_PLUGIN_ROOT}/scripts/plate/plate-orchestrator.sh` — that path doesn't exist (the orchestrator lives at `scripts/plate-orchestrator.sh`, no `plate/` subdir). The file itself wasn't found on disk during status check. **Hook dispatch may be currently broken** — needs verification.

3. **Branch-based plate model never landed.** The historic conversation explored switching from `git stash create` + `refs/plates/<id>/<name>` (cumulative tree as dangling commit) to a real `<branch>-plate` branch with `commit-tree` chained commits. The user verified the model live (3-step test passed where stash-pop fails) and asked me to write `branch-snapshot.sh`, then `branch-snapshot.v2.sh`. v3 (combining best of mine + codex + gemini reviews) was offered but never written. The v2 file sits unused.

4. **`dev-marketplace/.claude-plugin/marketplace.json` missing.** Dev install path may be broken.

5. **v2 vs v1 of branch-snapshot.** Both files coexist; no decision recorded as to which is canonical, and neither is referenced from any caller.

## Suggested next actions (not yet started)

- Restore `skills/plate/hooks/hooks.json` pointing at the correct paths (`scripts/plate-orchestrator.sh`, `scripts/plate-session-start.sh`).
- Decide branch-snapshot direction: replace v1 with v2, OR ship v3 (codex + gemini review consolidation), OR delete both and stay on `snapshot-stash.sh` if the cumulative-stash model is what the user wants long-term.
- Restore `dev-marketplace/.claude-plugin/marketplace.json` so the dev-install workflow continues to work.
- Wire either `branch-snapshot` variant into `push.sh` if the branch model is being adopted.

## Source labels for future search

- `plate-tree` — full file tree under `skills/plate/`
- `common-scripts-plate` — Python helper inventory
- `git-log-plate` — commit history since initial implementation
- `branch-snapshot-versions` — file sizes / mtimes for both branch-snapshot scripts
