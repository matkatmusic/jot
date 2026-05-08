"""Structural test: only one module file in the tree may be named `plate_lib.py`.

Section 2 of plans/python-migration-complete.md mandates that the plate
runtime live in exactly one place on disk. Historically two files coexisted:

  - `common/scripts/plate_lib.py`        (the orchestrator-facing dispatcher)
  - `common/scripts/plate/plate_lib.py`  (the deep runtime)

Both were importable simultaneously, which is a footgun: edits to one
silently diverged from the other, and `from common.scripts.plate_lib ...`
versus `from common.scripts.plate.plate_lib ...` resolved to different
modules with overlapping concerns. After consolidation the dispatcher is
renamed to `plate_dispatcher.py` and the runtime keeps the canonical
`plate/plate_lib.py` filename. This test fails RED while two `plate_lib.py`
files exist; it goes GREEN once the dispatcher is renamed.
"""

from __future__ import annotations

import importlib
from pathlib import Path


def _repoRoot() -> Path:
    """Resolve the repo root (parent of `tests/`)."""
    return Path(__file__).resolve().parent.parent


def plate_collectAllPlateLibModuleFiles() -> set[str]:
    """Find every file in the source tree literally named `plate_lib.py`.

    Excludes virtualenvs, build artifacts, and git internals so the
    assertion only counts checked-in source files. After consolidation
    exactly one such file must remain.
    """
    repo = _repoRoot()
    skip_parts = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
    found: set[str] = set()
    for path in repo.rglob("plate_lib.py"):
        # Skip files buried inside any excluded directory.
        if any(part in skip_parts for part in path.relative_to(repo).parts):
            continue
        found.add(str(path.resolve()))
    return found


def plate_resolveDispatcherPlateMainFile() -> str:
    """Resolve `plate_main` via the canonical post-rename import path.

    Verifies that every importer of `plate_main` reaches the dispatcher
    module after consolidation. Before the rename this raises
    ModuleNotFoundError because the dispatcher still lives at
    `common.scripts.plate_lib`; after the rename it succeeds.
    """
    mod = importlib.import_module("common.scripts.plate_dispatcher")
    plate_main_fn = getattr(mod, "plate_main")
    defining_module = importlib.import_module(plate_main_fn.__module__)
    return str(Path(defining_module.__file__).resolve())


def test_plate_lib_singleSourceOfTruth() -> None:
    # Scenario: only one source file in the tree may be named plate_lib.py.
    # Setup: scan the repo for every plate_lib.py.
    plate_lib_files = plate_collectAllPlateLibModuleFiles()
    # Test action: count distinct files.
    distinct_count = len(plate_lib_files)
    # Test verification: exactly one canonical runtime file remains.
    assert distinct_count == 1, (
        f"expected 1 plate_lib.py in tree, found {distinct_count}: {plate_lib_files}"
    )


def test_plate_dispatcherImportPath_resolvesToRenamedModule() -> None:
    # Scenario: after rename, plate_main is imported from plate_dispatcher.
    # Setup: import via the post-rename path.
    dispatcher_file = plate_resolveDispatcherPlateMainFile()
    # Test action: extract the basename.
    basename = Path(dispatcher_file).name
    # Test verification: the canonical dispatcher module is plate_dispatcher.py.
    assert basename == "plate_dispatcher.py", (
        f"plate_main must resolve from plate_dispatcher.py, got {dispatcher_file}"
    )
