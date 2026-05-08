from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from common.scripts.claude_lib import (
    claude_permseedLog,
    claude_seedPermissions,
)


_PERMSEED_ISO_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)")


def test_claude_permseedLog_no_op_when_log_file_is_none(tmp_path: Path) -> None:
    # Scenario: caller passes log_file=None; logging disabled.
    pre = sorted(tmp_path.iterdir())
    # Test action.
    claude_permseedLog("hello", None)
    # Test verification.
    assert sorted(tmp_path.iterdir()) == pre


def test_claude_permseedLog_no_op_when_log_file_is_empty_string(tmp_path: Path) -> None:
    # Scenario: empty string log_file means logging disabled.
    # Test action + verification.
    assert claude_permseedLog("hello", "") is None


def test_claude_permseedLog_writes_line_to_log_file(tmp_path: Path) -> None:
    # Scenario: normal call appends a line.
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("seeded ok", str(log_file), log_prefix="plugin")
    # Test verification.
    contents = log_file.read_text(encoding="utf-8")
    assert contents.endswith("plugin: seeded ok\n")
    assert contents.count("\n") == 1


def test_claude_permseedLog_default_log_prefix_is_plugin(tmp_path: Path) -> None:
    # Scenario: omitting log_prefix uses default "plugin".
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("msg", str(log_file))
    # Test verification.
    assert " plugin: msg\n" in log_file.read_text(encoding="utf-8")


def test_claude_permseedLog_custom_log_prefix_is_used(tmp_path: Path) -> None:
    # Scenario: caller-supplied prefix overrides default.
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("hi", str(log_file), log_prefix="permseed")
    # Test verification.
    contents = log_file.read_text(encoding="utf-8")
    assert " permseed: hi\n" in contents
    assert "plugin:" not in contents


def test_claude_permseedLog_line_starts_with_iso8601_timestamp(tmp_path: Path) -> None:
    # Scenario: log line is timestamped with ISO-8601 (matches bash date -Iseconds).
    log_file = tmp_path / "seed.log"
    # Test action.
    claude_permseedLog("x", str(log_file))
    # Test verification.
    line = log_file.read_text(encoding="utf-8").rstrip("\n")
    assert _PERMSEED_ISO_RE.match(line)


def test_claude_permseedLog_appends_rather_than_overwrites(tmp_path: Path) -> None:
    # Scenario: multiple calls accumulate lines (bash uses >>).
    log_file = tmp_path / "seed.log"
    claude_permseedLog("first", str(log_file))
    # Test action.
    claude_permseedLog("second", str(log_file))
    # Test verification.
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("plugin: first")
    assert lines[1].endswith("plugin: second")


def test_claude_permseedLog_swallows_write_errors_silently(tmp_path: Path) -> None:
    # Scenario: log_file under nonexistent dir; bash swallows via 2>/dev/null || true.
    bad = tmp_path / "missing" / "seed.log"
    # Test action + verification: must NOT raise, returns None.
    assert claude_permseedLog("msg", str(bad)) is None
    assert not bad.exists()


# --- claude_seedPermissions ---

@pytest.fixture
def permissions_workspace(tmp_path: Path):
    default = tmp_path / "default.json"
    installed = tmp_path / "installed.json"
    default_sha_file = tmp_path / "default.sha256"
    prior_sha_file = tmp_path / "prior.sha256"
    log_file = tmp_path / "seed.log"
    return {
        "default": default,
        "installed": installed,
        "default_sha_file": default_sha_file,
        "prior_sha_file": prior_sha_file,
        "log_file": log_file,
    }


def test_claude_seedPermissions_missing_default_file_logs_and_returns(permissions_workspace):
    # Scenario: bundled default file does not exist on disk.
    # Setup: only create the sha-file; leave default missing.
    permissions_workspace["default_sha_file"].write_text("deadbeef\n")
    # Test action: invoke with all required paths plus a log destination.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: nothing copied, no prior sha written, warning logged.
    assert not permissions_workspace["installed"].exists()
    assert not permissions_workspace["prior_sha_file"].exists()
    log_text = permissions_workspace["log_file"].read_text()
    assert "bundled permissions default missing" in log_text


def test_claude_seedPermissions_missing_default_sha_file_logs_and_returns(permissions_workspace):
    # Scenario: bundled default exists but its companion sha-file is missing.
    # Setup: write default contents only.
    permissions_workspace["default"].write_text("{}\n")
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: still no installed file; warning surfaced via log.
    assert not permissions_workspace["installed"].exists()
    assert "cannot seed" in permissions_workspace["log_file"].read_text()


def test_claude_seedPermissions_seeds_installed_when_missing(permissions_workspace):
    # Scenario: first run on a fresh machine - no installed file present.
    # Setup: create default + its sha-file with the real digest.
    payload = b'{"allow":["Read"]}\n'
    permissions_workspace["default"].write_bytes(payload)
    expected_sha = hashlib.sha256(payload).hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{expected_sha}  default.json\n")
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: installed copied from default; prior sha recorded.
    assert permissions_workspace["installed"].read_bytes() == payload
    assert permissions_workspace["prior_sha_file"].read_text().strip().split()[0] == expected_sha
    assert "seeded" in permissions_workspace["log_file"].read_text()


def test_claude_seedPermissions_no_op_when_installed_matches_default(permissions_workspace):
    # Scenario: installed file already byte-identical to bundled default.
    # Setup: create default; copy it to installed; record sha.
    payload = b"abc\n"
    permissions_workspace["default"].write_bytes(payload)
    permissions_workspace["installed"].write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{sha}\n")
    pre_mtime = permissions_workspace["installed"].stat().st_mtime_ns
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: file untouched, no log line emitted, no prior file written.
    assert permissions_workspace["installed"].stat().st_mtime_ns == pre_mtime
    assert not permissions_workspace["log_file"].exists() or permissions_workspace["log_file"].read_text() == ""
    assert not permissions_workspace["prior_sha_file"].exists()


def test_claude_seedPermissions_upgrades_unmodified_installed_to_new_default(permissions_workspace):
    # Scenario: bundled default has been bumped; user has not touched installed.
    # Setup: installed equals prior_sha contents; default differs.
    old = b"v1\n"
    new = b"v2-newer\n"
    permissions_workspace["installed"].write_bytes(old)
    permissions_workspace["default"].write_bytes(new)
    old_sha = hashlib.sha256(old).hexdigest()
    new_sha = hashlib.sha256(new).hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{new_sha}\n")
    permissions_workspace["prior_sha_file"].write_text(f"{old_sha}\n")
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: installed now matches new default; prior_sha advanced; logged.
    assert permissions_workspace["installed"].read_bytes() == new
    assert permissions_workspace["prior_sha_file"].read_text().strip() == new_sha
    assert "upgraded" in permissions_workspace["log_file"].read_text()


def test_claude_seedPermissions_user_edited_installed_is_preserved_and_logged(permissions_workspace):
    # Scenario: user has hand-edited installed; bundled default also moved on.
    # Setup: three distinct shas: installed, prior, default.
    permissions_workspace["installed"].write_bytes(b"user-tweaks\n")
    permissions_workspace["default"].write_bytes(b"new-default\n")
    new_sha = hashlib.sha256(b"new-default\n").hexdigest()
    prior_sha_value = hashlib.sha256(b"original\n").hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{new_sha}\n")
    permissions_workspace["prior_sha_file"].write_text(f"{prior_sha_value}\n")
    pre_installed = permissions_workspace["installed"].read_bytes()
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: installed bytes unchanged; prior_sha refreshed to new; log explains user-edited situation.
    assert permissions_workspace["installed"].read_bytes() == pre_installed
    assert permissions_workspace["prior_sha_file"].read_text().strip() == new_sha
    log_text = permissions_workspace["log_file"].read_text()
    assert "user-edited" in log_text
    assert "diff manually" in log_text


def test_claude_seedPermissions_user_edited_no_default_change_does_not_rewrite_prior(permissions_workspace):
    # Scenario: installed is user-edited but the bundled default is unchanged since prior_sha was recorded.
    # Setup: prior_sha == current_default_sha; installed differs from both.
    permissions_workspace["installed"].write_bytes(b"hand-edited\n")
    permissions_workspace["default"].write_bytes(b"def\n")
    def_sha = hashlib.sha256(b"def\n").hexdigest()
    permissions_workspace["default_sha_file"].write_text(f"{def_sha}\n")
    permissions_workspace["prior_sha_file"].write_text(f"{def_sha}\n")
    pre_prior_mtime = permissions_workspace["prior_sha_file"].stat().st_mtime_ns
    # Test action.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: prior_sha_file untouched; installed untouched; no log.
    assert permissions_workspace["prior_sha_file"].stat().st_mtime_ns == pre_prior_mtime
    assert permissions_workspace["installed"].read_bytes() == b"hand-edited\n"
    assert not permissions_workspace["log_file"].exists() or permissions_workspace["log_file"].read_text() == ""


def test_claude_seedPermissions_log_file_none_suppresses_logging(permissions_workspace):
    # Scenario: caller opts out of logging by passing log_file=None.
    # Test action: trigger the missing-default branch which would otherwise log.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=None,
    )
    # Test verification: no log file materialized anywhere in the workspace.
    assert not permissions_workspace["log_file"].exists()


def test_claude_seedPermissions_default_sha_file_with_two_column_format_is_parsed(permissions_workspace):
    # Scenario: default_sha_file uses `shasum`-style "<sha>  <filename>" layout.
    # Setup: write two-column sha line; ensure only the hash is consumed.
    payload = b"x\n"
    sha = hashlib.sha256(payload).hexdigest()
    permissions_workspace["default"].write_bytes(payload)
    permissions_workspace["default_sha_file"].write_text(f"{sha}  default.json\n")
    # Test action: install missing path exercises the parser.
    claude_seedPermissions(
        installed=str(permissions_workspace["installed"]),
        default=str(permissions_workspace["default"]),
        default_sha_file=str(permissions_workspace["default_sha_file"]),
        prior_sha_file=str(permissions_workspace["prior_sha_file"]),
        log_file=str(permissions_workspace["log_file"]),
    )
    # Test verification: prior_sha file holds only the hash, no filename token.
    assert permissions_workspace["prior_sha_file"].read_text().strip() == sha
