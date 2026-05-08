#!/usr/bin/env python3
"""rename_plate_funcs.py — bulk-rename plate_lib.py functions to add the
`plate_` domain prefix per the project's `<domain>_<verbPhrase>` convention.

Run once from the repo root:
    python3 plans/rename_plate_funcs.py

Performs word-boundary regex substitution across the 12 files known to
reference the 27 functions. Public names are prepended with `plate_`;
private names get `plate_` inserted after the leading underscore so the
Python privacy convention is preserved.

Plan: /Users/matkatmusicllc/.claude/plans/develop-a-plan-for-nested-bengio.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Public names: prepend `plate_`.
PUBLIC = [
    "createRandomBranchName",
    "random_string",
    "performRandomEdit",
    "formatPlateAge",
    "localTranscriptIsReadable",
    "extractConvoNameFromTranscript",
    "extractConvoCwdFromTranscript",
    "extractFilesEditedSinceTimestamp",
    "listPlateBranches",
    "findMyLastPlate",
    "stripConvoSummaryFromCommit",
    "regenerateTipSummary",
    "simulate_derived_agent",
    "extractFilesDeletedSinceTimestamp",
    "rewriteBranchTipSummary",
]

# Private names (leading `_`): insert `plate_` after the underscore.
PRIVATE = [
    "_writeFakeTranscriptWithToolUse",
    "_parseRmTargets",
    "_resolveTargetPlate",
    "_buildFullWtTree",
    "_buildExtractedTree",
    "_formatTrailerBody",
    "_trashBranchDir",
    "_writeTrashSession",
    "_listTrashSessions",
    "_resolvePlateTitle",
    "_writeTranscriptFile",
    "_buildTwoBranchPlateTopology",
]

MAPPING: list[tuple[str, str]] = (
    [(name, f"plate_{name}") for name in PUBLIC]
    + [(name, f"_plate_{name[1:]}") for name in PRIVATE]
)

# Sort longest-first to avoid any partial-overlap miscarriage on iteration.
MAPPING.sort(key=lambda pair: -len(pair[0]))

# Files known to reference the 27 names (from grep -rln verification).
TARGETS = [
    "common/scripts/plate/plate_lib.py",
    "common/scripts/plate/plate_cli.py",
    "common/scripts/plate/_rebase_reword_summary.py",
    "common/scripts/git_test_funcs_lib.py",
    "tests/test_git_lib.py",
    "skills/plate/tests/sequence/test_plate_cli.py",
    "skills/plate/tests/sequence/test_plate_scenarios.py",
    "skills/plate/tests/sequence/test_helpers_plate.py",
    "skills/plate/tests/sequence/test_helpers_convo.py",
    "skills/plate/tests/sequence/test_helpers_git_test_funcs.py",
    "skills/plate/tests/sequence/test_summary_pipeline.py",
    "skills/plate/tests/sequence/test_helpers_plate_sequence.py",
]


def renameOneFile(path: Path) -> dict[str, int]:
    """Apply every mapping to `path`. Returns dict[old_name, replacement_count]."""
    text = path.read_text()
    counts: dict[str, int] = {}
    new_text = text
    for old, new in MAPPING:
        pattern = rf"\b{re.escape(old)}\b"
        new_text, n = re.subn(pattern, new, new_text)
        if n:
            counts[old] = n
    if new_text != text:
        path.write_text(new_text)
    return counts


def main() -> int:
    grand_total = 0
    for rel in TARGETS:
        path = REPO_ROOT / rel
        if not path.is_file():
            print(f"SKIP (missing): {rel}", file=sys.stderr)
            continue
        counts = renameOneFile(path)
        file_total = sum(counts.values())
        grand_total += file_total
        print(f"{rel}: {file_total} replacements")
        for old, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"    {old} -> {dict(MAPPING)[old]}: {n}")
    print(f"\nTOTAL: {grand_total} replacements across {len(TARGETS)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
