# jot — Troubleshooting

## Watching the background claude

```bash
tmux attach -t jot       # attach to the background session
Ctrl-b d                 # detach without killing
```

One window per project, named by the basename of the project directory. If you have fired `/jot` from three different projects, you will see three windows in `tmux list-windows -t jot`.

## Where state lives

| Path | Purpose |
|---|---|
| `~/.jot-log.txt` | Session-level log: every `/jot` invocation, plus `HOOK_INPUT` dumps. Rotated manually. |
| `~/.jot-state/` | Per-user cache directory. |
| `<project>/Todos/<timestamp>_input.txt` | Durable idea + context file written by the hook. `head -1` contains `PROCESSED:<path>` after the background claude finishes. |
| `<project>/Todos/<slug>.md` | The final TODO file the background claude produced. |
| `<project>/Todos/.jot-state/queue.txt` | FIFO queue of pending `input.txt` paths. |
| `<project>/Todos/.jot-state/active_job.txt` | Currently-being-processed job path (empty when idle). |
| `<project>/Todos/.jot-state/queue.lock` | `mkdir`-based lock directory during queue mutations. |
| `<project>/Todos/.jot-state/audit.log` | One `<iso-ts> SUCCESS|FAIL <abs-path>` line per completed job. Auto-rotates at 1000 lines. |

## Reading `audit.log`

```bash
tail -20 <project>/Todos/.jot-state/audit.log
```

Each line: `<iso-8601> SUCCESS <abs-path>` or `<iso-8601> FAIL <abs-path>`. FAIL means the background claude either did not write the `PROCESSED:` marker to the first line of `input.txt`, or the claude process was killed before finishing.

## Finding PENDING `*_input.txt`

```bash
find <project>/Todos -maxdepth 1 -name '*_input.txt' -exec sh -c 'head -1 "$1" | grep -q "^PROCESSED:" || echo "$1"' _ {} \;
```

Any file printed by that command has not been processed. Re-trigger by either:

- Sending a new `/jot` — this enqueues a new job; the old pending file will not be automatically drained unless it is in `queue.txt`.
- **Manual re-send**:

   ```bash
   tmux send-keys -t jot:<project-basename> \
     "Read /absolute/path/to/<ts>_input.txt and follow the instructions at the top of that file" Enter
   ```

## Running `jot-diag-collect.sh`

Captures a post-mortem report: tmux pane scrollback, audit log tail, `queue.txt` + `active_job.txt` state, the triggering `input.txt`, git status, `~/.jot-state/` cache contents, and `JOT_*` / `CLAUDE_*` environment variables. Include the output file in any bug report.

```bash
cd <project>                                           # REQUIRED — collector reads $PWD/Todos/.jot-state/
bash ~/.claude/hooks/jot-diag-collect.sh /tmp/jot-diag.log
```

Run within ~30 seconds of a `/jot` failure — older pane scrollback may have rolled off.

## Common issues

- **`requirements check failed` in `~/.jot-log.txt`** — one of `jq`, `python3`, `tmux`, `claude`, or `lsof` is missing from `PATH`. The hook prints exact install hints. Install the missing tool and re-fire.
- **tmux session missing** — the next `/jot` recreates it automatically via `ensure_jot_session_and_window` in `jot.sh`. No manual recovery needed.
- **Background claude wedged (spinner forever)** — `tmux kill-pane -t jot:<project>`. On the next `/jot`, `SessionStart` detects the stale `active_job.txt` and prepends that job to the queue front so it drains before any new work.
- **`## Recent Conversation` shows `(no transcript available)`** — the `transcript_path` in the HOOK_INPUT payload either did not exist at write time or `capture-conversation.py` could not parse any user turns. Check `~/.jot-log.txt` for the raw `HOOK_INPUT` dump to see exactly what path the hook received.
- **Terminal.app keeps popping up on every `/jot`** — the `jot` tmux session has no attached clients. Leave one terminal attached (`tmux attach -t jot` + detach with `Ctrl-b d` keeps the client) and subsequent jots will reuse it via `spawn_terminal_if_needed`.
