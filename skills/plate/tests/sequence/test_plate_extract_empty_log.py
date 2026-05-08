"""Unit tests for the plate-extract-empty diagnostic logger.

Covers `_plate_resolvePlateLogFile` and `_plate_logExtractEmptyButWtDirty`,
plus an integration check that `plate_push` writes the line when the
extraction tree equals parent_tree but the full WT does not.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from common.scripts.git_lib import (
    QUIET_OUTPUT,
    CREATE_BRANCH_AND_CHECKOUT_FLAG,
    git_addFile,
    git_createCommit,
    git_writeGitignore,
)
from common.scripts.util_lib import run

from plate_lib import (
    _plate_resolvePlateLogFile,
    _plate_logExtractEmptyButWtDirty,
    _plate_writeFakeTranscriptWithToolUse,
    plate_push,
)
import git_test_funcs_lib as _gtf


def test_resolvePlateLogFile_returns_path_under_repo_dot_plate(tmp_path: Path,
                                                              monkeypatch) -> None:
    # Scenario: with no PLATE_LOG_FILE env, the helper falls back to
    # <repo>/.plate/plate-log.txt and ensures the parent directory exists.
    # Setup: clear any inherited env so the env path is not honored.
    monkeypatch.delenv("PLATE_LOG_FILE", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    # Test action.
    log_path = _plate_resolvePlateLogFile(repo)
    # Test verification: path matches the canonical fallback and parent dir exists.
    assert log_path == repo / ".plate" / "plate-log.txt"
    assert log_path.parent.is_dir()


def test_resolvePlateLogFile_honors_env_var(tmp_path: Path, monkeypatch) -> None:
    # Scenario: PLATE_LOG_FILE wins when set (used by both plate.sh and tests).
    custom = tmp_path / "custom-dir" / "log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(custom))
    log_path = _plate_resolvePlateLogFile(tmp_path / "repo")
    assert log_path == custom
    # Parent created on demand.
    assert log_path.parent.is_dir()


def test_logExtractEmptyButWtDirty_writes_diagnostic_line(tmp_path: Path,
                                                         monkeypatch) -> None:
    # Scenario: helper appends one space-separated key=value line to the resolved log.
    log = tmp_path / "log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(log))
    repo = tmp_path / "repo"
    repo.mkdir()
    # Test action.
    _plate_logExtractEmptyButWtDirty(
        repo=repo, branch="feature-x", convo_id="UUID-B",
        wt_tree="WTSHA", parent_tree="PARENTSHA",
    )
    # Test verification: log line contains canonical event marker plus key=value pairs.
    contents = log.read_text()
    assert "plate-extract-empty" in contents
    assert "branch=feature-x" in contents
    assert "convo=UUID-B" in contents
    assert "wt_tree=WTSHA" in contents
    assert "parent_tree=PARENTSHA" in contents


def test_plate_push_logs_when_extract_tree_equals_parent_but_wt_dirty(
    tmp_path: Path, monkeypatch,
) -> None:
    # Scenario: second-agent push with a transcript that has no Edit/Write/Bash
    # records since cutoff, but a dirty WT, must write a plate-extract-empty
    # diagnostic line so silent no-op pushes are auditable.
    log = tmp_path / "log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(log))
    # Setup: 1-commit repo + first plate from convo A.
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "main"], cwd=repo)
    _gtf._git_test_createUserConfig(repo) if hasattr(_gtf, "_git_test_createUserConfig") else None
    run(["git", "config", "user.email", "t@t.t"], cwd=repo)
    run(["git", "config", "user.name", "t"], cwd=repo)
    git_writeGitignore(repo)
    git_addFile(repo, ".gitignore")
    (repo / "a.txt").write_text("base\n")
    git_addFile(repo, "a.txt")
    git_createCommit(repo, "initial")

    uuid_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    transcript_A = tmp_path / f"{uuid_A}.jsonl"
    _plate_writeFakeTranscriptWithToolUse(
        transcript_A,
        [{"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
          "input": {"file_path": str(repo / "a.txt")}}],
    )
    (repo / "a.txt").write_text("base\nA1\n")
    pa_sha = plate_push(repo, convo_id=uuid_A, transcript_path=str(transcript_A))
    assert pa_sha is not None

    # Second agent: empty transcript (no tool_use records) but dirty WT.
    uuid_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    transcript_B = tmp_path / f"{uuid_B}.jsonl"
    transcript_B.write_text("")
    (repo / "unrelated.txt").write_text("dirt\n")

    # Test action: push must return None (no extractable changes) and log.
    pb_sha = plate_push(repo, convo_id=uuid_B, transcript_path=str(transcript_B))
    # Test verification: no commit, but a diagnostic line landed.
    assert pb_sha is None
    contents = log.read_text()
    assert "plate-extract-empty" in contents
    assert f"convo={uuid_B}" in contents


def test_plate_push_does_not_log_when_extract_tree_differs_from_parent(
    tmp_path: Path, monkeypatch,
) -> None:
    # Scenario: when extraction promotes real changes (extract_tree != parent_tree),
    # the diagnostic must NOT fire. This avoids false positives in the log.
    log = tmp_path / "log.txt"
    monkeypatch.setenv("PLATE_LOG_FILE", str(log))
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", QUIET_OUTPUT, CREATE_BRANCH_AND_CHECKOUT_FLAG, "main"], cwd=repo)
    run(["git", "config", "user.email", "t@t.t"], cwd=repo)
    run(["git", "config", "user.name", "t"], cwd=repo)
    git_writeGitignore(repo)
    git_addFile(repo, ".gitignore")
    (repo / "a.txt").write_text("base\n")
    git_addFile(repo, "a.txt")
    git_createCommit(repo, "initial")

    uuid_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    transcript_A = tmp_path / f"{uuid_A}.jsonl"
    _plate_writeFakeTranscriptWithToolUse(
        transcript_A,
        [{"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
          "input": {"file_path": str(repo / "a.txt")}}],
    )
    (repo / "a.txt").write_text("base\nA1\n")
    plate_push(repo, convo_id=uuid_A, transcript_path=str(transcript_A))

    uuid_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    transcript_B = tmp_path / f"{uuid_B}.jsonl"
    _plate_writeFakeTranscriptWithToolUse(
        transcript_B,
        [{"timestamp": "2099-01-01T00:02:00.000Z", "tool": "Write",
          "input": {"file_path": str(repo / "b.txt")}}],
    )
    (repo / "b.txt").write_text("B")

    # Test action.
    pb_sha = plate_push(repo, convo_id=uuid_B, transcript_path=str(transcript_B))
    # Test verification: real commit happened, log file has no diagnostic line.
    assert pb_sha is not None
    if log.exists():
        assert "plate-extract-empty" not in log.read_text()
