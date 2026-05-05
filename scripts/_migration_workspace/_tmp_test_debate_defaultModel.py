"""RED-YELLOW-GREEN tests for debate_defaultModel.

Mirrors bash `_default_model <agent>` from jot-plugin-orchestrator.sh
(lines 2186-2190). Reads `models.json` at
`${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/models.json` and
returns index-0 model for the requested agent, "" if missing/empty.

RELAXED_COVERAGE: no paired bash _tests existed; tests authored from
docstring + bash body inspection.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Standard temp file headers: insert workspace dir on sys.path so
# the SUT module can be imported by its temp filename.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _tmp_debate_defaultModel import debate_defaultModel  # noqa: E402


# Helper: build a fake plugin root with a models.json containing `payload`.
def _make_plugin_root(tmp_path: Path, payload: dict) -> Path:
    assets = tmp_path / "skills" / "debate" / "scripts" / "assets"
    assets.mkdir(parents=True)
    (assets / "models.json").write_text(json.dumps(payload))
    return tmp_path


def test_returns_first_claude_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "claude".
    # Setup: plugin root with models.json mapping claude -> 3 models.
    root = _make_plugin_root(tmp_path, {
        "claude": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        "gemini": ["gemini-3.1-pro-preview"],
        "codex": ["gpt-5.5"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="claude".
    result = debate_defaultModel("claude")
    # Test verification: index-0 entry for claude is returned verbatim.
    assert result == "claude-opus-4-7"


def test_returns_first_gemini_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "gemini".
    # Setup: plugin root with multi-entry gemini list.
    root = _make_plugin_root(tmp_path, {
        "gemini": ["gemini-3.1-pro-preview", "gemini-3-flash-preview"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: returns the first gemini model only.
    assert result == "gemini-3.1-pro-preview"


def test_returns_first_codex_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "codex".
    # Setup: plugin root with codex list.
    root = _make_plugin_root(tmp_path, {
        "codex": ["gpt-5.5", "gpt-5.4"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="codex".
    result = debate_defaultModel("codex")
    # Test verification: index-0 codex model returned.
    assert result == "gpt-5.5"


def test_unknown_agent_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: caller asks for an agent absent from models.json.
    # Setup: models.json with only claude listed.
    root = _make_plugin_root(tmp_path, {"claude": ["claude-opus-4-7"]})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for an unmapped agent name.
    result = debate_defaultModel("gemini")
    # Test verification: bash `// ""` fallback is "", not None / KeyError.
    assert result == ""


def test_agent_with_empty_list_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: agent key exists but has no models configured.
    # Setup: gemini key maps to an empty array.
    root = _make_plugin_root(tmp_path, {"gemini": []})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: jq `.[$a][0] // ""` returns "" on empty list.
    assert result == ""


def test_missing_plugin_root_env_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_ROOT is unset (plugin harness not active).
    # Setup: clear the env var.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # Test action + verification: a clear error is raised, not silent "".
    with pytest.raises((KeyError, RuntimeError)):
        debate_defaultModel("claude")
