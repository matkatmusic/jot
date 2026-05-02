"""Parity tests for common/scripts/permissions_seed_cli.py and the
permissions-seed.sh bash shim.

CLI tests run permissions_seed_cli.py directly via sys.executable
(no PATH resolution needed). Shim tests source the bash file and
invoke `permissions_seed`, which forks `python3 ..._cli.py`; that
fork resolves python3 via PATH, so the shim env preserves the real
PATH (pyenv-aware) per observation 3434/3437 (test_platform_cli.py).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PERM_CLI = REPO_ROOT / "common" / "scripts" / "permissions_seed_cli.py"
PERM_SH = REPO_ROOT / "common" / "scripts" / "permissions-seed.sh"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def cli_env_default() -> dict[str, str]:
    """Default env for direct python3 _cli.py invocations."""
    return {"PATH": "/usr/bin:/bin"}


@pytest.fixture
def shim_env() -> dict[str, str]:
    """Env for bash-shim tests: preserves PATH so `python3` resolves
    even when pyenv shims are in use (observation 3434)."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def py(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PERM_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def sh(snippet: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'source "{PERM_SH}"; {snippet}'],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _seed_files(tmp_path: Path, default_contents: bytes = b"v1\n") -> dict[str, Path]:
    default = tmp_path / "default.json"
    default.write_bytes(default_contents)
    sha_file = tmp_path / "default.sha"
    sha_file.write_text(_sha256(default) + "\n")
    return {
        "installed": tmp_path / "installed.json",
        "default": default,
        "default_sha_file": sha_file,
        "prior_sha_file": tmp_path / "prior.sha",
        "log_file": tmp_path / "seed.log",
    }


def _seed_argv(f: dict[str, Path], log: bool = True) -> list[str]:
    argv = [
        "seed",
        str(f["installed"]),
        str(f["default"]),
        str(f["default_sha_file"]),
        str(f["prior_sha_file"]),
        "--log-prefix", "testlog",
    ]
    if log:
        argv += ["--log-file", str(f["log_file"])]
    return argv


# ── CLI subprocess tests, one per spec branch ─────────────────────────


def test_cli_branch1_missing_default(tmp_path: Path, cli_env_default: dict[str, str]):
    f = _seed_files(tmp_path)
    f["default"].unlink()
    out = py(*_seed_argv(f), env=cli_env_default)
    assert out.returncode == 0
    assert not f["installed"].exists()
    assert "missing" in f["log_file"].read_text()


def test_cli_branch2_first_install(tmp_path: Path, cli_env_default: dict[str, str]):
    f = _seed_files(tmp_path, default_contents=b"first-payload\n")
    out = py(*_seed_argv(f), env=cli_env_default)
    assert out.returncode == 0
    assert f["installed"].read_bytes() == f["default"].read_bytes()
    assert f["prior_sha_file"].read_text().strip() == _sha256(f["default"])
    assert "seeded" in f["log_file"].read_text()


def test_cli_branch3_unchanged_install(tmp_path: Path, cli_env_default: dict[str, str]):
    f = _seed_files(tmp_path)
    f["installed"].write_bytes(f["default"].read_bytes())
    f["prior_sha_file"].write_text(_sha256(f["default"]) + "\n")
    out = py(*_seed_argv(f), env=cli_env_default)
    assert out.returncode == 0
    # No log line; either log file absent or empty.
    log_text = f["log_file"].read_text() if f["log_file"].exists() else ""
    assert log_text == ""


def test_cli_branch4_upgrade_when_untouched(
    tmp_path: Path, cli_env_default: dict[str, str]
):
    old_payload = b"old\n"
    new_payload = b"new\n"
    f = _seed_files(tmp_path, default_contents=old_payload)
    f["installed"].write_bytes(old_payload)
    f["prior_sha_file"].write_text(_sha256(f["default"]) + "\n")
    f["default"].write_bytes(new_payload)
    f["default_sha_file"].write_text(_sha256(f["default"]) + "\n")
    new_sha = _sha256(f["default"])
    out = py(*_seed_argv(f), env=cli_env_default)
    assert out.returncode == 0
    assert f["installed"].read_bytes() == new_payload
    assert f["prior_sha_file"].read_text().strip() == new_sha
    assert "upgraded" in f["log_file"].read_text()


def test_cli_branch5_user_edited_preserved(
    tmp_path: Path, cli_env_default: dict[str, str]
):
    edited_payload = b"hand-edited\n"
    f = _seed_files(tmp_path, default_contents=b"old\n")
    f["prior_sha_file"].write_text(_sha256(f["default"]) + "\n")
    f["installed"].write_bytes(edited_payload)
    f["default"].write_bytes(b"new\n")
    f["default_sha_file"].write_text(_sha256(f["default"]) + "\n")
    new_sha = _sha256(f["default"])
    out = py(*_seed_argv(f), env=cli_env_default)
    assert out.returncode == 0
    assert f["installed"].read_bytes() == edited_payload
    assert f["prior_sha_file"].read_text().strip() == new_sha
    assert "user-edited" in f["log_file"].read_text()


def test_cli_branch6_log_omitted_no_failure(
    tmp_path: Path, cli_env_default: dict[str, str]
):
    f = _seed_files(tmp_path)
    out = py(*_seed_argv(f, log=False), env=cli_env_default)
    assert out.returncode == 0
    assert out.stdout == ""
    assert out.stderr == ""
    # Seed still happened.
    assert f["installed"].exists()


# ── bash-shim parity (branch 2: first install) ────────────────────────


def test_shim_branch2_first_install_via_bash(
    tmp_path: Path, shim_env: dict[str, str]
):
    f = _seed_files(tmp_path, default_contents=b"shim-payload\n")
    snippet = (
        f'permissions_seed '
        f'"{f["installed"]}" "{f["default"]}" '
        f'"{f["default_sha_file"]}" "{f["prior_sha_file"]}" '
        f'"{f["log_file"]}" "shimlog"'
    )
    out = sh(snippet, env=shim_env)
    assert out.returncode == 0, out.stderr
    assert f["installed"].read_bytes() == f["default"].read_bytes()
    assert f["prior_sha_file"].read_text().strip() == _sha256(f["default"])
    assert "seeded" in f["log_file"].read_text()
    assert "shimlog" in f["log_file"].read_text()
