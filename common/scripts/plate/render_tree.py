#!/usr/bin/env python3
"""Render tree.md from all instance JSONs.

Reads all .plate/instances/*.json and produces a box-drawing tree showing
parent/child delegation relationships, sorted by last_touched desc.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

def load_instances(plate_root: Path) -> list[dict[str, Any]]:
    """Load all instance JSONs."""
    instances: list[dict[str, Any]] = []
    inst_dir = plate_root / "instances"
    if not inst_dir.exists():
        return instances
    for path in sorted(inst_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            instances.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return instances

def build_children_map(instances: list[dict]) -> dict[str, list[dict]]:
    """Map parent convo_id -> list of child instances."""
    children: dict[str, list[dict]] = {}
    for inst in instances:
        pr = inst.get("parent_ref", {}) or {}
        parent_convo = pr.get("convo_id")
        if parent_convo:
            children.setdefault(parent_convo, []).append(inst)
    return children

def format_plate_line(plate: dict) -> str:
    """Render a single plate line."""
    state = plate.get("state", "?")
    action = plate.get("summary_action") or "(no synopsis)"
    marker = {"paused": "◷", "delegated": "▶", "completed": "✓"}.get(state, "·")
    return f"{marker} [{state}] {action}"

def render_instance(
    inst: dict,
    children_map: dict[str, list[dict]],
    out: list[str],
    prefix: str = "",
    is_last: bool = True,
) -> None:
    """Recursive render with box-drawing characters."""
    convo = inst.get("convo_id", "")
    label = inst.get("label") or convo[:12]
    cwd = inst.get("cwd", "")
    touched = inst.get("last_touched", "")

    connector = "└── " if is_last else "├── "
    out.append(f"{prefix}{connector}{label}  ({convo[:8]})")
    child_prefix = prefix + ("    " if is_last else "│   ")
    out.append(f"{child_prefix}cwd: {cwd}")
    out.append(f"{child_prefix}last_touched: {touched}")

    stack = inst.get("stack", [])
    completed = inst.get("completed", [])
    if stack:
        out.append(f"{child_prefix}stack:")
        for p in stack:
            out.append(f"{child_prefix}  {format_plate_line(p)}")
    if completed:
        out.append(f"{child_prefix}completed: {len(completed)}")

    sub_children = children_map.get(convo, [])
    sub_children.sort(key=lambda x: x.get("last_touched", ""), reverse=True)
    for i, child in enumerate(sub_children):
        render_instance(
            child,
            children_map,
            out,
            prefix=child_prefix,
            is_last=(i == len(sub_children) - 1),
        )

def render_tree(plate_root: Path) -> str:
    instances = load_instances(plate_root)
    children_map = build_children_map(instances)

    # Top-level = no parent_ref or parent_ref.convo_id is None
    roots = [
        inst for inst in instances
        if not (inst.get("parent_ref") or {}).get("convo_id")
    ]
    roots.sort(key=lambda x: x.get("last_touched", ""), reverse=True)

    out: list[str] = []
    out.append("# .plate/tree.md")
    out.append("")
    out.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    out.append(f"Instances: {len(instances)}")
    out.append("")
    if not roots:
        out.append("(no top-level instances)")
    else:
        for i, root in enumerate(roots):
            render_instance(
                root,
                children_map,
                out,
                prefix="",
                is_last=(i == len(roots) - 1),
            )
            out.append("")

    return "\n".join(out) + "\n"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: render_tree.py <plate_root>", file=sys.stderr)
        sys.exit(1)
    plate_root = Path(sys.argv[1])
    content = render_tree(plate_root)
    (plate_root / "tree.md").write_text(content, encoding="utf-8")
    print(f"Wrote {plate_root / 'tree.md'}")
