# platform.sh — platform-specific UX helpers for Claude Code hooks.
#
# Source this file and call:
#   spawn_terminal_if_needed <session_name> [log_file] [log_prefix] [maximize]
#
# Behaviour: if no tmux client is attached to <session_name>, open a new
# macOS Terminal window attached to it via `tmux attach -t <session_name>`.
# When [maximize] = "yes", resize the new window's bounds to fill the
# desktop (only on first spawn — the early-return for already-attached
# clients still skips the entire osascript block).
# On non-Darwin hosts (or if osascript is unavailable) writes an advisory
# line to <log_file> and returns. Never fails — this is a UX nicety.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 4).

source "$(dirname "${BASH_SOURCE[0]}")/silencers.sh"
source "$(dirname "${BASH_SOURCE[0]}")/tmux.sh"

spawn_terminal_if_needed() {
  local session="${1:?spawn_terminal_if_needed: session name required}"
  local log_file="${2:-/dev/null}"
  local log_prefix="${3:-tmux}"
  local maximize="${4:-}"
  local clients
  # Probe for attached clients; silence invoke_command's failure log because
  # a missing session is the trigger-condition for spawning, not an error.
  clients=$(hide_errors tmux_list_clients "$session")
  if [ -n "$clients" ]; then
    return 0
  fi
  # Optional window-bounds adjustment after `do script` opens the new
  # Terminal window. Three modes:
  #   "yes"     — maximize to desktop bounds. Used by /debate (4-pane
  #               layout needs the room).
  #   "compact" — clamp to a small centred rect (1000×700). Used by
  #               single-pane spawners (e.g. /plate) so they don't
  #               inherit a maximized geometry left behind by /debate
  #               or by the user manually maximizing a previous window.
  #   ""        — no adjustment (legacy default).
  # Finder's "bounds of window of desktop" excludes the menu bar and
  # tracks the active display, so multi-monitor setups work for both
  # "yes" and "compact" modes.
  local maximize_block=""
  if [ "$maximize" = "yes" ]; then
    maximize_block='
tell application "Finder"
  set screenBounds to bounds of window of desktop
end tell
tell application "Terminal"
  set bounds of front window to screenBounds
end tell'
  elif [ "$maximize" = "compact" ]; then
    maximize_block='
tell application "Finder"
  set screenBounds to bounds of window of desktop
end tell
set sx to item 1 of screenBounds
set sy to item 2 of screenBounds
set ex to item 3 of screenBounds
set ey to item 4 of screenBounds
set winW to 1000
set winH to 700
set winX to sx + ((ex - sx - winW) div 2)
set winY to sy + ((ey - sy - winH) div 2)
tell application "Terminal"
  set bounds of front window to {winX, winY, winX + winW, winY + winH}
end tell'
  fi
  case "${OSTYPE:-}" in
    darwin*)
      if ! hide_output hide_errors command -v osascript; then
        printf '%s %s: osascript unavailable; attach manually via `tmux attach -t %s`\n' \
          "$(date -Iseconds)" "$log_prefix" "$session" >> "$log_file" 2>/dev/null || true
        return 0
      fi
      hide_output hide_errors osascript <<OSA &
if application "Terminal" is running then
  tell application "Terminal" to do script "tmux attach -t ${session}"
else
  tell application "Terminal"
    do script "tmux attach -t ${session}" in window 1
  end tell
end if${maximize_block}
OSA
      ;;
    *)
      printf '%s %s: non-Darwin host; attach manually via `tmux attach -t %s`\n' \
        "$(date -Iseconds)" "$log_prefix" "$session" >> "$log_file" 2>/dev/null || true
      ;;
  esac
}
