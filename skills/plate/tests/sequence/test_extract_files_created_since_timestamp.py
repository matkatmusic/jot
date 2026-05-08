"""Unit tests for `plate_extractFilesCreatedSinceTimestamp`.

Combines B1 (Bash parser), B2 (subagent enum), B3 (chained iterator) to
return repo-relative file paths from `Bash` and `Edit`/`Write`/`MultiEdit`
tool_use records since `since_iso`. Created paths must currently exist
in WT (created-then-deleted is filtered out).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from plate_lib import plate_extractFilesCreatedSinceTimestamp


def _writeTranscript(path: Path, records: list[dict]) -> Path:
    # Setup helper: write each record as a JSONL line under message.content[].
    lines = []
    for rec in records:
        lines.append(json.dumps({
            "type": "assistant",
            "timestamp": rec["timestamp"],
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": f"toolu_{rec['timestamp']}",
                    "name": rec["tool"],
                    "input": rec.get("input", {}),
                }],
            },
        }))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_extracts_files_from_bash_redirect(tmp_path: Path) -> None:
    # Scenario: a Bash tool_use that writes a file via `>` redirect must surface in the result.
    repo = tmp_path / "repo"
    repo.mkdir()
    # Setup: file present in WT (matches the post-create observable state).
    (repo / "newfile.txt").write_text("x\n")
    parent = tmp_path / "parent.jsonl"
    _writeTranscript(parent, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "Bash",
         "input": {"command": "printf 'x' > newfile.txt"}},
    ])
    # Test action.
    result = plate_extractFilesCreatedSinceTimestamp(parent, None, repo)
    # Test verification: repo-relative path captured.
    assert result == ["newfile.txt"]


def test_extracts_files_from_bash_touch(tmp_path: Path) -> None:
    # Scenario: a Bash `touch` tool_use captures empty-file creation.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").touch()
    parent = tmp_path / "parent.jsonl"
    _writeTranscript(parent, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "Bash",
         "input": {"command": "touch a.txt"}},
    ])
    result = plate_extractFilesCreatedSinceTimestamp(parent, None, repo)
    assert result == ["a.txt"]


def test_extracts_files_from_subagent_bash(tmp_path: Path) -> None:
    # Scenario: a Bash record in a sidechain agent-*.jsonl must attribute to the parent.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "child.txt").write_text("x\n")
    parent = tmp_path / "parent.jsonl"
    parent.write_text("")
    sub_dir = tmp_path / "parent" / "subagents"
    sub_dir.mkdir(parents=True)
    _writeTranscript(sub_dir / "agent-001.jsonl", [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "Bash",
         "input": {"command": "touch child.txt"}},
    ])
    # Test action.
    result = plate_extractFilesCreatedSinceTimestamp(parent, None, repo)
    # Test verification: subagent's authored file appears.
    assert result == ["child.txt"]


def test_filters_out_files_no_longer_in_wt(tmp_path: Path) -> None:
    # Scenario: created-then-deleted must NOT leak into the result.
    repo = tmp_path / "repo"
    repo.mkdir()
    parent = tmp_path / "parent.jsonl"
    _writeTranscript(parent, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "Bash",
         "input": {"command": "touch transient.txt"}},
    ])
    # No transient.txt on disk: simulates a transient file that was created then removed.
    result = plate_extractFilesCreatedSinceTimestamp(parent, None, repo)
    assert result == []


def test_returns_repo_relative_paths(tmp_path: Path) -> None:
    # Scenario: result is repo-relative, even though the parser anchors via resolved repo root.
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / "sub" / "deep.txt").write_text("x\n")
    parent = tmp_path / "parent.jsonl"
    _writeTranscript(parent, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "Bash",
         "input": {"command": "touch sub/deep.txt"}},
    ])
    result = plate_extractFilesCreatedSinceTimestamp(parent, None, repo)
    assert result == ["sub/deep.txt"]
