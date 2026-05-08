"""Unit tests for `_plate_iterToolUseRecordsSinceTimestamp`.

Yields each `tool_use` content block from a JSONL transcript, filtered
by `timestamp > since_iso`. Chains through `<parent_stem>/subagents/agent-*.jsonl`
so a Task-spawned subagent's tool_use records attribute to the parent.
"""
from __future__ import annotations

import json
from pathlib import Path

from plate_lib import _plate_iterToolUseRecordsSinceTimestamp


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


def test_yields_parent_records_only_when_no_subagents(tmp_path: Path) -> None:
    # Scenario: no subagents directory exists; iterator yields parent records only.
    parent = tmp_path / "parent.jsonl"
    _writeTranscript(parent, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "Edit",
         "input": {"file_path": "/repo/a.py"}},
        {"timestamp": "2026-05-08T10:01:00Z", "tool": "Bash",
         "input": {"command": "echo hi"}},
    ])
    # Test action.
    blocks = list(_plate_iterToolUseRecordsSinceTimestamp(parent, since_iso=None))
    # Test verification: both parent records yielded; no subagent contamination.
    names = [b.get("name") for b in blocks]
    assert names == ["Edit", "Bash"]


def test_yields_chained_records_from_parent_then_subagents(tmp_path: Path) -> None:
    # Scenario: parent + sidechain transcripts are walked in order.
    parent = tmp_path / "parent.jsonl"
    _writeTranscript(parent, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "Edit",
         "input": {"file_path": "/repo/a.py"}},
    ])
    # Setup: synthesize one subagent transcript at <parent_stem>/subagents/.
    sub_dir = tmp_path / "parent" / "subagents"
    sub_dir.mkdir(parents=True)
    _writeTranscript(sub_dir / "agent-001.jsonl", [
        {"timestamp": "2026-05-08T10:02:00Z", "tool": "Write",
         "input": {"file_path": "/repo/b.py"}},
    ])
    # Test action.
    blocks = list(_plate_iterToolUseRecordsSinceTimestamp(parent, since_iso=None))
    # Test verification: parent block first, subagent block second.
    names = [b.get("name") for b in blocks]
    assert names == ["Edit", "Write"]


def test_filters_records_before_timestamp(tmp_path: Path) -> None:
    # Scenario: records with `timestamp <= since_iso` must be excluded (strict).
    parent = tmp_path / "parent.jsonl"
    _writeTranscript(parent, [
        {"timestamp": "2026-05-08T09:00:00Z", "tool": "Edit",
         "input": {"file_path": "/repo/old.py"}},
        {"timestamp": "2026-05-08T11:00:00Z", "tool": "Edit",
         "input": {"file_path": "/repo/new.py"}},
    ])
    # Test action: filter to records strictly after 10:00.
    blocks = list(_plate_iterToolUseRecordsSinceTimestamp(
        parent, since_iso="2026-05-08T10:00:00Z",
    ))
    # Test verification: only the post-cutoff record yielded.
    paths = [b.get("input", {}).get("file_path") for b in blocks]
    assert paths == ["/repo/new.py"]
