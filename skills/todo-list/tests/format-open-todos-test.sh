#!/bin/bash
# format-open-todos-test.sh — smoke test for format_open_todos.py.
# Creates a temp Todos/ with mixed open/done frontmatter, runs the formatter,
# asserts only open TODOs appear in the output and the count line is correct.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$THIS_DIR/../scripts/format_open_todos.py"

TMP=$(mktemp -d /tmp/todo-list-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/Todos"
cat > "$TMP/Todos/001_open-one.md" <<'EOF'
---
id: 001
title: first open
status: open
created: 2026-04-21T10:00:00-07:00
branch: main
---
body
EOF

cat > "$TMP/Todos/002_done-two.md" <<'EOF'
---
id: 002
title: done two
status: done
created: 2026-04-21T10:05:00-07:00
branch: main
---
body
EOF

cat > "$TMP/Todos/003_open-three.md" <<'EOF'
---
id: 003
title: third open
status: open
created: 2026-04-21T10:10:00-07:00
branch: feature
---
body
EOF

out=$(TODOS_DIR="$TMP/Todos" python3 "$SCRIPT")

if ! printf '%s' "$out" | grep -q "ID: 001"; then
  echo "FAIL: missing ID 001 in output" >&2; echo "$out" >&2; exit 1
fi
if ! printf '%s' "$out" | grep -q "ID: 003"; then
  echo "FAIL: missing ID 003 in output" >&2; echo "$out" >&2; exit 1
fi
if printf '%s' "$out" | grep -q "ID: 002"; then
  echo "FAIL: done TODO 002 leaked into output" >&2; echo "$out" >&2; exit 1
fi
if ! printf '%s' "$out" | grep -q "^2 open TODOs$"; then
  echo "FAIL: count line missing or wrong" >&2; echo "$out" >&2; exit 1
fi

echo "PASS: format_open_todos filters and counts correctly"
