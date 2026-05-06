from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def _hooks_file(tmp_path: Path) -> Path:
    # Setup: a hooks JSON file containing a representative hooks block.
    p = tmp_path / "hooks.json"
    p.write_text('{"SessionStart":[{"hooks":[{"type":"command","command":"x"}]}]}')
    return p
