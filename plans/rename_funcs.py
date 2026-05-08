#!/usr/bin/env python3
"""rename_funcs.py — generic word-boundary bulk-rename driver.

Given a JSON config that declares a list of {old, new} name substitutions
and a list of target files (relative to repo root), applies word-boundary
regex substitution to each file. `\b<old>\b` -> `<new>`.

Usage:
    python3 plans/rename_funcs.py <config.json>

Config schema:
    {
      "name": "human-readable label",
      "mapping": [
        {"old": "createRandomBranchName", "new": "plate_createRandomBranchName"},
        ...
      ],
      "targets": [
        "common/scripts/plate/plate_lib.py",
        ...
      ]
    }

Behavior:
    - Sorts mapping by descending old-name length (collision safety).
    - Skips entries where `old == new` (no-op).
    - Skips missing target files with a stderr warning.
    - Prints per-file replacement counts and a grand total.

Why word-boundary regex (not plain str.replace): `\b` ensures
`random_string` doesn't match inside `random_string_or_bytes`. Also
handles string-literal references (mock.patch.object 2nd arg, etc.)
naturally since `\b` semantics work the same way inside quotes.

Past invocations (kept as records under plans/):
    plans/rename_plate_funcs.json   — May 2026, 27 plate_lib funcs
    plans/rename_debate_funcs.json  — May 2026, 7 debate_lib funcs
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def loadConfig(config_path: Path) -> dict:
    """Read and validate the JSON config. Raises ValueError on bad shape."""
    config = json.loads(config_path.read_text())
    for required in ("name", "mapping", "targets"):
        if required not in config:
            raise ValueError(f"config missing required field: {required!r}")
    for entry in config["mapping"]:
        if "old" not in entry or "new" not in entry:
            raise ValueError(f"mapping entry missing old/new: {entry!r}")
    return config


def buildSubstitutionPlan(mapping: list[dict]) -> list[tuple[str, str]]:
    """Filter no-ops, sort longest-first to avoid partial-overlap miscarriage."""
    plan = [(e["old"], e["new"]) for e in mapping if e["old"] != e["new"]]
    plan.sort(key=lambda pair: -len(pair[0]))
    return plan


def renameOneFile(path: Path, plan: list[tuple[str, str]]) -> dict[str, int]:
    """Apply every substitution to `path`. Returns dict[old_name, count]."""
    text = path.read_text()
    counts: dict[str, int] = {}
    new_text = text
    for old, new in plan:
        new_text, n = re.subn(rf"\b{re.escape(old)}\b", new, new_text)
        if n:
            counts[old] = n
    if new_text != text:
        path.write_text(new_text)
    return counts


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: rename_funcs.py <config.json>", file=sys.stderr)
        return 2

    config_path = Path(argv[0])
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()
    config = loadConfig(config_path)
    plan = buildSubstitutionPlan(config["mapping"])

    print(f"=== {config['name']} ===")
    print(f"({len(plan)} substitutions across {len(config['targets'])} files)\n")

    plan_lookup = dict(plan)
    grand_total = 0
    for rel in config["targets"]:
        path = REPO_ROOT / rel
        if not path.is_file():
            print(f"SKIP (missing): {rel}", file=sys.stderr)
            continue
        counts = renameOneFile(path, plan)
        file_total = sum(counts.values())
        grand_total += file_total
        print(f"{rel}: {file_total} replacements")
        for old, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"    {old} -> {plan_lookup[old]}: {n}")
    print(f"\nTOTAL: {grand_total} replacements across {len(config['targets'])} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
