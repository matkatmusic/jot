"""Tests for common/scripts/platform_lib.py.

Uses monkeypatch to stub subprocess, shutil.which, and platform.system
so the suite runs on any host without invoking osascript or Terminal.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import platform_lib
from platform_lib import (
    _appendAdvisory,
    _ADVISORY_NO_OSASCRIPT,
    _ADVISORY_NON_DARWIN,
    _buildOsascript,
    _clientsAttached,
    spawnTerminalIfNeeded,
)


def _fake_completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


# ── _clientsAttached ──────────────────────────────────────────────────


def test_clientsAttached_true_when_stdout_nonempty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _fake_completed(0, stdout="/dev/ttys001 ...\n"),
    )
    assert _clientsAttached("any") is True


def test_clientsAttached_false_when_stdout_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _fake_completed(0, stdout=""))
    assert _clientsAttached("any") is False


def test_clientsAttached_false_when_tmux_nonzero(monkeypatch: pytest.MonkeyPatch):
    # tmux returns 1 when the session does not exist.
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _fake_completed(1, stdout=""))
    assert _clientsAttached("missing") is False


# ── _buildOsascript ───────────────────────────────────────────────────


def test_buildOsascript_contains_both_terminal_branches():
    script = _buildOsascript("jot", maximize=False)
    assert 'if application "Terminal" is running then' in script
    assert "else" in script
    assert 'do script "tmux attach -t jot"' in script
    assert "in window 1" in script


def test_buildOsascript_no_maximize_block_by_default():
    script = _buildOsascript("jot", maximize=False)
    assert "Finder" not in script
    assert "screenBounds" not in script


def test_buildOsascript_includes_maximize_block_when_requested():
    script = _buildOsascript("jot", maximize=True)
    assert 'tell application "Finder"' in script
    assert "set screenBounds to bounds of window of desktop" in script
    assert "set bounds of front window to screenBounds" in script


def test_buildOsascript_session_is_substituted():
    script = _buildOsascript("my-session-42", maximize=False)
    assert "tmux attach -t my-session-42" in script


# ── _appendAdvisory ───────────────────────────────────────────────────


def test_appendAdvisory_writes_one_line(tmp_path: Path):
    log = tmp_path / "p.log"
    _appendAdvisory(log, "testlog", "fake", _ADVISORY_NO_OSASCRIPT)
    contents = log.read_text()
    assert contents.count("\n") == 1
    assert "testlog" in contents
    assert "fake" in contents
    assert "tmux attach -t fake" in contents
    assert "osascript unavailable" in contents


def test_appendAdvisory_swallows_unwritable_path(tmp_path: Path):
    # Pointing at a directory (not a file) makes open(..., "a") raise.
    _appendAdvisory(tmp_path, "p", "s", _ADVISORY_NON_DARWIN)
    # No exception = success.


def test_appendAdvisory_appends_to_existing(tmp_path: Path):
    log = tmp_path / "p.log"
    log.write_text("prior\n")
    _appendAdvisory(log, "p", "s", _ADVISORY_NON_DARWIN)
    lines = log.read_text().splitlines()
    assert lines[0] == "prior"
    assert "non-Darwin host" in lines[1]


# ── spawnTerminalIfNeeded: branching ──────────────────────────────────


def test_spawn_early_returns_when_clients_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(platform_lib, "_clientsAttached", lambda s: True)
    popen_mock = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen_mock)
    log = tmp_path / "p.log"
    spawnTerminalIfNeeded("s", log_file=log, log_prefix="p")
    assert popen_mock.call_count == 0
    assert not log.exists()


def test_spawn_on_darwin_with_osascript_invokes_popen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(platform_lib, "_clientsAttached", lambda s: False)
    monkeypatch.setattr(platform_lib._platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform_lib.shutil, "which", lambda c: "/usr/bin/osascript")
    captured: dict = {}
    class FakeProc:
        def __init__(self, *a, **kw):
            captured["argv"] = a[0]
            captured["kw"] = kw
            self.stdin = MagicMock()
        def __getattr__(self, _):
            return MagicMock()
    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    spawnTerminalIfNeeded("jot", log_file=tmp_path / "p.log", maximize=False)
    assert captured["argv"][0] == "osascript"
    assert captured["kw"]["start_new_session"] is True


def test_spawn_on_darwin_missing_osascript_writes_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(platform_lib, "_clientsAttached", lambda s: False)
    monkeypatch.setattr(platform_lib._platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform_lib.shutil, "which", lambda c: None)
    popen_mock = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen_mock)
    log = tmp_path / "p.log"
    spawnTerminalIfNeeded("jot", log_file=log, log_prefix="testlog")
    assert popen_mock.call_count == 0
    contents = log.read_text()
    assert "osascript unavailable" in contents
    assert "tmux attach -t jot" in contents
    assert "testlog" in contents


def test_spawn_on_non_darwin_writes_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(platform_lib, "_clientsAttached", lambda s: False)
    monkeypatch.setattr(platform_lib._platform, "system", lambda: "Linux")
    popen_mock = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen_mock)
    log = tmp_path / "p.log"
    spawnTerminalIfNeeded("jot", log_file=log, log_prefix="testlog")
    assert popen_mock.call_count == 0
    contents = log.read_text()
    assert "non-Darwin host" in contents
    assert "tmux attach -t jot" in contents
    assert "testlog" in contents


def test_spawn_empty_session_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    popen_mock = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen_mock)
    log = tmp_path / "p.log"
    spawnTerminalIfNeeded("", log_file=log)
    assert popen_mock.call_count == 0
    assert not log.exists()


def test_spawn_maximize_passed_through_to_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(platform_lib, "_clientsAttached", lambda s: False)
    monkeypatch.setattr(platform_lib._platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform_lib.shutil, "which", lambda c: "/usr/bin/osascript")
    captured: dict = {}
    class FakeProc:
        def __init__(self, *a, **kw):
            self._stdin_data = b""
            class Stdin:
                def write(s, data):
                    captured["script"] = data.decode()
                def close(s):
                    pass
            self.stdin = Stdin()
    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    spawnTerminalIfNeeded("s", log_file=tmp_path / "p.log", maximize=True)
    assert "Finder" in captured["script"]
    assert "screenBounds" in captured["script"]
