#!/bin/bash
# todo-session-end.sh — SessionEnd hook for per-invocation claude panes.
# Wipes the per-invocation /tmp/todo.XXXXXX directory that held this
# claude's settings.json and copied-in helper scripts.
#
# Args: $1 = absolute path to the temp dir
set -uo pipefail

TMPDIR_INV="${1:-}"

case "$TMPDIR_INV" in
  /tmp/todo.*|/private/tmp/todo.*) ;;
  *)
    echo "[todo-session-end] refusing to rm unexpected path: $TMPDIR_INV" >&2
    exit 0
    ;;
esac

rm -rf "$TMPDIR_INV"
exit 0
