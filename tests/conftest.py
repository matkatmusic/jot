from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def _hooks_file(tmp_path: Path) -> Path:
    # Setup: a hooks JSON file containing a representative hooks block.
    p = tmp_path / "hooks.json"
    p.write_text('{"SessionStart":[{"hooks":[{"type":"command","command":"x"}]}]}')
    return p


@pytest.fixture
def base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    # Setup: minimal valid plugin env for jot_main / debate_main style tests.
    # Sets CLAUDE_PLUGIN_ROOT, CLAUDE_PLUGIN_DATA, JOT_LOG_FILE; clears JOT_SKIP_LAUNCH.
    plugin_root = tmp_path / "plugin"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("JOT_LOG_FILE", str(tmp_path / "jot.log"))
    monkeypatch.delenv("JOT_SKIP_LAUNCH", raising=False)
    return {
        "plugin_root": str(plugin_root),
        "plugin_data": str(plugin_data),
        "tmp": str(tmp_path),
    }
