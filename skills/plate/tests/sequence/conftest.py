"""pytest fixtures for the /plate sequence test harness."""
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import setup_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Fresh git repo with the standard topology, isolated per test.

    Topology produced by setup_repo():
        main: A
              \\
        fix:   B - F1 (HEAD, clean WT)
    """
    return setup_repo(tmp_path)
