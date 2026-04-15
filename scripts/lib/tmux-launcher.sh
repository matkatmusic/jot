# tmux-launcher.sh — reusable tmux session/window/pane primitives.
#
# This file is meant to be `source`d. All state is passed via explicit
# arguments; nothing reads hidden globals. Functions log their failures
# via `return nonzero` rather than `exit` so callers can recover.
#
# Exported functions:
#   tmux_ensure_session <session> <window> <cwd> <keepalive_cmd> <keepalive_title>
#       Idempotent session+window+keepalive-pane bootstrap. On first
#       creation also sets remain-on-exit off, mouse on, and a pane
#       border format. Safe to call repeatedly.
#
#   tmux_ensure_keepalive_pane <target> <cwd> <keepalive_cmd> <title>
#       Probe the given window (session:window) for a pane titled
#       <title>. If absent, split a new pane, title it, and retile.
#       Probes by title (not index) because worker panes outlive the
#       keepalive pane and shift indices.
#
#   tmux_split_worker_pane <target> <cwd> <cmd>
#       Split a new pane running <cmd>. Prints the new pane_id on
#       stdout. Returns nonzero if tmux fails.
#
#   tmux_set_pane_title <pane_id> <title>
#   tmux_retile <target>
#       Cosmetic wrappers. Silently ignore tmux errors.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 6).

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
