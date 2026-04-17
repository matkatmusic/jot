# tmux-launcher.sh — reusable tmux session/window/pane primitives.
#
# This file is meant to be `source`d. All state is passed via explicit
# arguments; nothing reads hidden globals. Functions return nonzero on
# failure rather than `exit` so callers can recover.
#
# Requires tmux 2.9+ (pane-border-status, pane-border-format, select-pane -T).
# The version is checked at source time; sourcing fails if tmux is too old.
#
# Exported functions:
#   tmux_require_version <version>
#   tmux_capture_pane <pane_id> [lines=10]
#   tmux_ensure_session <session> <window> <cwd> <keepalive_cmd> <keepalive_title>
#   tmux_ensure_keepalive_pane <target> <cwd> <keepalive_cmd> <title>
#   tmux_split_worker_pane <target> <cwd> <cmd>
#   tmux_set_pane_title <pane_id> <title>
#   tmux_retile <target>
#   tmux_kill_session <session>

# ── Version gate ─────────────────────────────────────────────────────────

tmux_require_version() {
  local required="$1"
  local installed
  installed=$(tmux -V 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
  if [ -z "$installed" ]; then
    echo "[tmux-launcher] tmux not found" >&2
    return 1
  fi
  if printf '%s\n%s\n' "$required" "$installed" | sort -V | head -1 | grep -qx "$required"; then
    return 0
  fi
  echo "[tmux-launcher] tmux $required+ required (found $installed)" >&2
  return 1
}

# Callers should invoke `tmux_require_version "2.9"` after confirming
# tmux is installed (e.g. after check_requirements in hook-json.sh).

# ── Functions ────────────────────────────────────────────────────────────

tmux_capture_pane() {
  local pane_id="$1" lines="${2:-10}"
  if ! tmux list-panes -F '#{pane_id}' 2>/dev/null | grep -qx "$pane_id"; then
    echo "[tmux-launcher] tmux_capture_pane: pane '$pane_id' does not exist" >&2
    return 1
  fi
  tmux capture-pane -t "$pane_id" -p -S "-$lines"
}

tmux_ensure_session() {
  local session="$1" window="$2" cwd="$3" keepalive_cmd="$4" keepalive_title="$5"
  if ! tmux has-session -t "$session" 2>/dev/null; then
    tmux new-session -d -s "$session" -n "$window" -c "$cwd" "$keepalive_cmd"
    tmux set-option -t "$session" remain-on-exit off             >/dev/null 2>&1 || true
    tmux set-option -t "$session" mouse on                       >/dev/null 2>&1 || true
    tmux set-option -t "$session" pane-border-status top         >/dev/null 2>&1 || true
    tmux set-option -t "$session" pane-border-format ' #{pane_title} ' >/dev/null 2>&1 || true
    tmux select-pane -t "${session}:${window}.0" -T "$keepalive_title" >/dev/null 2>&1 || true
    return 0
  fi
  if ! tmux list-windows -t "$session" -F '#{window_name}' 2>/dev/null | grep -qx "$window"; then
    tmux new-window -t "$session" -n "$window" -c "$cwd" "$keepalive_cmd"
    tmux select-pane -t "${session}:${window}.0" -T "$keepalive_title" >/dev/null 2>&1 || true
    return 0
  fi
  tmux_ensure_keepalive_pane "${session}:${window}" "$cwd" "$keepalive_cmd" "$keepalive_title"
}

tmux_ensure_keepalive_pane() {
  local target="$1" cwd="$2" keepalive_cmd="$3" title="$4"
  if tmux list-panes -t "$target" -F '#{pane_title}' 2>/dev/null | grep -qx "$title"; then
    return 0
  fi
  local ka_id
  ka_id=$(tmux split-window -t "$target" -c "$cwd" -P -F '#{pane_id}' "$keepalive_cmd")
  [ -n "$ka_id" ] && tmux select-pane -t "$ka_id" -T "$title" >/dev/null 2>&1 || true
  tmux select-layout -t "$target" tiled >/dev/null 2>&1 || true
}

tmux_split_worker_pane() {
  local target="$1" cwd="$2" cmd="$3"
  local pane_id
  pane_id=$(tmux split-window -t "$target" -c "$cwd" -P -F '#{pane_id}' "$cmd")
  if [ -z "$pane_id" ]; then
    return 1
  fi
  printf '%s\n' "$pane_id"
}

tmux_set_pane_title() {
  tmux select-pane -t "$1" -T "$2" >/dev/null 2>&1 || true
}

tmux_retile() {
  tmux select-layout -t "$1" tiled >/dev/null 2>&1 || true
}

tmux_kill_session() {
  tmux kill-session -t "$1" 2>/dev/null || true
}
