"""Generate the function-name audit for MIGRATION_TO_PYTHON.md.

Walks every .py in the worktree (per scope rules) and emits markdown
listing top-level FunctionDef/AsyncFunctionDef/ClassDef in source order,
with one level of class-method nesting.
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

ROOT = Path("/Users/matkatmusicllc/Programming/jot")
EXCLUDE_NAMES = {"conftest.py"}
EXCLUDE_PATHS = {ROOT / "scripts" / "jot-plugin-orchestrator-historic.py"}

# Section grouping: prefix -> heading. First match wins.
SECTIONS = [
    ("common/scripts/plate/", "## common/scripts/plate/"),
    ("common/scripts/jot/", "## common/scripts/jot/"),
    ("common/scripts/", "## common/scripts/"),
    ("scripts/", "## scripts/"),
    ("skills/plate/tests/sequence/", "## skills/plate/tests/sequence/"),
    ("skills/", "## skills/"),
    ("tests/", "## tests/"),
]


def list_definitions(src_path: Path) -> tuple[list[str], int, int]:
    """Return (lines, fn_count, cls_count) for a single file."""
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    out: list[str] = []
    fn_count = 0
    cls_count = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            suffix = " (async)" if isinstance(node, ast.AsyncFunctionDef) else ""
            out.append(f"- {node.name}{suffix}")
            fn_count += 1
        elif isinstance(node, ast.ClassDef):
            out.append(f"- class {node.name}")
            cls_count += 1
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sx = " (async)" if isinstance(sub, ast.AsyncFunctionDef) else ""
                    out.append(f"  - {node.name}.{sub.name}{sx}")
                    fn_count += 1
    return out, fn_count, cls_count


def section_for(rel: str) -> str:
    for prefix, heading in SECTIONS:
        if rel.startswith(prefix):
            return heading
    return "## (other)"


def main() -> None:
    files: list[Path] = []
    for p in ROOT.rglob("*.py"):
        if any(part.startswith(".") for part in p.relative_to(ROOT).parts):
            continue
        if p.name in EXCLUDE_NAMES:
            continue
        if p in EXCLUDE_PATHS:
            continue
        files.append(p)
    files.sort()

    by_section: dict[str, list[Path]] = {}
    for p in files:
        rel = str(p.relative_to(ROOT))
        by_section.setdefault(section_for(rel), []).append(p)

    total_files = 0
    total_fns = 0
    total_classes = 0

    lines: list[str] = []
    lines.append("# Python function audit")
    lines.append("")
    lines.append(
        "Authoritative list of top-level functions and classes (with one "
        "level of method nesting) for every Python file in this worktree. "
        "Used as input when deciding how to split large modules into "
        "smaller, area-focused files."
    )
    lines.append("")
    lines.append(f"Last generated: {date.today().isoformat()}")
    lines.append("")
    lines.append("Regenerate from the worktree root with:")
    lines.append("")
    lines.append("```")
    lines.append("python3 /tmp/audit_gen.py > MIGRATION_TO_PYTHON.md")
    lines.append("```")
    lines.append("")
    lines.append(
        "Excluded: every `conftest.py` and "
        "`scripts/jot-plugin-orchestrator-historic.py`."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    section_order = [h for _, h in SECTIONS] + ["## (other)"]
    for heading in section_order:
        if heading not in by_section:
            continue
        lines.append(heading)
        lines.append("")
        for p in by_section[heading]:
            rel = str(p.relative_to(ROOT))
            defs, fn_count, cls_count = list_definitions(p)
            lines.append(f"### {rel}")
            lines.append("")
            if defs:
                lines.extend(defs)
            else:
                lines.append("*(no top-level functions or classes)*")
            lines.append("")
            lines.append(f"({fn_count} functions, {cls_count} classes)")
            lines.append("")
            total_files += 1
            total_fns += fn_count
            total_classes += cls_count

    lines.append("---")
    lines.append("")
    lines.append(
        f"**Totals:** {total_files} files, {total_fns} functions, "
        f"{total_classes} classes."
    )
    lines.append("")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
