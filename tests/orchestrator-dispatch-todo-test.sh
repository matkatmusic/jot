#!/bin/bash
# orchestrator-dispatch-todo-test.sh — verify orchestrator.sh routes prompts
# to the correct sub-orchestrator, and in particular that /todo does NOT
# match /todo-clean (which should fall through so claude's skill dispatcher
# can resolve it to the todo-clean SKILL.md).
#
# Failing condition: wrong dispatcher gets invoked for a given prompt.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$THIS_DIR/.." && pwd)"
ORCH="$REPO/scripts/orchestrator.sh"

TMP=$(mktemp -d /tmp/orch-dispatch-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

# Override PLUGIN_ROOT so our case branches invoke stub scripts, not the
# real sub-orchestrators. We need a fake tree that matches the paths used
# by orchestrator.sh.
FAKE_ROOT="$TMP/fake-plugin"
mkdir -p "$FAKE_ROOT/common/scripts" \
         "$FAKE_ROOT/skills/jot/scripts" \
         "$FAKE_ROOT/skills/plate/scripts" \
         "$FAKE_ROOT/skills/debate/scripts" \
         "$FAKE_ROOT/skills/todo/scripts" \
         "$FAKE_ROOT/skills/todo-list/scripts"
cp "$REPO/common/scripts/silencers.sh" "$FAKE_ROOT/common/scripts/"

# Stub each sub-orchestrator to print its own name.
for skill in jot plate debate todo todo-list; do
  stub="$FAKE_ROOT/skills/$skill/scripts/${skill}-orchestrator.sh"
  printf '#!/bin/bash\necho dispatched:%s\nexit 0\n' "$skill" > "$stub"
  chmod +x "$stub"
done

export CLAUDE_PLUGIN_ROOT="$FAKE_ROOT"

assert_dispatch() {
  local prompt="$1" expected="$2"
  local hook_input
  hook_input=$(python3 -c '
import json,sys
print(json.dumps({"prompt": sys.argv[1]}))
' "$prompt")
  got=$(printf '%s' "$hook_input" | bash "$ORCH" || true)
  if [ "$got" != "$expected" ]; then
    echo "FAIL: prompt='$prompt' expected='$expected' got='$got'" >&2
    exit 1
  fi
}

assert_dispatch "/jot foo"         "dispatched:jot"
assert_dispatch "/plate"           "dispatched:plate"
assert_dispatch "/debate topic"    "dispatched:debate"
assert_dispatch "/todo an idea"    "dispatched:todo"
assert_dispatch "/todo"            "dispatched:todo"
assert_dispatch "/todo-list"       "dispatched:todo-list"
# Critical: /todo-clean must NOT route to /todo.
assert_dispatch "/todo-clean"      ""
# Arbitrary text must not route anywhere.
assert_dispatch "hello world"      ""

# Namespaced forms (Claude Code "/jot:<skill>" disambiguation) must dispatch.
assert_dispatch "/jot:jot foo"       "dispatched:jot"
assert_dispatch "/jot:plate"         "dispatched:plate"
assert_dispatch "/jot:debate topic"  "dispatched:debate"
assert_dispatch "/jot:todo an idea"  "dispatched:todo"
assert_dispatch "/jot:todo"          "dispatched:todo"
assert_dispatch "/jot:todo-list"     "dispatched:todo-list"
# /jot:todo-clean still falls through — same as bare /todo-clean.
assert_dispatch "/jot:todo-clean"    ""

echo "PASS: orchestrator routes all 6 bare prefixes AND their /jot: namespaced forms; /todo-clean falls through"
