# tmux-send.sh — reliable text delivery to tmux panes running Claude Code.
#
# Source this file and call:
#
#   tmux_send_text <pane_id> <text>
#       Type text into the pane's input field. Does NOT submit.
#
#   tmux_send_enter <pane_id>
#       Press Enter to submit whatever is in the input field.
#
#   tmux_send_and_submit <pane_id> <text>
#       Type text then submit. Inserts a 0.5s gap between the text
#       and Enter because Claude Code's TUI drops the Enter keypress
#       when it arrives in the same send-keys call as a long string.
#
#   tmux_cancel_and_send <pane_id> <text> [label]
#       Send Ctrl-C until the agent is idle, then type + submit text.
#       Optional label is used in log output.
#
# All functions are idempotent and never fail fatally (best-effort).
# Extracted per plans/jot-generalizing-refactor.md.

tmux_send_text() {
  local pane_id="$1" text="$2"
  tmux send-keys -t "$pane_id" "$text"
}

tmux_send_enter() {
  tmux_send_text "$1" Enter
}

tmux_send_and_submit() {
  local pane_id="$1" text="$2"
  tmux_send_text "$pane_id" "$text"
  sleep 0.5
  tmux_send_enter "$pane_id"
}

tmux_cancel_and_send() {
  local pane_id="$1" text="$2" label="${3:-}"
  local attempt=0
  while [[ $attempt -lt 5 ]]; do
    tmux_send_text "$pane_id" C-c
    sleep 0.2
    local pane_tail
    pane_tail=$(tmux capture-pane -t "$pane_id" -p -S -5 2>/dev/null || true)
    if echo "$pane_tail" | grep -qF 'Ctrl-C'; then
      break
    fi
    attempt=$((attempt + 1))
  done
  if [[ $attempt -gt 0 ]] && [[ -n "$label" ]]; then
    echo "[tmux-send] Cancelled in-progress work: $label ($((attempt + 1)) Ctrl-C's)"
  fi
  tmux_send_and_submit "$pane_id" "$text"
}
