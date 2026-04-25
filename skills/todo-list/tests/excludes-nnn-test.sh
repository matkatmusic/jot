#!/bin/bash
# excludes-nnn-test.sh — assert format_open_todos.py drops legacy NNN-named
# files. Failing condition: NNN file's id or title leaks into rendered output.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$THIS_DIR/../scripts/format_open_todos.py"

TMP=$(mktemp -d /tmp/todo-list-nnn-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/Todos"

cat > "$TMP/Todos/007_legacy.md" <<'EOF'
---
id: 007
title: legacy nnn entry
status: open
created: 2026-04-21T10:00:00-07:00
branch: main
---
EOF

cat > "$TMP/Todos/2026-04-25T10-00-00_new.md" <<'EOF'
---
id: 2026-04-25T10-00-00
title: timestamp entry
status: open
created: 2026-04-25T10:00:00-07:00
branch: main
---
EOF

out=$(TODOS_DIR="$TMP/Todos" python3 "$SCRIPT")

if ! printf '%s' "$out" | grep -q "ID: 2026-04-25T10-00-00"; then
  echo "FAIL: timestamp id missing from output" >&2
  echo "$out" >&2
  exit 1
fi
if printf '%s' "$out" | grep -qE "ID: 007|legacy nnn entry"; then
  echo "FAIL: legacy NNN entry leaked into output" >&2
  echo "$out" >&2
  exit 1
fi
if ! printf '%s' "$out" | grep -q "^1 open TODO$"; then
  echo "FAIL: count line wrong (should be 1, not 2)" >&2
  echo "$out" >&2
  exit 1
fi

echo "PASS: NNN-named files excluded from /todo-list output"
