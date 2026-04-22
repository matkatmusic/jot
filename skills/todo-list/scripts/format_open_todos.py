#!/usr/bin/env python3
"""Read Todos/*.md (not Todos/done/), parse frontmatter, format open TODOs.

Env input:
    TODOS_DIR — absolute path to the project's Todos/ directory.

Writes formatted list to stdout. Empty output means no open TODOs.
"""
import os
import re
import sys
from pathlib import Path

TODOS_DIR = os.environ.get("TODOS_DIR", "")
if not TODOS_DIR or not Path(TODOS_DIR).is_dir():
    sys.exit(0)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


todos = []
for path in sorted(Path(TODOS_DIR).glob("*.md")):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        continue
    fm = parse_frontmatter(text)
    if not fm:
        continue
    if fm.get("status", "").lower() != "open":
        continue
    todos.append(fm)


def sort_key(t):
    tid = t.get("id", "")
    try:
        return (0, int(tid))
    except ValueError:
        return (1, tid)


todos.sort(key=sort_key)

if not todos:
    sys.exit(0)

lines = []
for t in todos:
    lines.append(f"ID: {t.get('id', '?')}")
    lines.append(f"Created: {t.get('created', '?')}")
    lines.append(f"Title: {t.get('title', '?')}")
    lines.append(f"Branch: {t.get('branch', '?')}")
    lines.append("")

lines.append(f"{len(todos)} open TODO{'s' if len(todos) != 1 else ''}")
print("\n".join(lines))
