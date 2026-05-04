#!/bin/bash
# frontmatter-parse-test.sh — validate SKILL.md frontmatter is well-formed.
# Uses the same minimal parser shape as format_open_todos.py (regex + colon split).
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$THIS_DIR/../SKILL.md"

[ -f "$SKILL" ] || { echo "FAIL: SKILL.md missing at $SKILL" >&2; exit 1; }

python3 - "$SKILL" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
if not m:
    print("FAIL: no YAML frontmatter block", file=sys.stderr); sys.exit(1)
fm = {}
for line in m.group(1).splitlines():
    if ":" in line:
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
for key in ("name", "description"):
    if key not in fm:
        print(f"FAIL: missing frontmatter key '{key}'", file=sys.stderr); sys.exit(1)
if fm["name"] != "todo-clean":
    print(f"FAIL: name={fm['name']!r}, expected 'todo-clean'", file=sys.stderr); sys.exit(1)
if "/todo-clean" not in fm["description"]:
    print("FAIL: description missing /todo-clean trigger", file=sys.stderr); sys.exit(1)
print("PASS: todo-clean frontmatter parses and has required keys")
PY
