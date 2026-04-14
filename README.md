# jot

Capture a mid-development idea without losing focus. Typing `/jot <idea>` writes the idea plus surrounding context (git state, open TODOs, recent conversation) to `Todos/<timestamp>_input.txt`, then a background Claude instance — one per invocation, running in its own tmux window — converts it into a proper TODO file. Your current conversation keeps running uninterrupted.

## How it works

- **Phase 1 (durable write)** — The `UserPromptSubmit` hook (`scripts/jot.sh`) intercepts `/jot` prompts, writes the idea and context to `Todos/<timestamp>_input.txt` **before** any enrichment can fail, then blocks the prompt so it never reaches the foreground Claude session.
- **Phase 2 (background processing)** — Each `/jot` spawns a dedicated background `claude` instance in its own tmux window under a shared `jot` session. The worker reads `input.txt`, follows embedded instructions, writes `Todos/<slug>.md`, overwrites `input.txt` with a `PROCESSED:` success marker, and its `Stop` hook kills the window. One worker per invocation — no shared queue, no cross-invocation state contamination.

## Requirements

Here are the required tools and versions needed to use the jot skill/hook (git stash create step 2 test)

| Tool | Install |
|---|---|
| `claude` (Claude Code CLI) | [claude.ai/download](https://claude.ai/download) |
| `jq` | `brew install jq` |
| `python3` | ships with macOS / `brew install python@3` |
| `tmux` (3.0+) | `brew install tmux` |

macOS is the primary target. `spawn_terminal_if_needed` uses `osascript` to auto-open Terminal.app and attach to the `jot` tmux session on first use; on non-Darwin hosts it no-ops and you'll need to attach manually (`tmux attach -t jot`).

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
export CLAUDE_PLUGIN_ROOT=~/.claude/plugins/cache/matkatmusic-jot/jot/1.0.0
export CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/jot

# Unit tests — stubbed tmux + JOT_SKIP_LAUNCH=1, no real workers
bash "$CLAUDE_PLUGIN_ROOT/tests/jot-test-suite.sh" all

# End-to-end — fires real /jot invocations, spawns real background claude workers
export TEST_PROJECT=~/some-claude-trusted-project
bash "$CLAUDE_PLUGIN_ROOT/tests/jot-e2e-live.sh" all
```

Expected: unit suite reports `PASS=30 FAIL=0` (one skipped when `JOT_TEST_TRANSCRIPT` is unset); e2e suite reports all 6 scenarios green (cold_start, warm_idle, transcript_fallback, cross_project, crash_recovery, diag_collector).

## Compatibility with `/todo-list`

jot writes TODO files with YAML frontmatter containing `id: <datetime>`, `title`, `status: open`, and `branch`. The `/todo-list` skill reads any `Todos/*.md` file with `status: open` by a generic `id` field — no filename format assumption. They work together with no additional configuration.

## Troubleshooting

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for watching the background claude, reading state files, re-triggering stuck jobs, and capturing diagnostic reports.
