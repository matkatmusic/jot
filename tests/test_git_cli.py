"""Parity tests for common/scripts/git_cli.py.

Each test asserts the subcommand's stdout, stderr, and exit code match
the historic git.sh contract — and exercises both the python entry
point (subprocess) and the bash shim (sourcing git.sh) so caller
behavior is verified end-to-end.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from git_lib import (
    USER_EMAIL_KEY,
    USER_EMAIL_VALUE,
    USER_NAME_KEY,
    USER_NAME_VALUE,
    run,
    setGitUserConfigValue,
)
from plate_lib import (
    TEST_FILENAME,
    makeEmptyRepo,
    makeTestRepoWithSingleCommit,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT_CLI = REPO_ROOT / "common" / "scripts" / "git_cli.py"
GIT_SH = REPO_ROOT / "common" / "scripts" / "git.sh"


def py(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke git_cli.py with given args; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(GIT_CLI), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def sh(fn_call: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Source git.sh and run a single function call inside bash."""
    return subprocess.run(
        ["bash", "-c", f'source "{GIT_SH}"; {fn_call}'],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


# ── is-repo ───────────────────────────────────────────────────────────


def test_is_repo_true(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    assert py("is-repo", str(repo)).returncode == 0
    assert sh(f'git_is_repo "{repo}"').returncode == 0


def test_is_repo_false(tmp_path: Path):
    assert py("is-repo", str(tmp_path)).returncode == 1
    assert sh(f'git_is_repo "{tmp_path}"').returncode == 1


# ── repo-root ─────────────────────────────────────────────────────────


def test_repo_root_returns_root(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    out = py("repo-root", str(repo))
    assert out.returncode == 0
    assert out.stdout.strip() == str(repo)


def test_repo_root_from_subdirectory(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    sub = repo / "sub"
    sub.mkdir()
    out = py("repo-root", str(sub))
    assert out.returncode == 0
    assert out.stdout.strip() == str(repo)


def test_repo_root_fails_outside_repo(tmp_path: Path):
    out = py("repo-root", str(tmp_path))
    assert out.returncode == 1
    assert "[git] not inside a git repository" in out.stderr


# ── branch-name ───────────────────────────────────────────────────────


def test_branch_name_returns_branch(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    out = py("branch-name", str(repo))
    assert out.returncode == 0
    assert out.stdout.strip() == "main"


def test_branch_name_fails_outside_repo(tmp_path: Path):
    out = py("branch-name", str(tmp_path))
    assert out.returncode == 1
    assert "not a git repository" in out.stderr


def test_branch_name_fails_on_detached_head(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    run(["git", "checkout", "--detach"], cwd=repo)
    out = py("branch-name", str(repo))
    assert out.returncode == 1
    assert "HEAD detached at" in out.stderr


# ── recent-commits ────────────────────────────────────────────────────


def test_recent_commits_prints_space_separated_hashes(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    for i in range(3):
        run(["git", "commit", "--allow-empty", "-m", f"c{i}"], cwd=repo)
    out = py("recent-commits", str(repo))
    assert out.returncode == 0
    hashes = out.stdout.strip().split()
    assert len(hashes) == 4
    assert all(len(h) >= 7 for h in hashes)


def test_recent_commits_fails_outside_repo(tmp_path: Path):
    out = py("recent-commits", str(tmp_path))
    assert out.returncode == 1
    assert "not a git repository" in out.stderr


def test_recent_commits_fails_on_empty_repo(tmp_path: Path):
    repo = makeEmptyRepo(path=tmp_path)
    setGitUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    setGitUserConfigValue(repo, USER_NAME_KEY, USER_NAME_VALUE)
    out = py("recent-commits", str(repo))
    assert out.returncode == 1
    assert "No commits yet" in out.stderr


# ── uncommitted ───────────────────────────────────────────────────────


def test_uncommitted_clean_repo_prints_None(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    out = py("uncommitted", str(repo))
    assert out.returncode == 0
    assert out.stdout.strip() == "None"


def test_uncommitted_lists_modified_file(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    (repo / TEST_FILENAME).write_text("modified\n")
    out = py("uncommitted", str(repo))
    assert out.returncode == 0
    assert TEST_FILENAME in out.stdout.split()


def test_uncommitted_fails_outside_repo(tmp_path: Path):
    out = py("uncommitted", str(tmp_path))
    assert out.returncode == 1
    assert "not a git repository" in out.stderr


# ── ensure-gitignore-entry ────────────────────────────────────────────


def test_ensure_gitignore_entry_creates_file(tmp_path: Path):
    out = py("ensure-gitignore-entry", str(tmp_path), ".plate/")
    assert out.returncode == 0
    assert ".plate/" in (tmp_path / ".gitignore").read_text().splitlines()


def test_ensure_gitignore_entry_is_idempotent(tmp_path: Path):
    for _ in range(3):
        assert py(
            "ensure-gitignore-entry", str(tmp_path), ".plate/"
        ).returncode == 0
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    assert lines.count(".plate/") == 1


# ── bash shim parity (covers a representative subset) ─────────────────


def test_shim_get_repo_root_matches_python(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    py_out = py("repo-root", str(repo))
    sh_out = sh(f'git_get_repo_root "{repo}"')
    assert sh_out.returncode == py_out.returncode == 0
    assert sh_out.stdout.strip() == py_out.stdout.strip() == str(repo)


def test_shim_get_branch_name_matches_python(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    sh_out = sh(f'git_get_branch_name "{repo}"')
    assert sh_out.returncode == 0
    assert sh_out.stdout.strip() == "main"


def test_shim_get_uncommitted_clean_returns_None(tmp_path: Path):
    repo = makeTestRepoWithSingleCommit(tmp_path)
    sh_out = sh(f'git_get_uncommitted "{repo}"')
    assert sh_out.returncode == 0
    assert sh_out.stdout.strip() == "None"


def test_shim_ensure_gitignore_entry_appends(tmp_path: Path):
    sh_out = sh(f'git_ensure_gitignore_entry "{tmp_path}" ".plate/"')
    assert sh_out.returncode == 0
    assert ".plate/" in (tmp_path / ".gitignore").read_text().splitlines()
