"""Tests for transcript / convo extraction helpers.

Split from test_helpers.py per MIGRATION_TO_PYTHON.md bucket [convo].
"""
from __future__ import annotations

from pathlib import Path

import pytest

# After the test_* functions migrated out of plate_lib.py, every library
# symbol the tests reference must be importable into this namespace —
# including underscore-prefixed scenario callables (`_check_*`) and
# private helpers (`_plate_writeFakeTranscriptWithToolUse`, etc.) that
# `from plate_lib import *` would skip. Pull them in explicitly via vars().
# (sys.path setup already done by conftest.py.)
import plate_lib as _plate_lib
from common.scripts.git_lib import (
    getCurrentGitBranchName
)

import test_plate_scenarios as _plate_scenarios
from test_plate_scenarios import (
    _check_plate_push_creates_branch_capturing_wip,
)

globals().update({
    name: value
    for name, value in vars(_plate_scenarios).items()
    if name.startswith("_check_") or name.startswith("_build") or name.startswith("_write")
})

globals().update({
    name: value
    for name, value in vars(_plate_lib).items()
    if not name.startswith("__")
})

def test_localTranscriptIsReadable(tmp_path: Path):
    # None / empty → False
    assert plate_localTranscriptIsReadable(None) is False
    assert plate_localTranscriptIsReadable("") is False
    # Non-existent path → False
    assert plate_localTranscriptIsReadable(str(tmp_path / "missing.jsonl")) is False
    # Real, readable file → True
    real = tmp_path / "real.jsonl"
    real.write_text('{"type":"foo"}\n')
    assert plate_localTranscriptIsReadable(str(real)) is True

def test_extractConvoNameFromTranscript_returns_latest_custom_title(tmp_path: Path):
    transcript = tmp_path / "abc-123.jsonl"
    transcript.write_text(
        '{"type":"system","cwd":"/x"}\n'
        '{"type":"custom-title","customTitle":"first name","sessionId":"abc-123"}\n'
        '{"type":"user","content":"hi"}\n'
        '{"type":"custom-title","customTitle":"renamed","sessionId":"abc-123"}\n'
    )
    assert plate_extractConvoNameFromTranscript(transcript) == "renamed"

def test_extractConvoNameFromTranscript_falls_back_to_session_id_when_no_title(
    tmp_path: Path,
):
    transcript = tmp_path / "session-uuid-xyz.jsonl"
    transcript.write_text('{"type":"system","cwd":"/x"}\n')
    assert plate_extractConvoNameFromTranscript(transcript) == "session-uuid-xyz"

def test_extractConvoNameFromTranscript_returns_none_when_file_missing(tmp_path: Path):
    assert plate_extractConvoNameFromTranscript(tmp_path / "missing.jsonl") is None

def test_extractConvoNameFromTranscript_skips_unparseable_lines(tmp_path: Path):
    transcript = tmp_path / "abc.jsonl"
    transcript.write_text(
        'not-json\n'
        '{"type":"custom-title","customTitle":"valid","sessionId":"abc"}\n'
    )
    assert plate_extractConvoNameFromTranscript(transcript) == "valid"

def test_extractConvoCwdFromTranscript_returns_first_cwd(tmp_path: Path):
    transcript = tmp_path / "x.jsonl"
    transcript.write_text(
        '{"type":"custom-title","customTitle":"name"}\n'
        '{"type":"system","cwd":"/Users/me/project"}\n'
        '{"type":"user","cwd":"/Users/me/elsewhere"}\n'
    )
    assert plate_extractConvoCwdFromTranscript(transcript) == "/Users/me/project"

def test_extractConvoCwdFromTranscript_returns_none_when_no_cwd(tmp_path: Path):
    transcript = tmp_path / "x.jsonl"
    transcript.write_text('{"type":"system","other":"field"}\n')
    assert plate_extractConvoCwdFromTranscript(transcript) is None

def test_extractConvoCwdFromTranscript_returns_none_when_file_missing(tmp_path: Path):
    assert plate_extractConvoCwdFromTranscript(tmp_path / "missing.jsonl") is None

def test_extractFilesEditedSinceTimestamp_filters_by_tool_and_cutoff(tmp_path: Path):
    transcript = _plate_writeFakeTranscriptWithToolUse(
        tmp_path / "t.jsonl",
        [
            {"timestamp": "2026-04-30T10:00:00.000Z", "tool": "Edit",
             "input": {"file_path": "/repo/file_a.txt"}},
            {"timestamp": "2026-04-30T10:01:00.000Z", "tool": "Write",
             "input": {"file_path": "/repo/file_b.txt"}},
            {"timestamp": "2026-04-30T10:02:00.000Z", "tool": "Read",
             "input": {"file_path": "/repo/file_c.txt"}},  # NOT a modifier
            {"timestamp": "2026-04-30T10:03:00.000Z", "tool": "MultiEdit",
             "input": {"file_path": "/repo/file_d.txt"}},
            {"timestamp": "2026-04-30T10:04:00.000Z", "tool": "Edit",
             "input": {"file_path": "/repo/file_a.txt"}},  # dup
        ],
    )

    # Cutoff at T2 (10:01:00) — entries at/before excluded; Read excluded; dedup.
    result = plate_extractFilesEditedSinceTimestamp(
        transcript, since_iso="2026-04-30T10:01:00.000Z"
    )
    assert result == ["/repo/file_a.txt", "/repo/file_d.txt"]

    # No cutoff → all file-modifying entries (still no Read; still deduped).
    result_all = plate_extractFilesEditedSinceTimestamp(transcript, since_iso=None)
    assert result_all == ["/repo/file_a.txt", "/repo/file_b.txt", "/repo/file_d.txt"]

    # Missing file → [].
    assert plate_extractFilesEditedSinceTimestamp(tmp_path / "missing.jsonl", None) == []

def test_extractFilesDeletedSinceTimestamp(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    transcript = _plate_writeFakeTranscriptWithToolUse(
        tmp_path / "t.jsonl",
        [
            {"timestamp": "2026-04-30T10:00:00.000Z", "tool": "Bash",
             "input": {"command": f"rm {repo}/inside_a.txt"}},
            {"timestamp": "2026-04-30T10:01:00.000Z", "tool": "Bash",
             "input": {"command": "rm /var/log/outside.txt"}},  # outside repo
            {"timestamp": "2026-04-30T10:02:00.000Z", "tool": "Bash",
             "input": {"command": f"git rm {repo}/inside_b.txt"}},
            {"timestamp": "2026-04-30T10:03:00.000Z", "tool": "Bash",
             "input": {"command": f"rm {repo}/inside_c.txt {repo}/inside_d.txt"}},
            {"timestamp": "2026-04-30T10:04:00.000Z", "tool": "Bash",
             "input": {"command": "rm $(cat list.txt)"}},  # shell expansion
            {"timestamp": "2026-04-30T10:05:00.000Z", "tool": "Bash",
             "input": {"command": f"rm -rf {repo}/inside_e.txt"}},  # flag stripped
            {"timestamp": "2026-04-30T10:06:00.000Z", "tool": "Edit",
             "input": {"file_path": f"{repo}/not_a_deletion.txt"}},  # not Bash
        ],
    )

    # All entries, no cutoff — only inside-repo, no expansions, flags ignored.
    result = plate_extractFilesDeletedSinceTimestamp(transcript, since_iso=None, repo_root=repo)
    assert result == [
        "inside_a.txt", "inside_b.txt", "inside_c.txt", "inside_d.txt", "inside_e.txt",
    ]

    # Cutoff at T2 → entries strictly > 10:02 (inside_c, inside_d, inside_e).
    result_recent = plate_extractFilesDeletedSinceTimestamp(
        transcript, since_iso="2026-04-30T10:02:00.000Z", repo_root=repo
    )
    assert result_recent == ["inside_c.txt", "inside_d.txt", "inside_e.txt"]

    # Missing transcript → [].
    assert plate_extractFilesDeletedSinceTimestamp(
        tmp_path / "missing.jsonl", None, repo
    ) == []
