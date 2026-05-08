"""Tests for jot_lib phase-2 (sendPrompt, launchPhase2Window, sessionStart, jot_main launch wiring)."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.scripts import jot_lib as mod
from common.scripts.jot_lib import (
    jot_launchPhase2Window,
    jot_sendPrompt,
    jot_sessionStart,
)
from common.scripts.util_lib import LockTimeout


# --- jot_sendPrompt ---


def test_jot_sendPrompt_delegates_to_tmux_sendAndSubmit_with_target_and_prompt(monkeypatch):
    # Scenario: caller has tmux target + input file path; jot_sendPrompt hands control to tmux_sendAndSubmit.
    calls = []
    # Setup: patch boundary helper to observe args.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit",
                        lambda p, t: calls.append((p, t)) or 0)
    # Test action.
    rc = jot_sendPrompt("jot:jots.0", "/tmp/jot.ABC123/input.txt")
    # Test verification: helper invoked with target + composed prompt.
    assert rc == 0
    assert calls == [(
        "jot:jots.0",
        "Read /tmp/jot.ABC123/input.txt and follow the instructions at the top of that file",
    )]


def test_jot_sendPrompt_returns_nonzero_when_tmux_helper_fails(monkeypatch):
    # Scenario: tmux send/submit fails; jot_sendPrompt propagates rc.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 1)
    # Test action + verification.
    assert jot_sendPrompt("jot:jots.9", "/tmp/anything.txt") == 1


def test_jot_sendPrompt_input_path_interpolated_verbatim(monkeypatch):
    # Scenario: paths with spaces/unusual chars must appear literally in the prompt.
    weird_path = "/tmp/jot dir/weird name.txt"
    seen = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit",
                        lambda p, t: seen.append((p, t)) or 0)
    # Test action.
    jot_sendPrompt("pane@7", weird_path)
    # Test verification.
    assert seen == [(
        "pane@7",
        f"Read {weird_path} and follow the instructions at the top of that file",
    )]


# --- jot_launchPhase2Window ---

@pytest.fixture
def phase2_env(tmp_path: Path, monkeypatch):
    # Setup: realistic env vars and tmpdirs the function reads.
    repo_root = tmp_path / "repo"
    plugin_data = tmp_path / "plugin_data"
    plugin_root = tmp_path / "plugin_root"
    repo_root.mkdir()
    plugin_data.mkdir()
    plugin_root.mkdir()
    log_file = tmp_path / "jot.log"
    log_file.touch()
    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CWD", str(repo_root))
    monkeypatch.setenv("LOG_FILE", str(log_file))
    monkeypatch.setenv("INPUT_FILE", str(repo_root / "Todos" / "input.txt"))
    monkeypatch.setenv("HOME", "/Users/tester")
    return {
        "repo_root": repo_root,
        "plugin_data": plugin_data,
        "plugin_root": plugin_root,
        "log_file": log_file,
    }


def _phase2_patches(tmp_path: Path):
    tmpdir_inv = tmp_path / "tmpinv"
    tmpdir_inv.mkdir()
    lock_obj = MagicMock()
    lock_obj.__enter__.return_value = lock_obj
    return {
        "tmpdir_inv": tmpdir_inv,
        "lock_obj": lock_obj,
        "file_lock": patch.object(mod, "FileLock", return_value=lock_obj),
        "state_init": patch.object(mod, "jot_initState"),
        "build_cmd": patch.object(
            mod,
            "jot_buildClaudeCmd",
            return_value={
                "TMPDIR_INV": str(tmpdir_inv),
                "SETTINGS_FILE": "/tmp/x/settings.json",
                "CLAUDE_CMD": "claude --foo",
            },
        ),
        "ensure": patch.object(mod, "tmux_ensureSession", return_value=0),
        "split": patch.object(mod, "tmux_splitWorkerPane", return_value="%42"),
        "title": patch.object(mod, "tmux_setPaneTitle", return_value=0),
        "retile": patch.object(mod, "tmux_retile", return_value=0),
        "spawn": patch.object(mod, "terminal_spawnIfNeeded", return_value=0),
    }


def _enter_phase2_patches(patches: dict):
    entered = {}
    for key, value in patches.items():
        if key in {"tmpdir_inv", "lock_obj"}:
            entered[key] = value
        else:
            entered[key] = value.__enter__()
    return entered


def _exit_phase2_patches(patches: dict) -> None:
    for key, value in patches.items():
        if key not in {"tmpdir_inv", "lock_obj"}:
            value.__exit__(None, None, None)


def test_jot_launchPhase2Window_initializes_state_dir_under_repo_root_todos(phase2_env, tmp_path: Path):
    # Scenario: function derives STATE_DIR=$REPO_ROOT/Todos/.jot-state and initializes it.
    # Setup: patch external tmux/build/lock boundaries.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: state init receives the derived state directory.
        expected = str(phase2_env["repo_root"] / "Todos" / ".jot-state")
        m["state_init"].assert_called_once_with(expected)
        assert os.environ["STATE_DIR"] == expected
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_acquires_global_tmux_lock_with_10s_timeout(phase2_env, tmp_path: Path):
    # Scenario: function must hold the global tmux-launch lock during pane spawn.
    # Setup: patch external boundaries.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: FileLock constructed for the global lock path with timeout 10.
        expected_lock = str(phase2_env["plugin_data"] / "tmux-launch.lock")
        m["file_lock"].assert_called_once_with(expected_lock, timeout=10)
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_returns_1_if_lock_acquire_times_out(phase2_env):
    # Scenario: lock contention prevents tmux launch.
    # Setup: FileLock construction raises LockTimeout.
    with patch.object(mod, "FileLock", side_effect=LockTimeout), \
         patch.object(mod, "tmux_ensureSession") as ensure, \
         patch.object(mod, "tmux_splitWorkerPane") as split, \
         patch.object(mod, "jot_buildClaudeCmd") as build_cmd:
        # Test action: launch phase 2.
        rc = jot_launchPhase2Window()
    # Test verification: returns failure and does not reach tmux/build calls.
    assert rc == 1
    ensure.assert_not_called()
    split.assert_not_called()
    build_cmd.assert_not_called()
    assert "failed to acquire global tmux-launch lock" in phase2_env["log_file"].read_text()


def test_jot_launchPhase2Window_pane_counter_increments_modulo_20(phase2_env, tmp_path: Path):
    # Scenario: counter file holds 7, so next pane label is jot8.
    # Setup: seed pane-counter.txt.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    counter = phase2_env["plugin_data"] / "pane-counter.txt"
    counter.write_text("7\n")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: counter increments and pane title uses jot8.
        assert counter.read_text().strip() == "8"
        m["title"].assert_called_once_with("%42", "jot8")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_pane_counter_wraps_from_20_to_1(phase2_env, tmp_path: Path):
    # Scenario: counter at 20 wraps to 1.
    # Setup: seed pane-counter.txt with 20.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    counter = phase2_env["plugin_data"] / "pane-counter.txt"
    counter.write_text("20\n")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: counter wraps and pane title uses jot1.
        assert counter.read_text().strip() == "1"
        m["title"].assert_called_once_with("%42", "jot1")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_split_failure_releases_lock_and_returns_1(phase2_env, tmp_path: Path):
    # Scenario: tmux_splitWorkerPane returns None.
    # Setup: patch split failure.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    m["split"].return_value = None
    try:
        # Test action: launch phase 2.
        rc = jot_launchPhase2Window()
        # Test verification: lock context exits, no title/retile/spawn occurs, rc=1.
        assert rc == 1
        m["lock_obj"].__exit__.assert_called_once()
        m["title"].assert_not_called()
        m["retile"].assert_not_called()
        m["spawn"].assert_not_called()
        assert "tmux split-window returned empty pane id" in phase2_env["log_file"].read_text()
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_writes_pane_id_atomically_via_tmp_then_rename(phase2_env, tmp_path: Path):
    # Scenario: PANE_ID must be written through a temp file then renamed to tmux_target.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: target file has pane id and temp file is gone.
        target_file = m["tmpdir_inv"] / "tmux_target"
        tmp_file = m["tmpdir_inv"] / "tmux_target.tmp"
        assert target_file.read_text().strip() == "%42"
        assert not tmp_file.exists()
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_calls_tmux_helpers_in_required_order(phase2_env, tmp_path: Path):
    # Scenario: ordering invariant is ensureSession, split, title, retile, lock release, spawn.
    # Setup: attach mocks to a parent recorder.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    parent = MagicMock()
    parent.attach_mock(m["ensure"], "ensure")
    parent.attach_mock(m["split"], "split")
    parent.attach_mock(m["title"], "title")
    parent.attach_mock(m["retile"], "retile")
    parent.attach_mock(m["lock_obj"].__exit__, "lock_exit")
    parent.attach_mock(m["spawn"], "spawn")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: ordering preserves lock release before terminal spawn.
        seq = [c[0] for c in parent.mock_calls if c[0] in {"ensure", "split", "title", "retile", "lock_exit", "spawn"}]
        assert seq == ["ensure", "split", "title", "retile", "lock_exit", "spawn"]
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_ensure_session_called_with_jot_jots_session_window(phase2_env, tmp_path: Path):
    # Scenario: ensureSession targets session jot and window jots with cwd plus keepalive command.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: ensureSession arguments match the shared jot tmux window contract.
        args = m["ensure"].call_args.args
        assert args[0] == "jot"
        assert args[1] == "jots"
        assert args[2] == str(phase2_env["repo_root"])
        assert "keepalive" in args[3].lower()
        assert args[4] == "jot: keepalive"
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_split_worker_called_with_built_claude_cmd(phase2_env, tmp_path: Path):
    # Scenario: split worker pane receives CLAUDE_CMD from jot_buildClaudeCmd.
    # Setup: customize build result command.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    m["build_cmd"].return_value = {
        "TMPDIR_INV": str(m["tmpdir_inv"]),
        "SETTINGS_FILE": "/tmp/x/settings.json",
        "CLAUDE_CMD": "claude --custom-arg",
    }
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: split worker uses the command from build result.
        m["split"].assert_called_once_with("jot:jots", str(phase2_env["repo_root"]), "claude --custom-arg")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_spawn_terminal_called_after_lock_released(phase2_env, tmp_path: Path):
    # Scenario: terminal spawn is invoked after lock-protected tmux setup.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: terminal spawner gets session, log file, and prefix.
        m["spawn"].assert_called_once_with("jot", str(phase2_env["log_file"]), "jot")
    finally:
        _exit_phase2_patches(p)


# --- jot_sessionStart ---


def test_missing_input_file_returns_0_and_warns(capsys):
    # Scenario: caller forgot to pass input_file; bash spec returns silent exit 0.
    # Setup: input_file=None, tmpdir_inv non-empty.
    # Test action: invoke jot_sessionStart with missing input_file.
    rc = jot_sessionStart(None, "/some/tmpdir")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and stderr names the missing-args contract.
    assert rc == 0
    assert "missing args" in err


def test_missing_tmpdir_inv_returns_0_and_warns(capsys):
    # Scenario: caller forgot tmpdir_inv argument.
    # Setup: input_file present, tmpdir_inv empty string.
    # Test action: invoke with empty tmpdir_inv.
    rc = jot_sessionStart("/x/in.md", "")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and missing-args message emitted.
    assert rc == 0
    assert "missing args" in err


def test_sidecar_empty_after_retries_returns_0(tmp_path, monkeypatch, capsys):
    # Scenario: tmux_target sidecar never appears within 5 retries.
    # Setup: empty tmpdir, monkeypatch sleep to no-op so test runs fast.
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: call with valid args but no sidecar file present.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 0 and stderr explains sidecar emptiness.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_sidecar_zero_byte_file_treated_as_empty(tmp_path, monkeypatch, capsys):
    # Scenario: sidecar exists but is zero-byte (race window).
    # Setup: create empty tmux_target file; bypass real sleeps.
    (tmp_path / "tmux_target").write_text("")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: empty sidecar is rejected as if missing.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_readiness_timeout_returns_1(tmp_path, monkeypatch, capsys):
    # Scenario: pane id resolved but Claude TUI never shows the ready glyph.
    # Setup: write valid sidecar; stub readiness probe to return 1 (timeout).
    (tmp_path / "tmux_target").write_text("%42\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", lambda pane: 1)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 1, no keys sent, diagnostic emitted.
    assert rc == 1
    assert "claude TUI not ready" in err
    assert sent == []


def test_happy_path_sends_read_prompt_to_resolved_pane(tmp_path, monkeypatch):
    # Scenario: sidecar present, TUI ready -> prompt is submitted to that pane.
    # Setup: write pane id "%99" into sidecar; stub readiness to 0; capture sends.
    (tmp_path / "tmux_target").write_text("%99\nignored-extra\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke with realistic args.
    rc = jot_sessionStart("/path/to/input.md", str(tmp_path))
    # Test verification: rc 0, exactly one send to first-line pane id, exact prompt text.
    assert rc == 0
    assert sent == [
        ("%99", "Read /path/to/input.md and follow the instructions at the top of that file"),
    ]


def test_sidecar_first_line_only_used(tmp_path, monkeypatch):
    # Scenario: sidecar accidentally contains multiple lines; bash uses head -1.
    # Setup: multi-line sidecar; stub readiness OK; capture send target.
    (tmp_path / "tmux_target").write_text("%first\n%second\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: only the first line is used as the pane target.
    assert sent[0][0] == "%first"


def test_readiness_called_with_resolved_pane_id(tmp_path, monkeypatch):
    # Scenario: readiness probe must receive the same pane id parsed from sidecar.
    # Setup: sidecar with "%77"; record arg passed into readiness probe.
    (tmp_path / "tmux_target").write_text("%77\n")
    seen: list[str] = []
    def fake_ready(pane: str) -> int:
        seen.append(pane)
        return 0
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", fake_ready)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 0)
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: readiness probe got the parsed pane id verbatim.
    assert seen == ["%77"]


# --- jot_main launch wiring (W3-A moved tests) ---


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


def test_skip_launch_does_not_call_phase2(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: JOT_SKIP_LAUNCH=1 path emits "(launch skipped)" and skips phase2.
    # Setup: full happy stubs + skip flag.
    _stub_passing_deps(monkeypatch)
    monkeypatch.setenv("JOT_SKIP_LAUNCH", "1")
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr("common.scripts.jot_lib.git_getBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr("common.scripts.jot_lib.git_getRecentCommitHashes", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.git_getUncommittedFilenames", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.todo_scanOpen", lambda r: "")
    launched = {"called": False}
    monkeypatch.setattr("common.scripts.jot_lib.jot_launchPhase2Window", lambda: launched.__setitem__("called", True) or 0)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="X", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot do thing", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 NOT called, block-decision contains "(launch skipped)".
    assert rc == 0
    assert launched["called"] is False
    assert "launch skipped" in out


def test_phase2_called_on_happy_path(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: happy path without JOT_SKIP_LAUNCH calls jot_launchPhase2Window exactly once.
    # Setup: same as happy-path test but track call count.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr("common.scripts.jot_lib.git_getBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr("common.scripts.jot_lib.git_getRecentCommitHashes", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.git_getUncommittedFilenames", lambda c: "")
    monkeypatch.setattr("common.scripts.jot_lib.todo_scanOpen", lambda r: "")
    calls = {"n": 0}

    def fake_launch() -> int:
        calls["n"] += 1
        return 0

    monkeypatch.setattr("common.scripts.jot_lib.jot_launchPhase2Window", fake_launch)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot launch me", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 called once, success block emitted.
    assert rc == 0
    assert calls["n"] == 1
    assert "Done! Jotted idea in" in out
