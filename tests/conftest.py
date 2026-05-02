"""Root pytest conftest.

Puts common/scripts on sys.path so tests can `import git_lib` directly,
and common/scripts/plate so tests that still depend on plate-side test
helpers (makeTestRepo*, makeTestFile, createUntrackedFile, etc.) and
their associated constants can `import plate_lib`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "common" / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "common" / "scripts" / "plate"))
