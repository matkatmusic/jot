#!/bin/bash
# plate-worker-end.sh — SessionEnd hook. Wipes the per-invocation tmpdir.
# Args: $1=tmpdir path
set -uo pipefail
TMPDIR_INV="${1:-}"
[ -n "$TMPDIR_INV" ] && [ -d "$TMPDIR_INV" ] && rm -rf "$TMPDIR_INV"
exit 0
