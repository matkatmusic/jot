"""Tests for tmux_lib Configure bucket: setOption family, selectPane,
setPaneTitle, selectLayout, retile + live."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from common.scripts import tmux_lib as _tmux_lib_mod
from common.scripts.tmux_lib import (
    tmux_killSession,
    tmux_newPane,
    tmux_newSession,
    tmux_newWindow,
    tmux_listPanes,
    tmux_retile,
    tmux_selectLayout,
    tmux_selectPane,
    tmux_setOption,
    tmux_setOptionForTarget,
    tmux_setOptionForWindow,
    tmux_setOptionGlobally,
    tmux_setPaneTitle,
)

# Bind module alias used throughout the test bodies.
mod = _tmux_lib_mod


# === Bucket: Configure ===

# --- tmux_setOption ---

class _FakeCompleted:
    """Stand-in for subprocess.CompletedProcess used by tmux_setOption tests."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_tmux_setOption_invokes_tmux_set_option_with_passed_args_and_returns_zero_on_success(monkeypatch, capfd):
    # Scenario: calling tmux_setOption with scope+name+value invokes
    # `tmux set-option -g status on`, returns 0, and echoes any non-empty
    # stdout from tmux.
    # Setup: capture the cmd argv handed to subprocess.run; return a successful CompletedProcess.
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted(0, stdout="ok-out\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Test action: call with three positional args.
    rc = tmux_setOption("-g", "status", "on")
    out, err = capfd.readouterr()
    # Test verification: rc is 0, argv was [tmux, set-option, ...passed-args], capture flags set, stdout echoed, no stderr noise.
    assert rc == 0
    assert captured["cmd"] == ["tmux", "set-option", "-g", "status", "on"]
    assert captured["kwargs"].get("capture_output") is True
    assert captured["kwargs"].get("text") is True
    assert "ok-out" in out
    assert err == ""


def test_tmux_setOption_emits_no_output_when_tmux_succeeds_with_empty_stdout(monkeypatch, capfd):
    # Scenario: a successful tmux call that produced no stdout must produce
    # no spurious blank line on the orchestrator's stdout (mirrors bash invoke_command).
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(0, "", ""))
    rc = tmux_setOption("-g", "status", "on")
    out, err = capfd.readouterr()
    # Test verification: rc=0 and BOTH output streams are completely empty.
    assert rc == 0
    assert out == ""
    assert err == ""


def test_tmux_setOption_logs_caller_name_and_combined_output_to_stderr_when_tmux_fails(monkeypatch, capfd):
    # Scenario: when tmux returns nonzero, the function attributes the failure
    # to the immediate caller's frame name (sys._getframe(1)) and logs the
    # combined stdout+stderr to its own stderr.
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(1, "", "unknown option\n")
    )

    # Setup: define a uniquely-named caller function so we can assert the
    # caller-name resolution mechanism actually works.
    def caller_frame():
        return tmux_setOption("-g", "bogus", "value")

    # Test action: invoke from caller_frame().
    rc = caller_frame()
    out, err = capfd.readouterr()
    # Test verification: rc is propagated from tmux; stderr line begins with [caller_frame]; the failed cmd and tmux's error both appear.
    assert rc == 1
    assert err.startswith("[caller_frame]")
    assert "tmux set-option -g bogus value" in err
    assert "unknown option" in err


def test_tmux_setOption_passes_variadic_args_through_to_tmux_in_order(monkeypatch):
    # Scenario: the function must NOT reorder, drop, or dedupe its variadic args -
    # they must appear in tmux's argv in the exact order supplied (proves no
    # accidental flag-collapsing or arg-massaging).
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _FakeCompleted(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Test action: pass a deliberately-jumbled set of flags+target+name+value.
    tmux_setOption("-gqu", "-t", "session:0", "mouse", "off")
    # Test verification: argv preserved verbatim after the [tmux, set-option] prefix.
    assert seen["cmd"] == ["tmux", "set-option", "-gqu", "-t", "session:0", "mouse", "off"]


# --- tmux_setOptionForTarget ---

def test_tmux_setOptionForTarget_passes_target_flag_then_target_then_name_then_value_to_tmux_setOption(monkeypatch):
    # Scenario: caller asks to set a tmux option scoped to a specific target;
    # wrapper must forward (-t, target, name, value) in that order to tmux_setOption.
    captured_args = {}

    # Setup: install a spy in place of tmux_setOption to capture forwarded args.
    def spy(*args):
        captured_args["args"] = args
        return 0
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", spy)

    # Test action: invoke the wrapper with sample target/name/value.
    tmux_setOptionForTarget("mysession", "status", "on")

    # Test verification: spy received exactly ("-t", target, name, value).
    assert captured_args["args"] == ("-t", "mysession", "status", "on")


def test_tmux_setOptionForTarget_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the underlying exit code unchanged so
    # callers can branch on success/failure.
    # Setup: stub returns a distinctive non-zero code.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", lambda *a: 42)

    # Test action: invoke wrapper.
    result = tmux_setOptionForTarget("win0", "remain-on-exit", "off")

    # Test verification: returned value matches the stub's return value.
    assert result == 42


# --- tmux_setOptionGlobally ---

def test_tmux_setOptionGlobally_passes_dash_g_flag_then_name_then_value_to_tmux_setOption(monkeypatch):
    # Scenario: caller asks to set a tmux option globally; wrapper must forward
    # ("-g", name, value) in that order to the underlying tmux_setOption.
    captured_args = {}

    # Setup: install a spy in place of tmux_setOption.
    def spy(*args):
        captured_args["args"] = args
        return 0
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", spy)

    # Test action: invoke the wrapper.
    tmux_setOptionGlobally("status-interval", "5")

    # Test verification: spy received exactly ("-g", name, value).
    assert captured_args["args"] == ("-g", "status-interval", "5")


def test_tmux_setOptionGlobally_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the underlying exit code unchanged.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", lambda *a: 42)

    # Test action: invoke wrapper.
    result = tmux_setOptionGlobally("foo", "bar")

    # Test verification: returned value equals the stub's return value.
    assert result == 42


# --- tmux_setOptionForWindow ---

def test_tmux_setOptionForWindow_passes_dash_w_then_dash_t_then_target_then_name_then_value_to_tmux_setOption(monkeypatch):
    # Scenario: wrapper must forward args as (-w, -t, target, name, value),
    # preserving bash flag order from `tmux_set_option -w -t <target> <name> <value>`.
    captured = {}

    # Setup: spy capturing all positional args passed to tmux_setOption.
    def spy(*args):
        captured["args"] = args
        return 0
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", spy)

    # Test action: invoke wrapper with representative target/name/value.
    tmux_setOptionForWindow("mywin", "remain-on-exit", "on")

    # Test verification: argv order matches bash exactly.
    assert captured["args"] == ("-w", "-t", "mywin", "remain-on-exit", "on")


def test_tmux_setOptionForWindow_returns_the_exit_code_from_tmux_setOption(monkeypatch):
    # Scenario: wrapper must propagate the callee's exit code unchanged.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_setOption", lambda *a: 42)

    # Test action: invoke wrapper.
    result = tmux_setOptionForWindow("win", "opt", "val")

    # Test verification: wrapper returns exactly what tmux_setOption returned.
    assert result == 42


# --- tmux_selectPane ---

def _make_fake_run(rc: int, stdout: str = "", stderr: str = "", calls: list | None = None):
    """Builds a fake subprocess.run with controllable rc/stdout/stderr."""
    def _fake(cmd, *args, **kwargs):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout=stdout, stderr=stderr)
    return _fake


def test_tmux_selectPane_invokes_tmux_select_pane_with_dash_t_target(monkeypatch):
    # Scenario: caller passes a pane target; function shells out to `tmux select-pane -t <target>` exactly.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke under test.
    tmux_selectPane("sess:0.1")
    # Test verification: exact argv (-t flag + target placement).
    assert calls == [["tmux", "select-pane", "-t", "sess:0.1"]]


def test_tmux_selectPane_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0; function returns 0.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_selectPane("good-target") == 0


def test_tmux_selectPane_returns_nonzero_and_logs_caller_when_select_fails(monkeypatch, capsys):
    # Scenario: tmux fails (e.g. missing pane); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))

    # Setup: named caller frame to assert sys._getframe(1) attribution.
    def caller_frame():
        return tmux_selectPane("missing")

    # Test action.
    rc = caller_frame()
    err = capsys.readouterr().err
    # Test verification: rc propagated; stderr names caller and tmux's stderr.
    assert rc == 1
    assert "caller_frame" in err
    assert "can't find pane" in err


# --- tmux_setPaneTitle ---

def test_tmux_setPaneTitle_invokes_tmux_select_pane_with_dash_t_target_and_dash_T_title(monkeypatch):
    # Scenario: caller sets a pane title; the underlying tmux command must use select-pane with -t <target> and -T <title>.
    calls: list = []
    # Setup: capturing fake.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action: invoke with a known pane target and title.
    tmux_setPaneTitle("%42", "my-title")
    # Test verification: argv is exactly the bash equivalent `tmux select-pane -t %42 -T my-title`.
    assert calls == [["tmux", "select-pane", "-t", "%42", "-T", "my-title"]]


def test_tmux_setPaneTitle_returns_zero_on_success(monkeypatch):
    # Scenario: tmux exits 0; wrapper propagates 0 to the caller.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_setPaneTitle("%0", "title") == 0


def test_tmux_setPaneTitle_returns_nonzero_and_logs_caller_when_target_missing(monkeypatch, capsys):
    # Scenario: tmux exits nonzero (e.g. target gone); wrapper returns rc and logs caller-attributed diagnostic to stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="can't find pane"))
    # Test action: invoke from this test (caller name = test's name).
    rc = tmux_setPaneTitle("%999", "x")
    err = capsys.readouterr().err
    # Test verification: nonzero rc propagated AND stderr message tagged with calling test's name.
    assert rc == 1
    assert "[test_tmux_setPaneTitle_returns_nonzero_and_logs_caller_when_target_missing]" in err
    assert "can't find pane" in err


# --- tmux_selectLayout ---

def test_tmux_selectLayout_invokes_tmux_select_layout_with_dash_t_target_then_layout_name(monkeypatch):
    # Scenario: caller passes target and layout; argv is `tmux select-layout -t <target> <layout>`.
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0, calls=calls))
    # Test action.
    tmux_selectLayout("session:0.0", "tiled")
    # Test verification.
    assert calls == [["tmux", "select-layout", "-t", "session:0.0", "tiled"]]


def test_tmux_selectLayout_returns_zero_on_success(monkeypatch):
    # Scenario: subprocess returns rc=0; function propagates.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(0))
    # Test action + verification.
    assert tmux_selectLayout("sess:0", "even-horizontal") == 0


def test_tmux_selectLayout_returns_nonzero_and_logs_caller_when_layout_invalid(monkeypatch, capsys):
    # Scenario: tmux rejects an invalid layout (rc=1); function returns rc and logs caller-attributed stderr.
    monkeypatch.setattr(subprocess, "run", _make_fake_run(1, stderr="invalid layout: bogus"))
    # Test action.
    rc = tmux_selectLayout("sess:0", "bogus")
    err = capsys.readouterr().err
    # Test verification.
    assert rc == 1
    assert "test_tmux_selectLayout_returns_nonzero_and_logs_caller_when_layout_invalid" in err
    assert "tmux select-layout -t sess:0 bogus" in err
    assert "invalid layout: bogus" in err


# --- tmux_retile ---

def test_tmux_retile_invokes_tmux_selectLayout_with_tiled_for_the_given_target(monkeypatch):
    # Scenario: tmux_retile must delegate to tmux_selectLayout passing the literal "tiled" layout.
    calls: list = []

    # Setup: spy.
    def spy(target, layout):
        calls.append((target, layout))
        return 0

    monkeypatch.setattr("common.scripts.tmux_lib.tmux_selectLayout", spy)
    # Test action.
    tmux_retile("session:1")
    # Test verification: exactly one delegation, target verbatim, layout literal "tiled".
    assert calls == [("session:1", "tiled")]


def test_tmux_retile_returns_the_exit_code_from_tmux_selectLayout(monkeypatch):
    # Scenario: thin wrapper must propagate the callee's return value.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_selectLayout", lambda *a: 42)
    # Test action + verification.
    assert tmux_retile("any-target") == 42


# === Bucket: Configure [live] ===

@pytest.fixture
def tmux_session_opts():
    # Provide a unique, isolated tmux session for one test; tear it down on exit.
    name = f"tmux-py-opt-test-{os.getpid()}"
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)
    rc = tmux_newSession(name)
    assert rc == 0, "fixture failed to create tmux session"
    yield name
    subprocess.run(["tmux", "kill-session", "-t", name],
                   capture_output=True, check=False)


# Skip the whole module if tmux is unavailable on this host.
pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not installed"
)


@pytest.mark.live
def test_setOptionForWindow_rejects_nonexistent_window(tmux_session_opts, capfd):
    # Scenario: setting a window option against a missing window fails.
    # Setup: live session exists, but target window does not.
    session = tmux_session_opts
    bogus_win = f"nosuch-{os.getpid()}"
    # Test action: attempt to set the option against the absent window.
    rc = tmux_setOptionForWindow(f"{session}:{bogus_win}", "aggressive-resize", "on")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()



@pytest.mark.live
def test_setOptionForWindow_accepts_valid_window_option(tmux_session_opts):
    # Scenario: setting a window-scoped option on a real window succeeds.
    # Setup: create a named window inside the fixture session.
    session = tmux_session_opts
    win = f"optwin-{os.getpid()}"
    rc_new = tmux_newWindow(session, win)
    assert rc_new == 0, "precondition: tmux_newWindow should succeed"
    # Test action: set `aggressive-resize on` on the new window.
    rc = tmux_setOptionForWindow(f"{session}:{win}", "aggressive-resize", "on")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0

@pytest.mark.live
def test_setOptionGlobally_rejects_invalid_option(capfd):
    # Scenario: setting a fabricated global option fails.
    # Setup: no fixture state needed (global scope).
    # Test action: attempt to set an unknown option name globally.
    rc = tmux_setOptionGlobally("not-a-real-option", "foo")
    # Test verification: rc nonzero.
    assert rc != 0
    capfd.readouterr()

@pytest.mark.live
def test_setOptionGlobally_accepts_valid_global_option():
    # Scenario: setting a global option to its current value succeeds (no-op).
    # Setup: read the current global `mouse` value so we can rewrite it identically.
    proc = subprocess.run(
        ["tmux", "show-options", "-gv", "mouse"],
        capture_output=True, text=True, check=False,
    )
    current = (proc.stdout or "").strip() or "off"
    # Test action: set the global `mouse` option back to the captured value.
    rc = tmux_setOptionGlobally("mouse", current)
    # Test verification: rc must be 0.
    assert rc == 0



@pytest.mark.live
def test_setOptionForTarget_rejects_nonexistent_target(capfd):
    # Scenario: targeting a session that does not exist returns nonzero.
    # Setup: build a name guaranteed not to exist.
    bogus = f"nonexistent-{os.getpid()}"
    subprocess.run(["tmux", "kill-session", "-t", bogus],
                   capture_output=True, check=False)
    # Test action: try to set `mouse on` against the nonexistent session.
    rc = tmux_setOptionForTarget(bogus, "mouse", "on")
    # Test verification: tmux rejects unknown target; rc nonzero.
    assert rc != 0
    capfd.readouterr()



@pytest.mark.live
def test_setOptionForTarget_rejects_invalid_option(tmux_session_opts, capfd):
    # Scenario: setting an unknown option name on a live session returns nonzero.
    # Setup: live session from fixture.
    session = tmux_session_opts
    # Test action: attempt to set a fabricated option name.
    rc = tmux_setOptionForTarget(session, "not-a-real-option", "foo")
    # Test verification: tmux rejects unknown option; rc nonzero.
    assert rc != 0
    capfd.readouterr()  # drain caller-attributed stderr from helper


@pytest.mark.live
def test_setOptionForTarget_accepts_valid_session_option(tmux_session_opts):
    # Scenario: setting a real session-scoped option on a live session returns rc=0.
    # Setup: tmux_session_opts fixture provides a fresh detached session.
    session = tmux_session_opts
    # Test action: set the session-scoped `remain-on-exit` option to `off`.
    rc = tmux_setOptionForTarget(session, "remain-on-exit", "off")
    # Test verification: tmux accepted it; rc must be 0.
    assert rc == 0


# Real-tmux fixture: creates a detached session, yields its name, kills on teardown.
@pytest.fixture
def tmux_session_panes():
    name = f"tmux-py-pane-test-{os.getpid()}"
    tmux_killSession(name)  # Setup: ensure no stale session of the same name
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


def _first_pane_id(session: str) -> str:
    # Helper: returns the first pane id (e.g. "%0") in the session.
    rows = tmux_listPanes(session, "-F", "#{pane_id}")
    return rows[0] if rows else ""


@pytest.mark.live
def test_selectPane_byKnownPaneId_succeeds(tmux_session_panes):
    # Scenario: select_pane targets an existing pane id and succeeds.
    # Setup: capture id of the only pane.
    pid = _first_pane_id(tmux_session_panes)
    assert pid, "precondition: a pane id must exist"
    # Test action: select that pane.
    rc = tmux_selectPane(pid)
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_setPaneTitle_succeeds(tmux_session_panes):
    # Scenario: set_pane_title returns rc 0 on a known pane.
    # Setup: known pane id.
    pid = _first_pane_id(tmux_session_panes)
    # Test action: set a title.
    rc = tmux_setPaneTitle(pid, f"titletest-{os.getpid()}")
    # Test verification: rc 0.
    assert rc == 0


@pytest.mark.live
def test_setPaneTitle_roundTripsThroughListPanes(tmux_session_panes):
    # Scenario: Title set via setPaneTitle is visible via listPanes default -F.
    # Setup: pid + unique title.
    pid = _first_pane_id(tmux_session_panes)
    title = f"titletest-{os.getpid()}"
    assert tmux_setPaneTitle(pid, title) == 0
    # Test action: list panes (default format includes pane_title).
    rows = tmux_listPanes(tmux_session_panes)
    # Test verification: at least one row contains the new title.
    assert any(title in row for row in rows)


@pytest.mark.live
def test_selectPane_failsOnNonexistentTarget():
    # Scenario: select_pane on a nonexistent target returns nonzero rc.
    # Setup: bogus target name.
    bogus = f"nonexistent-{os.getpid()}"
    # Test action: attempt select.
    rc = tmux_selectPane(bogus)
    # Test verification: nonzero rc.
    assert rc != 0


@pytest.fixture
def layout_session():
    # Setup: create real detached tmux session with 3 panes for layout exercises.
    name = f"tmux-py-lay-test-{os.getpid()}"
    tmux_newSession(name)
    tmux_newPane(name)
    tmux_newPane(name)
    yield name
    # Teardown: best-effort kill regardless of test outcome.
    tmux_killSession(name)


@pytest.mark.live
def test_selectLayout_tiled_succeeds(layout_session):
    # Scenario: tmux_selectLayout returns 0 when applying the tiled layout to a real session.
    # Setup: live session created by fixture.
    # Test action: invoke selectLayout with "tiled".
    rc = tmux_selectLayout(layout_session, "tiled")
    # Test verification: rc must be 0 (success).
    assert rc == 0


@pytest.mark.live
def test_selectLayout_evenHorizontal_succeeds(layout_session):
    # Scenario: tmux_selectLayout returns 0 for the even-horizontal preset.
    # Setup: live session from fixture.
    # Test action: invoke selectLayout with "even-horizontal".
    rc = tmux_selectLayout(layout_session, "even-horizontal")
    # Test verification: rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_selectLayout_invalidName_fails(layout_session):
    # Scenario: tmux_selectLayout returns nonzero when given an unknown layout name.
    # Setup: live session from fixture.
    # Test action: invoke selectLayout with bogus layout id.
    rc = tmux_selectLayout(layout_session, "not-a-layout")
    # Test verification: rc must be nonzero (failure).
    assert rc != 0


@pytest.mark.live
def test_retile_succeeds(layout_session):
    # Scenario: tmux_retile returns 0 on a valid live session target.
    # Setup: live session from fixture.
    # Test action: invoke retile.
    rc = tmux_retile(layout_session)
    # Test verification: rc must be 0.
    assert rc == 0


@pytest.mark.live
def test_retile_nonexistentTarget_fails():
    # Scenario: tmux_retile returns nonzero when target session does not exist.
    # Setup: synthesize a name guaranteed not to exist.
    bogus = f"nonexistent-{os.getpid()}-xyz"
    # Test action: invoke retile against bogus target.
    rc = tmux_retile(bogus)
    # Test verification: rc must be nonzero.
    assert rc != 0
