"""Tests for todo_sessionEnd and todo_stop (stop bucket)."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from common.scripts import todo_lib as mod
from common.scripts.todo_lib import todo_sessionEnd, todo_stop


# --------- shared fixtures (used by test_safe_wrapper_falls_back_to_unavailable) ---------

@pytest.fixture
def base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    # Setup: minimal valid plugin env + scratch log.
    plugin_root = tmp_path / "plugin"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("JOT_LOG_FILE", str(tmp_path / "jot.log"))
    monkeypatch.delenv("JOT_SKIP_LAUNCH", raising=False)
    return {
        "plugin_root": str(plugin_root),
        "plugin_data": str(plugin_data),
        "tmp": str(tmp_path),
    }


def _stub_passing_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup: bypass real tool checks + tmux probe.
    monkeypatch.setattr("common.scripts.hookjson_lib.hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr("common.scripts.jot_lib.tmux_requireVersion", lambda _m: 0)


def _stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


# Bind a local alias for jot_main reference inside test_safe_wrapper_falls_back_to_unavailable.
from common.scripts import jot_lib as _jot_mod  # noqa: E402


def test_safe_wrapper_falls_back_to_unavailable(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: git_lib helpers raise; the input file should record "(unavailable)".
    # Setup: stub all git_lib funcs to raise; stub launch + render.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)

    def boom(*_: object) -> str:
        raise RuntimeError("nope")

    monkeypatch.setattr("common.scripts.jot_lib.getGitBranchNameOrFail", boom)
    monkeypatch.setattr("common.scripts.jot_lib.getGitRecentCommitHashes", boom)
    monkeypatch.setattr("common.scripts.jot_lib.getGitUncommittedFilenames", boom)
    monkeypatch.setattr("common.scripts.jot_lib.todo_scanOpen", boom)
    monkeypatch.setattr("common.scripts.jot_lib.jot_launchPhase2Window", lambda: 0)

    def fake_run(cmd, *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="INSTR", stderr="")

    monkeypatch.setattr(_jot_mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot recover", "cwd": str(repo)}))
    # Test action: invoke.
    rc = _jot_mod.jot_main()
    # Test verification: rc=0 + every safe-wrapped value rendered as "(unavailable)".
    assert rc == 0
    files = list((repo / "Todos").glob("*_input.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "Branch: (unavailable)" in text
    assert "Commits: (unavailable)" in text
    assert "Uncommitted: (unavailable)" in text
    assert "## Open TODO Files\n(unavailable)" in text


def test_empty_string_is_rejected(monkeypatch, capsys):
    # Scenario: empty string has no valid prefix; must be rejected
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("")

    # Test verification:
    assert calls == []
    err = capsys.readouterr().err
    assert "[todo-session-end] refusing to rm unexpected path:" in err


def test_nonexistent_valid_path_is_silently_ignored(monkeypatch, capsys):
    # Scenario: valid prefix but path does not exist; ignore_errors=True swallows it
    # Setup: rmtree with ignore_errors=True must not raise on missing path
    deleted: list[str] = []

    def fake_rmtree(path, ignore_errors=False):
        # Simulate real rmtree behaviour: no-op when ignore_errors=True
        assert ignore_errors is True
        deleted.append(path)

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    # Test action: path looks valid but does not exist on disk
    todo_sessionEnd("/tmp/todo.does-not-exist-1234")

    # Test verification: rmtree was still called (caller swallows the error)
    assert deleted == ["/tmp/todo.does-not-exist-1234"]
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# Valid /tmp/todo.X prefix
# ---------------------------------------------------------------------------


def test_valid_tmp_prefix_calls_rmtree(monkeypatch, capsys):
    # Scenario: valid /tmp/todo.X path delegates removal to shutil.rmtree
    # Setup: capture rmtree calls
    calls: list[tuple] = []

    def fake_rmtree(path, ignore_errors=False):
        calls.append((path, ignore_errors))

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    # Test action:
    todo_sessionEnd("/tmp/todo.abc123")

    # Test verification:
    assert calls == [("/tmp/todo.abc123", True)]
    assert capsys.readouterr().err == ""


def test_valid_tmp_prefix_suffix_variation(monkeypatch):
    # Scenario: /tmp/todo. with a different suffix is also accepted
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/tmp/todo.xyz-session-99")

    # Test verification:
    assert calls == ["/tmp/todo.xyz-session-99"]


# ---------------------------------------------------------------------------
# Valid /private/tmp/todo.X prefix
# ---------------------------------------------------------------------------


def test_valid_private_tmp_prefix_calls_rmtree(monkeypatch, capsys):
    # Scenario: valid /private/tmp/todo.X path (macOS real path) is accepted
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/private/tmp/todo.session42")

    # Test verification:
    assert calls == ["/private/tmp/todo.session42"]
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# Invalid prefix - dir untouched, stderr warning emitted
# ---------------------------------------------------------------------------


def test_invalid_prefix_prints_stderr_and_skips_rmtree(monkeypatch, capsys):
    # Scenario: path with unrecognised prefix is rejected; rmtree not called
    # Setup:
    calls: list[str] = []
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors=False: calls.append(path))

    # Test action:
    todo_sessionEnd("/var/tmp/todo.sneaky")

    # Test verification:
    assert calls == []
    err = capsys.readouterr().err
    assert "[todo-session-end] refusing to rm unexpected path: /var/tmp/todo.sneaky" in err


def test_invalid_prefix_leaves_directory_intact(monkeypatch, tmp_path, capsys):
    # Scenario: directory with bad prefix must not be removed from the filesystem
    # Setup: a real directory that should NOT be touched
    bad_dir = tmp_path / "evil"
    bad_dir.mkdir()
    # Bypass the prefix by using a path string that does NOT match valid prefixes
    fake_bad_path = str(bad_dir)

    monkeypatch.setattr(shutil, "rmtree", shutil.rmtree)  # use real rmtree to detect any deletion

    # Test action:
    todo_sessionEnd(fake_bad_path)

    # Test verification: directory still exists because prefix was invalid
    assert bad_dir.exists()



def test_missing_args_returns_early(tmp_path: Path, capsys) -> None:
    # Scenario: all three required args are empty strings
    # Setup: no filesystem state needed
    # Test action: call with empty strings
    rc = todo_stop("", "", "")
    # Test verification: must not raise; logs to stderr; returns 0
    captured = capsys.readouterr()
    assert rc == 0
    assert "[todo-stop] missing args" in captured.err


def _make_tmpdir(tmp_path: Path, tmux_target: str = "%42") -> Path:
    """Write a minimal per-invocation tmpdir with tmux_target sidecar."""
    d = tmp_path / "todo.XXXX"
    d.mkdir()
    (d / "tmux_target").write_text(f"{tmux_target}\n")
    return d


def test_missing_state_dir_returns_early(tmp_path: Path, capsys) -> None:
    # Scenario: input_file and tmpdir_inv present but state_dir empty
    # Setup:
    inv = _make_tmpdir(tmp_path)
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    rc = todo_stop(str(input_file), str(inv), "")
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "[todo-stop] missing args" in captured.err


# ---------------------------------------------------------------------------
# tmux_target sidecar retry / failure
# ---------------------------------------------------------------------------


def test_empty_sidecar_logs_and_returns(tmp_path: Path, capsys) -> None:
    # Scenario: tmux_target file exists but is empty after all retries
    # Setup:
    inv = tmp_path / "inv"
    inv.mkdir()
    (inv / "tmux_target").write_text("")       # empty — no pane id
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action: patch time.sleep so test is fast
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


def test_missing_sidecar_file_logs_and_returns(tmp_path: Path, capsys) -> None:
    # Scenario: tmux_target file does not exist at all
    # Setup:
    inv = tmp_path / "inv"
    inv.mkdir()
    # no tmux_target written
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with patch("common.scripts.todo_lib.time.sleep"):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    captured = capsys.readouterr()
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


# ---------------------------------------------------------------------------
# Audit log — SUCCESS path
# ---------------------------------------------------------------------------


def test_processed_marker_writes_success_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt first line starts with "PROCESSED:"
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\nsome other content\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        rc = todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert rc == 0
    audit = (state_dir / "audit.log").read_text()
    assert "SUCCESS" in audit
    assert str(input_file) in audit


def test_processed_marker_removes_input_file(tmp_path: Path) -> None:
    # Scenario: SUCCESS path should delete the input file
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification: file must be gone
    assert not input_file.exists()


# ---------------------------------------------------------------------------
# Audit log — FAIL paths
# ---------------------------------------------------------------------------


def test_no_processed_marker_writes_fail_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt exists but first line lacks PROCESSED:
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("still pending\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    audit = (state_dir / "audit.log").read_text()
    assert "FAIL" in audit
    assert "no PROCESSED marker" in audit


def test_no_processed_marker_does_not_remove_input_file(tmp_path: Path) -> None:
    # Scenario: FAIL path must NOT delete the input file (only SUCCESS deletes it)
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("still pending\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert input_file.exists()


def test_missing_input_file_writes_fail_missing_to_audit(tmp_path: Path) -> None:
    # Scenario: input.txt does not exist at all
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "nonexistent_input.txt"
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    audit = (state_dir / "audit.log").read_text()
    assert "FAIL" in audit
    assert "input.txt missing" in audit


# ---------------------------------------------------------------------------
# Audit rotation
# ---------------------------------------------------------------------------


def test_audit_rotated_when_over_1000_lines(tmp_path: Path) -> None:
    # Scenario: audit.log exceeds 1000 lines; must be trimmed to 1000
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    audit = state_dir / "audit.log"
    # Write 1005 lines
    audit.write_text("\n".join(f"line {i}" for i in range(1005)) + "\n")
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification: line count must be <= 1000
    line_count = len([l for l in audit.read_text().splitlines() if l])
    assert line_count <= 1000


# ---------------------------------------------------------------------------
# tmux pane kill (side-effect verification)
# ---------------------------------------------------------------------------


def test_kill_pane_called_with_correct_target(tmp_path: Path) -> None:
    # Scenario: tmux_killPane must be called with the pane id from sidecar
    # Setup:
    inv = _make_tmpdir(tmp_path, tmux_target="%99")
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    kill_mock = MagicMock(return_value=0)
    retile_mock = MagicMock(return_value=0)
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane", kill_mock),
        patch("common.scripts.todo_lib.tmux_retile", retile_mock),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    kill_mock.assert_called_once_with("%99")


def test_retile_called_with_todo_todos_window(tmp_path: Path) -> None:
    # Scenario: tmux_retile must target "todo:todos" after killing pane
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "state"
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    retile_mock = MagicMock(return_value=0)
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile", retile_mock),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    retile_mock.assert_called_once_with("todo:todos")


def test_state_dir_created_if_absent(tmp_path: Path) -> None:
    # Scenario: state_dir does not pre-exist; function must create it
    # Setup:
    inv = _make_tmpdir(tmp_path)
    state_dir = tmp_path / "new_state_dir"
    # Do NOT create state_dir
    input_file = tmp_path / "input.txt"
    input_file.write_text("PROCESSED: done\n")
    # Test action:
    with (
        patch("common.scripts.todo_lib.time.sleep"),
        patch("common.scripts.todo_lib.tmux_killPane"),
        patch("common.scripts.todo_lib.tmux_retile"),
    ):
        todo_stop(str(input_file), str(inv), str(state_dir))
    # Test verification:
    assert state_dir.is_dir()
    assert (state_dir / "audit.log").is_file()
