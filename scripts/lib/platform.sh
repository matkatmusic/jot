# platform.sh — platform-specific UX helpers for Claude Code hooks.
#
# Source this file and call:
#   spawn_terminal_if_needed <session_name> [log_file] [log_prefix]
#
# Behaviour: if no tmux client is attached to <session_name>, open a new
# macOS Terminal window attached to it via `tmux attach -t <session_name>`.
# On non-Darwin hosts (or if osascript is unavailable) writes an advisory
# line to <log_file> and returns. Never fails — this is a UX nicety.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 4).

spawn_terminal_if_needed() {
  local session="${1:?spawn_terminal_if_needed: session name required}"
  local log_file="${2:-/dev/null}"
  local log_prefix="${3:-tmux}"
  local clients
  clients=$(tmux list-clients -t "$session" 2>/dev/null || true)
  if [ -n "$clients" ]; then
    return 0
  fi
  case "${OSTYPE:-}" in
    darwin*)
      if ! command -v osascript >/dev/null 2>&1; then
        printf '%s %s: osascript unavailable; attach manually via `tmux attach -t %s`\n' \
          "$(date -Iseconds)" "$log_prefix" "$session" >> "$log_file" 2>/dev/null || true
        return 0
      fi
      osascript >/dev/null 2>&1 <<OSA &
tell application "Terminal"
  do script "tmux attach -t ${session}"
  set frontmost of window 1 to false
end tell
OSA
      ;;
    *)
      printf '%s %s: non-Darwin host; attach manually via `tmux attach -t %s`\n' \
        "$(date -Iseconds)" "$log_prefix" "$session" >> "$log_file" 2>/dev/null || true
      ;;
  esac
}
