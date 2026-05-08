"""Unit tests for `plate_enumerateSubagentTranscripts`.

Convention (verified against live ~/.claude/projects/ data):
    <parent_dir>/<parent_uuid>.jsonl                      parent transcript
    <parent_dir>/<parent_uuid>/subagents/agent-*.jsonl    sidechain transcripts
"""
from __future__ import annotations

from pathlib import Path

from plate_lib import plate_enumerateSubagentTranscripts


def test_returns_empty_when_no_subagents_dir(tmp_path: Path) -> None:
    # Scenario: a parent transcript with no sibling <stem>/subagents/ directory.
    # Setup: write a bare parent JSONL; do not create any subagents directory.
    parent = tmp_path / "ffb915f9-abac.jsonl"
    parent.write_text("")
    # Test action: enumerate.
    result = plate_enumerateSubagentTranscripts(parent)
    # Test verification: empty list (no false positives from random tmp_path content).
    assert result == []


def test_returns_all_agent_jsonl_files_in_subagents_dir(tmp_path: Path) -> None:
    # Scenario: two subagent transcripts authored under <parent_stem>/subagents/.
    # Setup: parent JSONL plus two agent-*.jsonl siblings in the conventional dir.
    parent = tmp_path / "ffb915f9-abac.jsonl"
    parent.write_text("")
    sub_dir = tmp_path / "ffb915f9-abac" / "subagents"
    sub_dir.mkdir(parents=True)
    a = sub_dir / "agent-001.jsonl"
    b = sub_dir / "agent-002.jsonl"
    a.write_text("")
    b.write_text("")
    # Test action.
    result = plate_enumerateSubagentTranscripts(parent)
    # Test verification: both subagent transcripts returned, sorted.
    assert result == [a, b]


def test_ignores_non_agent_jsonl_in_subagents_dir(tmp_path: Path) -> None:
    # Scenario: only files matching `agent-*.jsonl` count; other names are ignored.
    parent = tmp_path / "ffb915f9-abac.jsonl"
    parent.write_text("")
    sub_dir = tmp_path / "ffb915f9-abac" / "subagents"
    sub_dir.mkdir(parents=True)
    valid = sub_dir / "agent-001.jsonl"
    valid.write_text("")
    # Setup decoys: a different prefix and a wrong extension.
    (sub_dir / "task-001.jsonl").write_text("")
    (sub_dir / "agent-001.txt").write_text("")
    # Test action.
    result = plate_enumerateSubagentTranscripts(parent)
    # Test verification: only the conformant filename comes back.
    assert result == [valid]
