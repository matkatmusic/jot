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
cat > "$TMP/Todos/2026-04-21T10-00-00_open-one.md" <<'EOF'
---
id: 2026-04-21T10-00-00
title: first open
status: open
created: 2026-04-21T10:00:00-07:00
branch: main
---
body
EOF

cat > "$TMP/Todos/2026-04-21T10-05-00_done-two.md" <<'EOF'
---
id: 2026-04-21T10-05-00
title: done two
status: done
created: 2026-04-21T10:05:00-07:00
branch: main
---
body
EOF

cat > "$TMP/Todos/2026-04-21T10-10-00_open-three.md" <<'EOF'
---
id: 2026-04-21T10-10-00
title: third open
status: open
created: 2026-04-21T10:10:00-07:00
branch: feature
---
body
EOF

out=$(TODOS_DIR="$TMP/Todos" TZ=America/Los_Angeles python3 "$SCRIPT")

if ! printf '%s' "$out" | grep -q "Title: first open"; then
  echo "FAIL: missing 'first open' title in output" >&2; echo "$out" >&2; exit 1
fi
if ! printf '%s' "$out" | grep -q "Title: third open"; then
  echo "FAIL: missing 'third open' title in output" >&2; echo "$out" >&2; exit 1
fi
if printf '%s' "$out" | grep -q "Title: done two"; then
  echo "FAIL: done TODO 'done two' leaked into output" >&2; echo "$out" >&2; exit 1
fi
if printf '%s' "$out" | grep -qE "^ID:|^ *ID:"; then
  echo "FAIL: ID: line still present (should be removed)" >&2; echo "$out" >&2; exit 1
fi
if ! printf '%s' "$out" | grep -q "^2 open TODOs$"; then
  echo "FAIL: count line missing or wrong" >&2; echo "$out" >&2; exit 1
fi
if ! printf '%s' "$out" | grep -qF "Created: Apr 21, 2026 @ 10:00:00am local time"; then
  echo "FAIL: human-readable Created line missing" >&2; echo "$out" >&2; exit 1
fi
if printf '%s' "$out" | grep -q "Created: 2026-04-21T10:00:00-07:00"; then
  echo "FAIL: raw ISO timestamp leaked into output" >&2; echo "$out" >&2; exit 1
fi

echo "PASS: format_open_todos filters and counts correctly"
