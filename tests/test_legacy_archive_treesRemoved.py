"""Structural assertions for Section 3 of the Python migration plan.

Verifies that three pre-Python bash trees are deleted from disk and that
no live ``.py`` / ``.json`` source references any path inside them.

Provenance anchors that mention these tree paths are preserved in markdown
docs (e.g. ``MIGRATION_TO_PYTHON.md``, ``plans/`` history, ``.claude/``
agent-memory). The grep helper filters those out so only live importer
references would surface.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Repo root resolves from this file's location: tests/<this>.py -> repo root.
__REPO_ROOT__ = Path(__file__).resolve().parent.parent


def legacy_archiveTreeRoots() -> list[Path]:
    """Return the three legacy tree roots (absolute paths) that must be gone."""
    relative = [
        Path("skills/plate/scripts/archive"),
        Path("skills/debate/scripts/OLD_DISCARD"),
        Path("TO_DELETE"),
    ]
    return [__REPO_ROOT__ / p for p in relative]


def legacy_grepArchiveTreeReferences() -> list[str]:
    """Return live ``.py`` / ``.json`` references to the legacy tree paths.

    Filters out:
    - Hits inside the trees themselves (they are about to be deleted).
    - Hits inside ``.md`` files (provenance/history docs).
    - Hits inside ``.claude/`` (agent-memory provenance).
    - Hits inside ``plans/`` (migration plan history).
    - Hits inside ``MIGRATION_TO_PYTHON.md`` (provenance anchor).
    - Hits inside ``.git/``.
    """
    tree_paths = [
        "skills/plate/scripts/archive",
        "skills/debate/scripts/OLD_DISCARD",
        "TO_DELETE",
    ]
    hits: list[str] = []
    for tree in tree_paths:
        # Test action: shell out to grep for the tree path string.
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "--include=*.py",
                "--include=*.json",
                tree,
                str(__REPO_ROOT__),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            # Filter: drop hits inside the tree itself.
            if f"/{tree}/" in line:
                continue
            # Filter: drop provenance/doc directories.
            if "/.git/" in line:
                continue
            if "/.claude/" in line:
                continue
            if "/plans/" in line:
                continue
            # Filter: drop markdown (defensive; --include already excludes).
            if line.split(":", 1)[0].endswith(".md"):
                continue
            # Filter: drop MIGRATION_TO_PYTHON.md provenance anchor.
            if "MIGRATION_TO_PYTHON.md" in line.split(":", 1)[0]:
                continue
            # Filter: drop this test file itself (it must name the paths
            # to assert their absence; that is not a live importer).
            if line.split(":", 1)[0] == str(Path(__file__).resolve()):
                continue
            hits.append(line)
    return hits


def test_legacyArchiveTrees_areRemoved() -> None:
    # Scenario: three pre-Python bash trees must be deleted.
    # Setup: enumerate the expected-gone roots.
    expected_gone = legacy_archiveTreeRoots()
    # Test action: check each on disk.
    still_present = [p for p in expected_gone if p.exists()]
    # Test verification: zero remaining.
    assert still_present == []


def test_noLiveReferencesToDeletedArchiveTrees() -> None:
    # Scenario: no .py/.json file may reference the deleted trees.
    # Setup: gather sources to grep.
    references = legacy_grepArchiveTreeReferences()
    # Test verification: zero hits outside docstrings/comments.
    assert references == []
