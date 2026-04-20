claude-launcher.sh: writes a settings.json and prints the `claude --settings ... --add-dir ...` command string for a per-invocation launch
git.sh: git query helpers — repo detection, repo root, branch name, recent commit hashes, uncommitted files, and idempotent .gitignore appending
hook-json.sh: Claude Code hook JSON helpers — emit `{"decision":"block",...}` responses and probe required commands with install hints
invoke_command.sh: canonical command-execution wrapper that logs failures tagged with the caller's function name and suppresses stdout on success
lock.sh: mkdir-based cross-platform lock_acquire/lock_release with stale-lock auto-sweep (flock is unavailable on macOS)
permissions-seed.sh: three-state first-run / upgrade seeder for a user-editable permissions allowlist (seed, upgrade if untouched, or leave user edits alone)
platform.sh: UX nicety that spawns a macOS Terminal window attached to a tmux session when no client is attached
silencers.sh: canonical `hide_output` / `hide_errors` wrappers — use these instead of raw `>/dev/null` or `2>/dev/null`
tmux-launcher.sh: higher-level tmux composites — `tmux_ensure_session`, `tmux_ensure_keepalive_pane`, `tmux_split_worker_pane`, and Claude-readiness polling
tmux.sh: low-level tmux primitives (sessions, windows, panes, layouts, send-keys) routed through `invoke_command`, plus their test suites
