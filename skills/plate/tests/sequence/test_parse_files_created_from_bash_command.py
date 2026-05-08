"""Unit tests for `_plate_parseFilesCreatedFromBashCommand`.

Each test exercises one Bash redirect/creation form. Mirror of the source
parser at `_plate_parseRmTargets` so /plate's push step can capture
files authored via Bash (no `Edit`/`Write` tool_use record).
"""
from __future__ import annotations

from pathlib import Path

from plate_lib import _plate_parseFilesCreatedFromBashCommand


def _resolved(tmp_path: Path) -> Path:
    # Setup: every parser call needs a resolved repo root to anchor relative paths.
    return tmp_path.resolve()


def test_parses_single_redirect(tmp_path: Path) -> None:
    # Scenario: `cmd > path` writes a single output file.
    repo_root = _resolved(tmp_path)
    # Test action: parse a literal `printf 'x' > newfile.txt`.
    result = _plate_parseFilesCreatedFromBashCommand(
        "printf 'x' > newfile.txt", repo_root,
    )
    # Test verification: parser returns the single redirect target as a repo-relative path.
    assert result == {"newfile.txt"}


def test_parses_append_redirect(tmp_path: Path) -> None:
    # Scenario: `cmd >> path` appends to an output file; same capture rules as `>`.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "echo line >> log.txt", repo_root,
    )
    assert result == {"log.txt"}


def test_parses_tee_destination(tmp_path: Path) -> None:
    # Scenario: `... | tee path` writes the pipeline output to `path`.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "echo hello | tee out.txt", repo_root,
    )
    assert "out.txt" in result


def test_parses_tee_append(tmp_path: Path) -> None:
    # Scenario: `tee -a path` appends; the `-a` flag must be skipped, not captured.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "echo hello | tee -a out.txt", repo_root,
    )
    assert result == {"out.txt"}


def test_parses_touch(tmp_path: Path) -> None:
    # Scenario: `touch a b` creates multiple empty files; both must be captured.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "touch a.txt b.txt", repo_root,
    )
    assert result == {"a.txt", "b.txt"}


def test_parses_cp_destination(tmp_path: Path) -> None:
    # Scenario: `cp src dst` only the destination is "created"; src is read.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "cp src.txt dst.txt", repo_root,
    )
    assert result == {"dst.txt"}


def test_parses_mv_destination(tmp_path: Path) -> None:
    # Scenario: `mv src dst` likewise only captures the destination.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "mv old.txt new.txt", repo_root,
    )
    assert result == {"new.txt"}


def test_parses_git_add_arguments(tmp_path: Path) -> None:
    # Scenario: `git add a b` is explicit user staging; treat each pathspec as authored.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "git add a.txt b.txt", repo_root,
    )
    assert result == {"a.txt", "b.txt"}


def test_skips_shell_expansion_globs(tmp_path: Path) -> None:
    # Scenario: tokens with shell-expansion chars must be skipped to avoid spurious adds.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "touch *.tmp", repo_root,
    )
    # Test verification: nothing captured because `*.tmp` is not a literal path.
    assert result == set()


def test_skips_command_substitution(tmp_path: Path) -> None:
    # Scenario: `$(...)` and backticks are also expansion forms; must not be captured.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "touch $(date +%F).txt", repo_root,
    )
    assert result == set()


def test_skips_paths_outside_repo(tmp_path: Path) -> None:
    # Scenario: an absolute path that resolves outside the repo root must be dropped.
    repo_root = _resolved(tmp_path)
    result = _plate_parseFilesCreatedFromBashCommand(
        "touch /tmp/elsewhere.txt", repo_root,
    )
    assert result == set()
