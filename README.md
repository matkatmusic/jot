# jot + plate + todo + debate

Focus-preserving skills for Claude Code. Each one intercepts the prompt via a `UserPromptSubmit` hook, does the durable work synchronously, and (when applicable) hands enrichment or follow-up off to a background `claude` instance running in its own tmux pane — so your current conversation keeps running uninterrupted. **Background agents always run in dedicated tmux sessions** (`jot:jots`, `debate-N`, `plate-summary-N`); attaching is optional and the foreground conversation is never blocked on them.

## `/jot <idea>`

Capture a mid-development idea without losing focus. Writes the idea plus surrounding context (git state, open TODOs, recent conversation) to `Todos/<timestamp>_input.txt`, then a background Claude — one per invocation, running in its own pane under a shared `jot:jots` tmux window — converts it into a proper TODO file.

### How it works

- **Phase 1 (durable write)** — `scripts/jot-plugin-orchestrator.sh` dispatches `/jot` prompts to `skills/jot/scripts/jot-orchestrator.sh`, which writes the idea and context to `Todos/<timestamp>_input.txt` **before** any enrichment can fail, then blocks the prompt so it never reaches the foreground Claude.
- **Phase 2 (background processing)** — Each `/jot` spawns a dedicated background `claude` instance in its own tmux pane inside the shared `jot:jots` window. The worker reads `input.txt`, follows embedded instructions, writes `Todos/<slug>.md`, overwrites `input.txt` with a `PROCESSED:` success marker, and its `Stop` hook kills the pane. One worker per invocation — no shared queue, no cross-invocation contamination. Multiple `/jot` calls can run concurrently.

## `/todo <idea>`

Capture a structured TODO without losing focus. The foreground claude asks 1–3 clarifying questions if your idea is vague, then a background Claude worker in a dedicated tmux pane writes `Todos/<TIMESTAMP>_<slug>.md` with frontmatter (id, title, status, created, branch) plus sections for Idea, Context, Recent commits, Uncommitted files, Active plan, and Dependencies.

- Filenames embed the capture timestamp, mirroring `/jot`. Worker permissions are tight: read anywhere under `Todos/` and `.claude/plans/`, write only under `Todos/` — no Bash forms required.

## `/todo-list`

Read-only summary of all open TODOs in `Todos/`. Runs entirely inside the `UserPromptSubmit` hook — a python3 formatter parses YAML frontmatter from every `.md` (excluding `Todos/done/`) and emits ID / title / created / branch for each, plus a count. No tmux, no background worker.

## `/todo-clean`

Interactive foreground scan of open TODOs against `git log --since=<created>`. For each candidate whose commit history suggests resolution, asks via `AskUserQuestion` before moving it to `Todos/done/` and stamping `status: done` + `resolved: <iso>` in the frontmatter.

## `/debate <topic>`

Multi-agent debate (Claude + Gemini + Codex) in a four-pane tmux window. Agents independently analyze the topic, cross-critique each other, then synthesize. The launcher maximizes the Terminal.app window on first launch so the layout fits; reattach paths are unaffected. Model selection per agent lives in `skills/debate/scripts/assets/models.json` — index 0 is the launch-time default, subsequent entries are capacity-rotation targets used when an agent's model returns 429 / "at capacity".

## `/plate`

Stack-of-plates WIP tracker for when you notice uncommitted work that belongs to a different task. Snapshot it on a per-branch plate ref, switch contexts freely, then replay or jump back to it later. Plates are real git commits on `<branch>-plate` refs (not stash refs), so they survive `git stash drop`, `git clean -fd`, branch switches, and even `git push` if you publish the plate ref. Cross-machine handoff works via commit trailers — a teammate cloning the repo can read what's on a parked plate without your local machine being reachable.

### Commands

| Command | Effect |
|---|---|
| `/plate` | Snapshot the current working tree as a commit on `<branch>-plate` (creates the ref if missing). Async background agent then writes a 5-section recovery summary to the tip's `convo-summary:` trailer ~30s later. |
| `/plate --done` | Cherry-pick the plate stack bottom-up onto the current branch as sequential commits. Aborts cleanly on conflict, restoring HEAD/WT. |
| `/plate --drop` | Pop the top plate, save it under `<repo>/.plate/trash/<branch>/<ts>_dropped_<sha>/{info.json, plate_001.patch}`. |
| `/plate --trash` | Delete the entire `<branch>-plate` ref; save every plate commit as numbered patches under `<repo>/.plate/trash/<branch>/<ts>_trashed_<sha>/`. |
| `/plate --recycle` | Restore the most recent dropped/trashed session for the current branch. Re-parents at `info.json::parent_sha_at_save` (NOT current HEAD) so restoring a stale plate doesn't accidentally rebase it onto unrelated work. |
| `/plate --recycle --list` | Read-only enumeration of every dropped/trashed session, grouped by branch, newest first. |
| `/plate --recycle <session-dir-name>` | Restore a specific session by directory name. |
| `/plate --next` | Numbered list of every parked plate across all branches, sorted by tip-commit time. |
| `/plate --next <#>` | Jump to plate #N: snapshots current WIP first (so nothing is lost), checks out the target plate's parent branch, restores the plate's tree as unstaged WIP, and emits a `claude --resume` command pointing at the originating conversation. |
| `/plate --show` | (Currently returns `"TODO"` — design deferred.) |

Plates also fire **automatically on `SessionEnd`**, so any uncommitted WIP at the moment a Claude conversation closes lands on `<branch>-plate` without you having to remember to run `/plate`. Re-entrant fires are blocked by a `PLATE_SKIP_AUTO=1` belt-and-suspenders env var.

### How it works

- **Hook entry**: `UserPromptSubmit` (or `SessionEnd` for the auto-fire) routes `/plate` through `scripts/jot-plugin-orchestrator.sh` → `skills/plate/scripts/plate.sh::plate_main`, which dispatches to `common/scripts/plate/cli.py` for every variant. The CLI returns the user-facing message via `emit_block` so the literal `/plate` prompt never reaches the foreground model.
- **Branch-model storage**: each plate is a `git commit-tree` against `<branch>-plate` with trailers `parent-branch`, `convo-id`, `convo-name`, and (added asynchronously) `convo-summary`. No `.plate/instances/` JSON, no stash refs.
- **Multi-agent same-branch attribution**: when two parallel Claude sessions push to the same `<branch>-plate`, each commit captures only the files that agent edited. Detection is via the previous tip's `convo-id` trailer; isolation is via parsing each agent's transcript for `Edit`/`Write`/`MultiEdit`/`NotebookEdit` tool-use entries plus `Bash` `rm`/`git rm` parses since the previous plate.
- **Async summary agent**: after a successful push, `common/scripts/plate/spawn_summary_agent.py` fires a background `claude` in a fresh tmux pane (`plate-summary-<N>`, counter-suffixed to avoid cross-project collisions). The agent reads the plate branch + transcript, writes a 5-section summary (`what:`/`why:`/`how:`/`open questions:`/`next steps:` per `skills/plate/summary-template.md`) to a tempfile, and self-exits when a watcher hook detects the file. A `SessionEnd` hook on that pane then runs `cli.py set-plate-summary` which uses `git rebase -i` reword (in a detached worktree) to add the trailer to the new tip and strip stale `convo-summary` trailers from earlier commits. The pane is auto-attached in a Terminal.app window via `spawn_terminal_if_needed` so you can watch it work.
- **Sandboxed permissions**: the spawned summary agent gets a narrow read-only `permissions.allow` block in its per-invocation `settings.json` — Read on the prompt/template/transcript/output paths plus 11 read-only git verbs (in both bare-`git` and `rtk git` form). It cannot mutate the repo even if the prompt tries to.
- **Logs**: per-repo at `<repo>/.plate/plate-log.txt`. Both `plate.sh` and the summary-agent's hooks log to the same file via the exported `PLATE_LOG_FILE` env var.

## Architecture

- `scripts/jot-plugin-orchestrator.sh` — single dispatcher wired into `hooks/hooks.json:UserPromptSubmit`; routes `/jot`, `/plate`, `/debate`, `/todo`, `/todo-list` to their per-skill orchestrators. `/todo-clean` falls through and is resolved by Claude's skill dispatcher.
- `skills/jot/scripts/`, `skills/plate/scripts/`, `skills/todo/scripts/`, `skills/todo-list/scripts/` — per-skill orchestrators, lifecycle hooks, assets, prompts. `skills/todo-clean/` is SKILL.md-only (no hook).
- `common/scripts/` — shared helpers (`tmux.sh`, `invoke_command.sh`, `silencers.sh`, `git.sh`, `lock.sh`, `platform.sh`, `hook-json.sh`, `claude-launcher.sh`, `permissions-seed.sh`) + namespaced python helpers (`common/scripts/jot/`, `common/scripts/plate/`)
- Lifecycle-safe hook scripts are copied into a per-invocation tmpdir at launch, so `claude plugin update` can't yank them mid-run

## Requirements

Required tools for `/jot`, `/plate`, `/todo`, and `/debate`:

| Tool | Used by | Install |
|---|---|---|
| `claude` (Claude Code CLI) | all skills (foreground + spawned background agents) | [claude.ai/download](https://claude.ai/download) |
| `git` (2.30+) | `/plate` (entire branch model + rebase-reword trailer rewrite); also `/jot` and `/todo` for context capture | `brew install git` (macOS ships an older one) |
| `jq` | hook JSON shaping (`SessionEnd` injects `prompt:"/plate"` via `jq`); orchestrator dispatch parsing | `brew install jq` |
| `python3` (3.10+) | `cli.py`, `spawn_summary_agent.py`, transcript parsers, hook helpers | ships with macOS / `brew install python@3` |
| `tmux` (3.0+) | every background agent pane (`jot:jots`, `debate-N`, `plate-summary-N`) | `brew install tmux` |
| `osascript` (macOS-only) | `spawn_terminal_if_needed` auto-opens a Terminal.app window attaching to the agent's tmux session | ships with macOS |

**Tmux session conventions** — each skill uses a distinct, predictable session name so you can attach without guessing:

| Skill | Session | Layout |
|---|---|---|
| `/jot` | `jot:jots` | one shared session, one pane per `/jot` invocation, lifecycle-tied (`Stop` hook kills the pane on completion) |
| `/debate` | `debate-N` (counter-suffixed) | four panes — Claude / Gemini / Codex / synthesis — one session per `/debate` invocation |
| `/plate` summary agent | `plate-summary-N` (counter-suffixed) | one pane per `/plate` push, self-exits when summary written |

macOS is the primary target. On non-Darwin hosts `spawn_terminal_if_needed` no-ops and you'll need to attach manually (`tmux attach -t <session>` from the table above).

## Installation

### Option A — Claude Code marketplace (recommended)

```bash
claude plugin marketplace add https://github.com/matkatmusic/jot.git
claude plugin install jot@matkatmusic-jot
```

The `claude plugin install` command creates a per-install data directory at `~/.claude/plugins/data/jot/` and on the first `/jot` invocation, `jot.sh` seeds `permissions.local.json` there from the bundled portable default.

### Option B — Declarative in `~/.claude/settings.json`

Add the marketplace to `extraKnownMarketplaces` and enable the plugin:

```json
{
  "enabledPlugins": {
    "jot@matkatmusic-jot": true
  },
  "extraKnownMarketplaces": {
    "matkatmusic-jot": {
      "source": {
        "source": "git",
        "url": "https://github.com/matkatmusic/jot.git"
      }
    }
  }
}
```

Then run `claude plugin install jot@matkatmusic-jot` once to pull the plugin into the local cache.

### Consumer-project setup

In any project where you want to use `/jot`, add the per-project state directory to `.gitignore` so jot's queue/audit artifacts don't pollute your repo:

```
# jot plugin state
Todos/.jot-state/
```

This is a one-time manual step per project. The `Todos/` directory itself is intentionally tracked — the TODO markdown files are the whole point.

### Customizing permissions

The background worker's permission allowlist lives at `~/.claude/plugins/data/jot/permissions.local.json` and is seeded from the bundled default at `assets/permissions.default.json`. Edit the installed copy to add site-specific grants (e.g. `Bash(git:*)` if your jot workflow needs git access). Changes take effect on the next `/jot`.

Plugin upgrades detect edits via sha256: if the installed file matches the previously-shipped default it gets refreshed, if it was user-edited it's left alone and a one-line hint is logged.

### Updating

```bash
claude plugin update jot@matkatmusic-jot
```

Restart Claude Code to apply. Your customized `permissions.local.json` is preserved (see [Customizing permissions](#customizing-permissions)).

### Uninstalling

```bash
claude plugin uninstall jot@matkatmusic-jot
```

The per-install data directory at `~/.claude/plugins/data/jot/` is left intact so a reinstall keeps your custom permissions. Delete it manually for a clean slate.

## Verification

After install, fire a `/jot` in any Claude Code session inside a trusted project directory:

```
/jot verify the jot plugin installed correctly
```

Within ~30 seconds:

- `Todos/<timestamp>_input.txt` exists; `head -1` starts with `PROCESSED:`
- `Todos/<timestamp>_<slug>.md` exists with `## Idea`, `## Context`, `## Conversation` sections
- `Todos/.jot-state/audit.log` last line is `<iso-ts> SUCCESS <abs-path>`

You can watch the background worker live in another terminal:

```bash
tmux attach -t jot
```

### Test suites

Both test suites ship with the plugin and run against the installed copy. Set `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` first so `jot.sh` doesn't trip its plugin-env assertions:

```bash
export CLAUDE_PLUGIN_ROOT=~/.claude/plugins/cache/matkatmusic-jot/jot/1.1.5
export CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/jot

# Unit tests — stubbed tmux + JOT_SKIP_LAUNCH=1, no real workers
bash "$CLAUDE_PLUGIN_ROOT/skills/jot/tests/jot-test-suite.sh" all

# End-to-end — fires real /jot invocations, spawns real background claude workers
export TEST_PROJECT=~/some-claude-trusted-project
bash "$CLAUDE_PLUGIN_ROOT/skills/jot/tests/jot-e2e-live.sh" all
```

Expected: unit suite reports `PASS=30 FAIL=0` (one skipped when `JOT_TEST_TRANSCRIPT` is unset); e2e suite reports all 6 scenarios green (cold_start, warm_idle, transcript_fallback, cross_project, crash_recovery, diag_collector).

## Compatibility with `/todo-list`

jot writes TODO files with YAML frontmatter containing `id: <datetime>`, `title`, `status: open`, and `branch`. The `/todo-list` skill reads any `Todos/*.md` file with `status: open` by a generic `id` field — no filename format assumption. They work together with no additional configuration.

## Troubleshooting

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for watching the background claude, reading state files, re-triggering stuck jobs, and capturing diagnostic reports.
