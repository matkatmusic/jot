from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from common.scripts import jot_lib
from common.scripts import tmux_lib
from common.scripts import util_lib


# Replaces tests/test_util_terminal.py::test_terminal_spawnIfNeeded_skips_spawn_when_clients_attached
def test_terminal_listTmuxClients_returns_stdout_when_tmux_command_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: tmux list-clients succeeds for a session.
    # Setup: replace subprocess.run with a fake completed process.
    captured_argv: list[str] = []

    def fakeRun(argv, **_kwargs):
        captured_argv.extend(argv)
        return SimpleNamespace(returncode=0, stdout="/dev/ttys001\n")

    monkeypatch.setattr(util_lib.subprocess, "run", fakeRun)

    # Test action: list clients for one session.
    result = util_lib._terminal_listTmuxClients("jot")

    # Test verification: stdout is returned and tmux received the session.
    assert result == "/dev/ttys001\n"
    assert captured_argv == ["tmux", "list-clients", "-t", "jot"]


def test_terminal_listTmuxClients_returns_empty_string_when_tmux_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: tmux list-clients returns a nonzero status.
    # Setup: fake a failed tmux command.
    monkeypatch.setattr(
        util_lib.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="error\n"),
    )

    # Test action: list clients for one session.
    result = util_lib._terminal_listTmuxClients("jot")

    # Test verification: failures are hidden as an empty string.
    assert result == ""


def test_terminal_listTmuxClients_returns_empty_string_when_tmux_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: tmux is missing or cannot be executed.
    # Setup: make subprocess.run raise FileNotFoundError.
    monkeypatch.setattr(
        util_lib.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("tmux")),
    )

    # Test action: list clients for one session.
    result = util_lib._terminal_listTmuxClients("jot")

    # Test verification: missing tmux is hidden as an empty string.
    assert result == ""


def test_terminal_appendAdvisory_skips_dev_null_log(tmp_path: Path) -> None:
    # Scenario: a caller passes /dev/null as the advisory log path.
    # Setup: record the files in tmp_path so accidental writes are visible.
    before = set(tmp_path.iterdir())

    # Test action: append the Darwin advisory to /dev/null.
    util_lib._terminal_appendAdvisory("/dev/null", "jot", "jot")

    # Test verification: no file was created in the working tmp directory.
    assert set(tmp_path.iterdir()) == before


def test_terminal_appendAdvisory_swallows_write_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: writing the Darwin advisory raises OSError.
    # Setup: patch open so every write attempt fails.
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: (_ for _ in ()).throw(OSError("EACCES")))

    # Test action and verification: the helper returns without raising.
    assert util_lib._terminal_appendAdvisory("/tmp/blocked.log", "jot", "jot") is None


def test_terminal_spawnIfNeeded_returns_zero_when_darwin_popen_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: osascript exists on Darwin, but spawning it raises OSError.
    # Setup: no tmux clients are attached and Popen fails.
    monkeypatch.setattr(util_lib, "_terminal_listTmuxClients", lambda _session: "")
    monkeypatch.setattr(util_lib.sys, "platform", "darwin")
    monkeypatch.setattr(util_lib.shutil, "which", lambda _cmd: "/usr/bin/osascript")
    monkeypatch.setattr(
        util_lib.subprocess,
        "Popen",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("spawn failed")),
    )

    # Test action: ask the helper to spawn a terminal.
    result = util_lib.terminal_spawnIfNeeded("jot")

    # Test verification: spawn failures are swallowed and reported as success.
    assert result == 0


def test_util_tail_lines_returns_last_requested_lines(tmp_path: Path) -> None:
    # Scenario: a diagnostic log has more lines than the caller wants.
    # Setup: write five numbered lines.
    log_file = tmp_path / "audit.log"
    log_file.write_text("1\n2\n3\n4\n5\n", encoding="utf-8")

    # Test action: ask for the last two lines.
    result = util_lib._util_tail_lines(log_file, 2)

    # Test verification: only the tail is returned.
    assert result == "4\n5\n"


def test_util_tail_lines_returns_empty_string_when_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: a diagnostic log exists but cannot be read.
    # Setup: force Path.read_text to raise OSError.
    log_file = tmp_path / "audit.log"
    log_file.write_text("content\n", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(OSError("read")))

    # Test action: ask for log tail lines.
    result = util_lib._util_tail_lines(log_file, 2)

    # Test verification: unreadable logs produce an empty diagnostic section.
    assert result == ""


def test_jot_collectDiagnostics_reports_audit_and_log_tails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the diagnostic report should include only the audit/log tails.
    # Setup: create state audit with 35 lines and jot log with 25 lines.
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "Todos" / ".jot-state"
    state_dir.mkdir(parents=True)
    (state_dir / "audit.log").write_text("".join(f"a{i}\n" for i in range(35)), encoding="utf-8")
    jot_log = tmp_path / "jot.log"
    jot_log.write_text("".join(f"l{i}\n" for i in range(25)), encoding="utf-8")
    monkeypatch.setenv("JOT_LOG_FILE", str(jot_log))

    # Test action: collect diagnostics.
    out_path = jot_lib.jot_collectDiagnostics(str(tmp_path / "diag.log"))
    report = Path(out_path).read_text()

    # Test verification: old lines are trimmed and tail lines remain.
    assert "a0\n" not in report
    assert "a5\n" in report
    assert "l0\n" not in report
    assert "l5\n" in report


def test_tmux_run_returns_missing_message_when_tmux_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: diagnostics call tmux, but the binary is unavailable.
    # Setup: make subprocess.run raise FileNotFoundError.
    monkeypatch.setattr(
        tmux_lib.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("tmux")),
    )

    # Test action: run a tmux diagnostic command.
    result = tmux_lib._tmux_run("list-sessions")

    # Test verification: the diagnostic helper returns a user-facing marker.
    assert result == "(tmux not found)"


def test_tmux_session_exists_returns_false_when_tmux_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: diagnostics ask whether the jot session exists, but tmux is
    # unavailable.
    # Setup: make subprocess.run raise FileNotFoundError.
    monkeypatch.setattr(
        tmux_lib.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("tmux")),
    )

    # Test action: check for the jot session.
    result = tmux_lib._tmux_session_exists("jot")

    # Test verification: missing tmux means the session does not exist.
    assert result is False
