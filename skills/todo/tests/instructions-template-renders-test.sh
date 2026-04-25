#!/bin/bash
# instructions-template-renders-test.sh — render todo-instructions.md via
# render_template.py with the same arg list the launcher passes, and assert
# zero unreplaced ${IDENT} tokens remain. This guards against regressions
# where someone adds a runtime-only placeholder like ${NNN} without
# escaping it (render_template.py is strict — any surviving ${IDENT} is
# a hard failure).
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/../../.." && pwd)"
TEMPLATE="$REPO/skills/todo/scripts/assets/todo-instructions.md"
RENDER="$REPO/common/scripts/jot/render_template.py"

out=$(REPO_ROOT=/tmp/fakerepo \
      TIMESTAMP=2026-04-22T00-00-00 \
      BRANCH=main \
      INPUT_ABS=/tmp/fakerepo/Todos/2026-04-22T00-00-00_input.txt \
      SCRIPTS_DIR=/tmp/fake/scripts \
      python3 "$RENDER" "$TEMPLATE" REPO_ROOT TIMESTAMP BRANCH INPUT_ABS SCRIPTS_DIR)

# Sanity: output must contain the substituted values.
for needle in "/tmp/fakerepo" "2026-04-22T00-00-00" "main" "/tmp/fake/scripts"; do
  if ! printf '%s' "$out" | grep -qF "$needle"; then
    echo "FAIL: rendered output missing '$needle'" >&2
    exit 1
  fi
done

# The template legitimately uses literal-dollar tokens elsewhere? No —
# any ${IDENT} in the output means something leaked. render_template.py
# would have exited non-zero already, but belt-and-suspenders grep here.
leftover=$(printf '%s' "$out" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*\}' | sort -u || true)
if [ -n "$leftover" ]; then
  echo "FAIL: unreplaced \${IDENT} tokens in rendered output:" >&2
  printf '%s\n' "$leftover" >&2
  exit 1
fi

echo "PASS: todo-instructions.md renders clean (all 5 render-time vars substituted, no leftover \${IDENT})"
