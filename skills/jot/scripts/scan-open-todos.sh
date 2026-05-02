#!/usr/bin/env bash
# scan-open-todos.sh - delegates to common/scripts/jot/scan_open_todos_cli.py.
# See that file for the open-todos contract. File kept executable
# so existing callers (jot.sh:183, jot-test-suite.sh) work unmodified.
exec python3 \
  "$(dirname "${BASH_SOURCE[0]}")/../../../common/scripts/jot/scan_open_todos_cli.py" \
  "$@"
