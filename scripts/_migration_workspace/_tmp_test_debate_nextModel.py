"""RED tests for debate_nextModel — migrated from bash _next_model.

Author: Python pro subagent
Date: 2026-05-04
RELAXED_COVERAGE: no paired bash _tests; tests authored from intent + body.
"""
import json
import sys
from pathlib import Path

import pytest

# Ensure workspace dir on sys.path so we can import the temp production module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_nextModel import debate_nextModel  # noqa: E402


@pytest.fixture
def models_file(tmp_path: Path) -> Path:
    # Setup: typical models.json shape per assets/models.json.
    p = tmp_path / "models.json"
    p.write_text(json.dumps({
        "gemini": ["gem-pro", "gem-flash", "gem-lite"],
        "codex":  ["gpt-a", "gpt-b"],
        "claude": ["c-opus", "c-sonnet"],
    }))
    return p


def test_returns_first_model_when_none_tried(models_file: Path) -> None:
    # Scenario: no models tried yet for an agent.
    # Setup: empty TRIED_MODELS entry for "gemini".
    tried = {"gemini": "", "codex": "", "claude": ""}
    # Test action: ask for next model for gemini.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: first model in list is returned.
    assert result == "gem-pro"


def test_skips_already_tried_models(models_file: Path) -> None:
    # Scenario: first two gemini models already tried.
    # Setup: comma-joined tried list matching bash idiom ",a,b,".
    tried = {"gemini": "gem-pro,gem-flash", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: third model returned.
    assert result == "gem-lite"


def test_returns_none_when_all_tried(models_file: Path) -> None:
    # Scenario: every model in the list has been tried.
    # Setup: tried list contains all gemini entries.
    tried = {"gemini": "gem-pro,gem-flash,gem-lite", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: bash returned rc=1; Python returns None.
    assert result is None


def test_unknown_agent_returns_none(models_file: Path) -> None:
    # Scenario: agent key absent from models.json.
    # Setup: tried dict has agent but JSON does not.
    tried = {"mystery": ""}
    # Test action: request next model for unknown agent.
    result = debate_nextModel("mystery", tried, str(models_file))
    # Test verification: no model available -> None.
    assert result is None


def test_partial_tried_with_leading_comma(models_file: Path) -> None:
    # Scenario: tried list has bash-style leading comma artifact (",first").
    # Setup: tried entry mimics how _stash appends (",${next}").
    tried = {"codex": ",gpt-a"}
    # Test action: request next codex model.
    result = debate_nextModel("codex", tried, str(models_file))
    # Test verification: gpt-a is skipped, gpt-b returned.
    assert result == "gpt-b"


def test_missing_models_file_returns_none(tmp_path: Path) -> None:
    # Scenario: models.json path does not exist.
    # Setup: point at nonexistent file (bash hide_errors -> empty stdin -> rc=1).
    tried = {"gemini": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(tmp_path / "missing.json"))
    # Test verification: graceful None.
    assert result is None
