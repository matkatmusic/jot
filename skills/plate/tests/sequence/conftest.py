"""pytest fixtures for the /plate sequence test harness."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# plate_lib (formerly tests/sequence/helpers.py) now lives in
# common/scripts/plate/. Inject that on sys.path so this conftest and
# every test in this directory can `import plate_lib`.
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "common" / "scripts" ))

# plate_lib's '_check' functions now live at skills/plate/tests/sequence/
sys.path.insert(0, str(_REPO_ROOT / "skills" / "plate" / "tests" / "sequence"))

from git_test_funcs_lib import setup_git_plate_test_repo  # noqa: E402
from git_lib import getCurrentGitBranchName

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Fresh git repo with the standard topology, isolated per test.

    Topology produced by setup_git_plate_test_repo():
        main: A
              \\
        fix:   B - F1 (HEAD, clean WT)
    """
    return setup_git_plate_test_repo(tmp_path)
