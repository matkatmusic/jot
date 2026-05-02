"""Tests for common/scripts/permissions_seed_lib.py.

Each test exercises one branch of the three-state seeder spec from
common/scripts/permissions-seed.sh and is designed to fail loudly
if that branch's behavior breaks.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from permissions_seed_lib import permissionsSeed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_files(tmp_path: Path, default_contents: bytes = b"v1\n") -> dict[str, Path]:
    """Create a minimal valid set of seed files; tests mutate from there."""
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


# ── branch 1: bundled default missing ─────────────────────────────────


def test_branch1_missing_default_returns_without_copy(tmp_path: Path):
    f = _seed_files(tmp_path)
    f["default"].unlink()
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=f["log_file"],
        log_prefix="testlog",
    )
    assert not f["installed"].exists()
    assert "missing" in f["log_file"].read_text()


def test_branch1_missing_sha_file_returns_without_copy(tmp_path: Path):
    f = _seed_files(tmp_path)
    f["default_sha_file"].unlink()
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=f["log_file"],
        log_prefix="testlog",
    )
    assert not f["installed"].exists()
    assert "missing" in f["log_file"].read_text()


# ── branch 2: first install ───────────────────────────────────────────


def test_branch2_first_install_copies_and_records_sha(tmp_path: Path):
    f = _seed_files(tmp_path, default_contents=b"first-install-payload\n")
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=f["log_file"],
        log_prefix="testlog",
    )
    assert f["installed"].read_bytes() == f["default"].read_bytes()
    assert f["prior_sha_file"].read_text().strip() == _sha256(f["default"])
    assert "seeded" in f["log_file"].read_text()


# ── branch 3: installed already matches current default ───────────────


def test_branch3_unchanged_install_is_noop(tmp_path: Path):
    f = _seed_files(tmp_path, default_contents=b"steady-state\n")
    # Pre-seed: installed == default; prior_sha file already records it.
    f["installed"].write_bytes(f["default"].read_bytes())
    f["prior_sha_file"].write_text(_sha256(f["default"]) + "\n")
    installed_mtime_before = f["installed"].stat().st_mtime_ns
    prior_before = f["prior_sha_file"].read_text()
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=f["log_file"],
        log_prefix="testlog",
    )
    assert f["installed"].stat().st_mtime_ns == installed_mtime_before
    assert f["prior_sha_file"].read_text() == prior_before
    # Branch 3 must not log anything.
    assert not f["log_file"].exists() or f["log_file"].read_text() == ""


# ── branch 4: untouched install upgrades to new bundled default ───────


def test_branch4_upgrade_when_user_never_edited(tmp_path: Path):
    # Old default == old installed; ship a new default + new sha.
    old_payload = b"old\n"
    new_payload = b"new-default-payload\n"
    f = _seed_files(tmp_path, default_contents=old_payload)
    f["installed"].write_bytes(old_payload)
    f["prior_sha_file"].write_text(_sha256(f["default"]) + "\n")  # old sha
    # Now ship the new default.
    f["default"].write_bytes(new_payload)
    f["default_sha_file"].write_text(_sha256(f["default"]) + "\n")
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=f["log_file"],
        log_prefix="testlog",
    )
    assert f["installed"].read_bytes() == new_payload
    assert f["prior_sha_file"].read_text().strip() == _sha256(f["default"])
    assert "upgraded" in f["log_file"].read_text()


# ── branch 5: user-edited installed is preserved ──────────────────────


def test_branch5_user_edited_install_preserved(tmp_path: Path):
    old_payload = b"old\n"
    edited_payload = b"hand-edited-by-user\n"
    new_payload = b"new-default\n"
    f = _seed_files(tmp_path, default_contents=old_payload)
    # Record prior_sha matching old default; then user edits installed.
    f["prior_sha_file"].write_text(_sha256(f["default"]) + "\n")
    f["installed"].write_bytes(edited_payload)
    # Now ship a new default.
    f["default"].write_bytes(new_payload)
    f["default_sha_file"].write_text(_sha256(f["default"]) + "\n")
    new_sha = _sha256(f["default"])
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=f["log_file"],
        log_prefix="testlog",
    )
    # User edits MUST be preserved.
    assert f["installed"].read_bytes() == edited_payload
    # prior_sha advances to the current default sha (so next upgrade
    # cycle can re-detect the same edited state).
    assert f["prior_sha_file"].read_text().strip() == new_sha
    assert "user-edited" in f["log_file"].read_text()


# ── branch 6: logging is best-effort ──────────────────────────────────


def test_branch6_log_silenced_when_log_file_none(tmp_path: Path, capsys: pytest.CaptureFixture):
    f = _seed_files(tmp_path)
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=None,
        log_prefix="testlog",
    )
    # No exception, no stderr noise, and the seed still happened.
    captured = capsys.readouterr()
    assert captured.err == ""
    assert f["installed"].exists()


def test_branch6_log_silenced_when_log_file_unwritable(tmp_path: Path):
    f = _seed_files(tmp_path)
    # Path inside a non-existent directory => open(..., 'a') raises.
    unwritable = tmp_path / "no-such-dir" / "seed.log"
    permissionsSeed(
        installed=f["installed"],
        default=f["default"],
        default_sha_file=f["default_sha_file"],
        prior_sha_file=f["prior_sha_file"],
        log_file=unwritable,
        log_prefix="testlog",
    )
    # Function returns normally; the seed itself still succeeded.
    assert f["installed"].exists()
    assert f["installed"].read_bytes() == f["default"].read_bytes()
