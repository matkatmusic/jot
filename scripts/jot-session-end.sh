#!/bin/bash
# jot-session-end.sh — SessionEnd hook for per-project claude instances.
# Wipes the per-invocation /tmp/jot.XXXXXX directory that held the
# settings.json for this claude instance.
#
# Args:
#   $1 = absolute path to the temp dir (must match /tmp/jot.* or /private/tmp/jot.*)
set -uo pipefail

TMPDIR_INV="${1:-}"

# Safety guard: refuse to rm anything not matching the expected pattern.
# Without this a misconfigured hook could wipe an arbitrary path.
case "$TMPDIR_INV" in
  /tmp/jot.*|/private/tmp/jot.*) ;;
  *)
    echo "[jot-session-end] refusing to rm unexpected path: $TMPDIR_INV" >&2
    exit 0
    ;;
esac

rm -rf "$TMPDIR_INV"
exit 0
