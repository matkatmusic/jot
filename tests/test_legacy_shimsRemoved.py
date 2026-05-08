"""Section 4 of plans/python-migration-complete.md.

Asserts the two legacy back-compat re-export shims are deleted from source
and that the canonical modules continue to expose the symbols those shims
used to forward.
"""
from __future__ import annotations

from pathlib import Path

# Repo-root-relative paths. Tests assume CWD is the repo root, which is the
# convention used by the other tests/ modules (see tests/conftest.py).
_PLATE_LIB = Path("common/scripts/plate/plate_lib.py")
_GIT_LIB = Path("common/scripts/git_lib.py")


def test_gitTestFuncsLibShim_isRemovedFromPlateLib() -> None:
    # Scenario: the wildcard back-compat re-export of git_test_funcs_lib is gone
    # from plate_lib so importers are forced to the canonical module.
    # Setup: read the plate_lib source as text.
    text = _PLATE_LIB.read_text()
    # Test action: none — purely textual.
    # Test verification: the wildcard shim line is absent.
    assert "from common.scripts.git_test_funcs_lib import *" not in text


def test_runAndCurrentTimestampMsShim_isRemovedFromGitLib() -> None:
    # Scenario: the back-compat re-export of `run` and `currentTimestampMs`
    # from util_lib (via git_lib) is gone, so importers are forced to import
    # directly from util_lib.
    # Setup: read the git_lib source as text.
    text = _GIT_LIB.read_text()
    # Test action: none — purely textual.
    # Test verification: the exact shim import line is absent. Phrased
    # against the precise textual shim so benign internal uses of `run`
    # or `currentTimestampMs` elsewhere in the file do not false-positive.
    assert (
        "from common.scripts.util_lib import run, currentTimestampMs"
        not in text
    )


def test_gitTestFuncsLibSymbols_resolveFromCanonical() -> None:
    # Scenario: a representative public symbol of git_test_funcs_lib is
    # importable directly from its canonical home — i.e. nothing in the
    # codebase relies on plate_lib re-exporting it.
    # Setup: nothing.
    # Test action: import the canonical module and grab a public symbol.
    from common.scripts.git_test_funcs_lib import git_test_makeEmptyRepo
    # Test verification: the symbol is the expected callable.
    assert callable(git_test_makeEmptyRepo)


def test_runAndCurrentTimestampMs_resolveFromCanonical() -> None:
    # Scenario: `run` and `currentTimestampMs` resolve directly from
    # util_lib (their canonical home) — i.e. nothing in the codebase
    # relies on git_lib re-exporting them.
    # Setup: nothing.
    # Test action: import both symbols from the canonical module.
    from common.scripts.util_lib import currentTimestampMs, run
    # Test verification: both are callable.
    assert callable(run)
    assert callable(currentTimestampMs)
