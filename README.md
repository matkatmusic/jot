# jot

Capture a mid-development idea without losing focus. Typing `/jot <idea>` writes the idea plus surrounding context (git state, open TODOs, recent conversation) to `Todos/<timestamp>_input.txt`, then a background Claude instance — persistent per project in a `tmux` window — converts it into a proper TODO file. Your current conversation keeps running uninterrupted.

## How it works

- **Phase 1 (durable write)** — The `UserPromptSubmit` hook (`jot.sh`) intercepts `/jot` prompts, writes the idea and context to `Todos/<timestamp>_input.txt` **before** any enrichment can fail, then blocks the prompt so it never reaches Claude.
- **Phase 2 (background processing)** — A per-project persistent `claude` instance runs inside a `tmux` session named `jot`, one window per project keyed by basename of `cwd`. A FIFO queue (`Todos/.jot-state/queue.txt`) feeds one job at a time via `tmux send-keys`. `SessionStart` / `Stop` hooks inside the background claude drain the queue and write `PROCESSED:` markers + `audit.log` entries.

Full architecture: see `~/.claude/plans/toasty-strolling-lollipop.md`.

## Dependencies

| Tool | Required for | Install |
|---|---|---|
| `jq` | parsing HOOK_INPUT JSON | `brew install jq` |
| `python3` | `capture-conversation.py` transcript parsing | ships with macOS / `brew install python3` |
| `tmux` | persistent background claude sessions | `brew install tmux` |
| `claude` | the background processing agent | [claude.ai/download](https://claude.ai/download) |
| `lsof` | transcript path resolution helper (historic) | ships with macOS |

## Installation

1. **Clone dotfiles** and run `install.sh` — this creates symlinks from `~/.claude/hooks/jot.sh` and `~/.claude/hooks/scripts/` into the dotfiles repo, and installs the skill into `~/.claude/skills/matkatmusic_claude_skills_jot/`.

2. **Register the UserPromptSubmit hook** in `~/.claude/settings.json`:

   ```json
   {
     "hooks": {
       "UserPromptSubmit": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "${HOME}/.claude/hooks/jot.sh"
             }
           ]
         }
       ]
     }
   }
   ```

3. **Consumer projects** (any project where you want to use `/jot`): add the state directory to `.gitignore` so jot's queue/audit artifacts do not pollute your repo:

   ```
   # jot skill state
   Todos/.jot-state/
   ```

   This is a one-time manual step — `install.sh` does not modify consumer repos.

## Verification

1. **Unit tests** (stubbed tmux + `JOT_SKIP_LAUNCH=1`):

   ```bash
   bash ~/.claude/hooks/jot-test-suite.sh all
   ```

   Expect `PASS=37 FAIL=0` (or 41 if the legacy transcript-resolver tests are still present in your version).

2. **Live smoke test**:

   ```bash
   tmux attach -t jot     # in one terminal, to watch the background claude
   ```

   In another Claude Code session, type `/jot verify the jot skill installed correctly`. Within ~90 seconds you should see:
   - `Todos/<timestamp>_input.txt` exists; `head -1` starts with `PROCESSED:`
   - `Todos/<slug>.md` exists with `## Idea`, `## Context`, `## Conversation` sections
   - `Todos/.jot-state/audit.log` last line is `<iso-ts> SUCCESS <abs-path>`

## Compatibility with `/todo-list`

jot writes TODO files with YAML frontmatter containing `id: <datetime>`, `title`, `status: open`, and `branch`. The `/todo-list` skill (`matkatmusic_claude_skills_todo-list`) reads any `Todos/*.md` file with `status: open` by generic `id` field — no filename format assumption. They work together with no additional configuration.

## Troubleshooting

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for watching the background claude, reading state files, re-triggering stuck jobs, and capturing diagnostic reports.
