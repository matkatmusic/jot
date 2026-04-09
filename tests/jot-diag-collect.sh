#!/bin/bash
# jot-diag-collect.sh — post-mortem collector for a /jot run.
#
# Run this IN THE PROJECT DIRECTORY where you invoked /jot, ideally
# within ~30 seconds of firing /jot so the tmux pane still shows claude's
# current output. It gathers every piece of state needed to debug a Phase 2
# run and writes it to a single report file.
#
# Usage:
#   bash ~/.claude/hooks/jot-diag-collect.sh            # writes /tmp/jot-diag-YYYYMMDD-HHMMSS.log
#   bash ~/.claude/hooks/jot-diag-collect.sh out.log    # custom output path
#
# Output is one large text report. Paste the path (or cat the file) to
# share results.

set -uo pipefail

OUT="${1:-/tmp/jot-diag-$(date +%Y%m%d-%H%M%S).log}"
CWD=$(pwd)
PROJECT=$(basename "$CWD")
TMUX_TARGET="jot:$PROJECT"
STATE_DIR="$CWD/Todos/.jot-state"

# ── helpers ──────────────────────────────────────────────────────────────
section() { printf '\n═══════════════════════════════════════════════════════════\n%s\n═══════════════════════════════════════════════════════════\n' "$1"; }
indent()  { sed 's/^/  /'; }
kv()      { printf '%-28s %s\n' "$1" "$2"; }

{
  printf 'jot-diag-collect report\n'
  printf 'generated: %s\n' "$(date -Iseconds)"
  printf 'cwd:       %s\n' "$CWD"
  printf 'project:   %s\n' "$PROJECT"
  printf 'tmux target (expected): %s\n' "$TMUX_TARGET"

  # ── 1. Latest input.txt ───────────────────────────────────────────────
  section "1. Latest Todos/*_input.txt"
  LATEST=$(ls -t "$CWD"/Todos/*_input.txt 2>/dev/null | head -1 || true)
  if [ -z "$LATEST" ]; then
    echo "(no input.txt found in $CWD/Todos/)"
  else
    kv "path" "$LATEST"
    kv "size (bytes)" "$(wc -c < "$LATEST" | tr -d ' ')"
    kv "mtime" "$(stat -f '%Sm' "$LATEST" 2>/dev/null || stat -c '%y' "$LATEST")"
    FIRST_LINE=$(head -1 "$LATEST")
    kv "first line" "$FIRST_LINE"
    if [[ "$FIRST_LINE" == PROCESSED:* ]]; then
      kv "status" "✓ PROCESSED (success)"
    elif [[ "$FIRST_LINE" == "# Jot Task" ]]; then
      kv "status" "⏳ PENDING (claude hasn't finished OR failed)"
    else
      kv "status" "? unknown first-line format"
    fi
    echo
    echo "--- full content ---"
    cat "$LATEST"
  fi

  # ── 2. State dir contents ─────────────────────────────────────────────
  section "2. State dir ($STATE_DIR)"
  if [ ! -d "$STATE_DIR" ]; then
    echo "(state dir does not exist — Phase 2 may not have run)"
  else
    echo "--- ls -la ---"
    ls -la "$STATE_DIR" 2>&1 | indent
    echo
    echo "--- queue.txt ---"
    if [ -f "$STATE_DIR/queue.txt" ]; then
      if [ -s "$STATE_DIR/queue.txt" ]; then
        cat "$STATE_DIR/queue.txt" | indent
      else
        echo "  (empty — no jobs pending)"
      fi
    else
      echo "  (missing)"
    fi
    echo
    echo "--- active_job.txt ---"
    if [ -f "$STATE_DIR/active_job.txt" ]; then
      if [ -s "$STATE_DIR/active_job.txt" ]; then
        cat "$STATE_DIR/active_job.txt" | indent
        echo "  (claude is currently processing this file)"
      else
        echo "  (empty — claude is idle)"
      fi
    else
      echo "  (missing)"
    fi
    echo
    echo "--- audit.log (last 30 entries) ---"
    if [ -f "$STATE_DIR/audit.log" ]; then
      tail -30 "$STATE_DIR/audit.log" | indent
    else
      echo "  (missing)"
    fi
    echo
    echo "--- queue.lock ---"
    if [ -e "$STATE_DIR/queue.lock" ]; then
      echo "  LOCK IS HELD (type: $(test -d "$STATE_DIR/queue.lock" && echo "dir (mkdir lock)" || echo "file"))"
      echo "  If no /jot is currently running, this is a stale lock and should be removed:"
      echo "    rm -rf '$STATE_DIR/queue.lock'"
    else
      echo "  (free — no lock held)"
    fi
  fi

  # ── 3. tmux session state ─────────────────────────────────────────────
  section "3. tmux session 'jot'"
  if ! tmux has-session -t jot 2>/dev/null; then
    echo "(no 'jot' tmux session exists)"
  else
    echo "--- tmux list-sessions | grep jot ---"
    tmux list-sessions 2>&1 | grep '^jot' | indent

    echo
    echo "--- tmux list-windows -t jot ---"
    tmux list-windows -t jot 2>&1 | indent

    echo
    echo "--- tmux list-panes -t $TMUX_TARGET ---"
    tmux list-panes -t "$TMUX_TARGET" -F '#{pane_id} pid=#{pane_pid} dead=#{pane_dead} deadstatus=#{pane_dead_status} cmd=#{pane_current_command}' 2>&1 | indent

    echo
    echo "--- pane start command ---"
    tmux display-message -t "$TMUX_TARGET" -p 'start: #{pane_start_command}' 2>&1 | indent

    echo
    echo "--- tmux attached clients ---"
    CLIENTS=$(tmux list-clients -t jot 2>/dev/null)
    if [ -z "$CLIENTS" ]; then
      echo "  (no clients attached)"
    else
      echo "$CLIENTS" | indent
    fi

    echo
    echo "--- pane content (last 80 lines of scrollback) ---"
    tmux capture-pane -t "$TMUX_TARGET" -p -S -80 2>&1 | indent
  fi

  # ── 4. Per-invocation /tmp/jot.* dirs ─────────────────────────────────
  section "4. /tmp/jot.* per-invocation dirs"
  FOUND_TMP=0
  for d in /tmp/jot.*; do
    [ -d "$d" ] || continue
    FOUND_TMP=1
    echo "--- $d ---"
    ls -la "$d" 2>&1 | indent
    if [ -f "$d/settings.json" ]; then
      echo "  --- settings.json ---"
      cat "$d/settings.json" | indent
    fi
  done
  [ "$FOUND_TMP" = "0" ] && echo "(none — either not started or SessionEnd cleaned up)"

  # ── 5. Plugin jot-log.txt (global redacted log) ──────────────────────
  # Log location moved from ~/.jot-log.txt to ${CLAUDE_PLUGIN_DATA}/jot-log.txt
  # after the plugin migration. JOT_LOG_FILE still overrides both.
  _log="${JOT_LOG_FILE:-${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/jot}/jot-log.txt}"
  section "5. $_log (last 20 entries)"
  if [ -f "$_log" ]; then
    tail -20 "$_log" | indent
  else
    echo "(missing)"
  fi

  # ── 6. Recent Todos/ directory ────────────────────────────────────────
  section "6. Todos/ directory listing (newest first)"
  if [ -d "$CWD/Todos" ]; then
    ls -lat "$CWD/Todos/" 2>&1 | head -20 | indent
  else
    echo "(no Todos/ dir in $CWD)"
  fi

  # ── 7. Installed plugin script sanity check ──────────────────────────
  # Paths moved from ~/.claude/hooks/... to ${CLAUDE_PLUGIN_ROOT}/scripts/...
  # after the plugin migration.
  _root="${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/installed/jot}"
  section "7. Installed plugin script paths"
  for p in \
    "$_root/scripts/jot.sh" \
    "$_root/scripts" \
    "$_root/scripts/jot-state-lib.sh" \
    "$_root/scripts/jot-session-start.sh" \
    "$_root/scripts/jot-stop.sh" \
    "$_root/scripts/jot-session-end.sh"
  do
    if [ -e "$p" ] || [ -L "$p" ]; then
      if [ -L "$p" ]; then
        kv "$p" "→ $(readlink "$p")"
      else
        kv "$p" "present ($(stat -f '%z' "$p" 2>/dev/null || stat -c '%s' "$p") bytes)"
      fi
    else
      kv "$p" "MISSING"
    fi
  done

  # ── 8. Dependency check ───────────────────────────────────────────────
  section "8. Dependency check"
  for cmd in jq python3 tmux claude osascript; do
    if command -v "$cmd" >/dev/null 2>&1; then
      kv "$cmd" "$(command -v "$cmd")"
    else
      kv "$cmd" "NOT FOUND"
    fi
  done

  section "END OF REPORT"
} > "$OUT" 2>&1

echo "jot-diag report: $OUT"
echo "size: $(wc -c < "$OUT") bytes, $(wc -l < "$OUT") lines"
echo
echo "share this with Claude via:"
echo "  cat $OUT"
echo "or just paste the path."
