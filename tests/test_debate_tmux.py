"""Tests for debate_lib -- tmux bucket (claimSession, launchAgent ready-poll, newEmptyPane, sendPromptToAgent, waitForMarker)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from common.scripts.debate_lib import (
    debate_claimSession,
    debate_launchAgent,
    debate_newEmptyPane,
    debate_sendPromptToAgent,
)
from common.scripts.tmux_lib import (
    tmux_killSession,
    tmux_listPanes,
    tmux_newSession,
)
from common.scripts import debate_lib as mod


# =====================================================================
# debate_claimSession tests [tmux -- slot claiming]
# =====================================================================


def test_claims_first_unused_when_all_free(tmp_path):
    # Scenario: no debate-* sessions exist; first attempt at debate-1 succeeds.
    # Setup: fake tmux runner that always returns rc=0 (free slot).
    calls = []

    def fake_tmux(argv):
        calls.append(argv)
        return 0  # success

    # Test action: claim a session.
    result = debate_claimSession("sleep 86400", tmux_runner=fake_tmux)

    # Test verification: returned debate-1 and invoked tmux exactly once.
    assert result == "debate-1"
    assert len(calls) == 1


def test_skips_collisions_until_free_slot(tmp_path):
    # Scenario: debate-1 and debate-2 already exist; debate-3 is free.
    # Setup: runner returns nonzero for first two N, zero for third.
    rcs = iter([1, 1, 0])
    seen = []

    def fake_tmux(argv):
        seen.append(argv)
        return next(rcs)

    # Test action: claim.
    result = debate_claimSession("keepalive", tmux_runner=fake_tmux)

    # Test verification: walked N=1..3, returned debate-3.
    assert result == "debate-3"
    assert len(seen) == 3


def test_passes_keepalive_cmd_and_geometry_to_tmux(tmp_path):
    # Scenario: claim must invoke tmux with -d, -s <name>, -x 200, -y 60,
    #           -n main, and the keepalive_cmd as the final argv.
    # Setup: runner that succeeds and records argv.
    captured = {}

    def fake_tmux(argv):
        captured["argv"] = argv
        return 0

    # Test action: claim with a specific keepalive command.
    debate_claimSession("sleep 99999", tmux_runner=fake_tmux)

    # Test verification: argv contains required flags and keepalive tail.
    argv = captured["argv"]
    assert argv[0] == "tmux"
    assert "new-session" in argv
    assert "-d" in argv
    assert "-s" in argv and argv[argv.index("-s") + 1] == "debate-1"
    assert "-x" in argv and argv[argv.index("-x") + 1] == "200"
    assert "-y" in argv and argv[argv.index("-y") + 1] == "60"
    assert "-n" in argv and argv[argv.index("-n") + 1] == "main"
    assert argv[-1] == "sleep 99999"


def test_raises_when_all_slots_exhausted(tmp_path):
    # Scenario: every N from 1 to 999 collides; function must signal failure.
    # Setup: runner that always returns nonzero.
    attempts = {"n": 0}

    def fake_tmux(argv):
        attempts["n"] += 1
        return 1

    # Test action + verification: RuntimeError raised after 999 attempts.
    with pytest.raises(RuntimeError):
        debate_claimSession("k", tmux_runner=fake_tmux)
    assert attempts["n"] == 999


def test_session_names_are_sequential_debate_n(tmp_path):
    # Scenario: verify the N-th attempt targets `debate-<N>` (1-indexed).
    # Setup: fail first 4, succeed on 5th.
    names = []
    rcs = iter([1, 1, 1, 1, 0])

    def fake_tmux(argv):
        names.append(argv[argv.index("-s") + 1])
        return next(rcs)

    # Test action: claim.
    result = debate_claimSession("cmd", tmux_runner=fake_tmux)

    # Test verification: sequential debate-1..debate-5 attempts, returned debate-5.
    assert names == ["debate-1", "debate-2", "debate-3", "debate-4", "debate-5"]
    assert result == "debate-5"


# =====================================================================
# debate_launchAgent ready-poll tests [tmux -- readiness]
# =====================================================================


_PANE = "%7"
_AGENT = "claude"
_CMD = "claude --settings /tmp/s.json --add-dir '/repo'"
_READY = "Claude Code v"
_STAGE = "r1"


def _patch_all(pane_content: str = "", *, ready_after: int | None = 0):
    """Patch I/O callees on common.scripts.debate_lib (where bare names resolve)."""
    call_count = 0

    def fake_capture(pane_id, scrollback_lines=2000):
        nonlocal call_count
        result = _READY if (ready_after is not None and call_count >= ready_after) else ""
        call_count += 1
        return result

    return (
        patch("common.scripts.debate_lib.tmux_sendAndSubmit"),
        patch("common.scripts.debate_lib.tmux_capturePane", side_effect=fake_capture),
        patch("common.scripts.debate_lib.debate_writeFailed"),
        patch("common.scripts.debate_lib.time.sleep"),
    )


def test_sends_launch_cmd_via_tmux(tmp_path):
    # Scenario: launch_agent calls tmux_send_and_submit with the correct pane
    #           and launch command string.
    # Setup: pane immediately ready
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0] as mock_send, patches[1], patches[2], patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: sendAndSubmit called once with pane_id and launch_cmd
    mock_send.assert_called_once_with(_PANE, _CMD)


def test_returns_true_when_ready_marker_found(tmp_path):
    # Scenario: pane capture contains ready_marker before timeout.
    # Setup: capture returns ready string on iteration 0
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0], patches[1], patches[2], patches[3]:
        result = debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: truthy result means success
    assert result is True


def test_returns_false_on_timeout(tmp_path):
    # Scenario: pane never shows ready_marker within timeout.
    # Setup: capture always returns empty string; use timeout=2 for speed
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=None)
    with patches[0], patches[1], patches[2], patches[3]:
        result = debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
            timeout=2,
        )
    # Test verification: False means timeout
    assert result is False


def test_sleeps_between_capture_polls(tmp_path):
    # Scenario: each polling iteration sleeps 1 second (mirrors bash `sleep 1`).
    # Setup: ready on iteration 2 (so 2 sleeps happen before success)
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=2)
    with patches[0], patches[1], patches[2], patches[3] as mock_sleep:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: sleep(1) called at least twice
    assert mock_sleep.call_count >= 2
    mock_sleep.assert_any_call(1)


def test_default_timeout_is_120(tmp_path):
    # Scenario: when timeout is omitted, the function defaults to 120 iterations.
    # Setup: capture never ready; measure how many times sleep was called.
    # RELAXED_COVERAGE: bash default is 120; we verify the parameter default
    # rather than waiting 120 real seconds. We inspect the function signature.
    # Test action: introspect default parameter value
    import inspect
    sig = inspect.signature(debate_launchAgent)
    # Test verification: default value for `timeout` parameter is 120
    assert sig.parameters["timeout"].default == 120


# =====================================================================
# debate_newEmptyPane tests
# =====================================================================


def test_newEmptyPane_returnsPaneId_onSuccess():
    # Scenario: subprocess succeeds and returns a pane id; function returns it.
    # Setup: mock subprocess.run to simulate tmux success with pane id '%7'.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%7\n"
    fake_result.stderr = ""
    with patch(
        "common.scripts.tmux_lib.tmux_selectLayout",
        return_value=0,
    ), patch(
        "common.scripts.debate_lib.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call with arbitrary window target and cwd.
        result = debate_newEmptyPane("mysession:mywindow", "/tmp")
    # Test verification: returned pane id matches stdout (stripped).
    assert result == "%7"


def test_newEmptyPane_returnsNone_onTmuxFailure():
    # Scenario: subprocess reports nonzero rc; function returns None.
    # Setup: mock subprocess.run to simulate tmux error.
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "error: no current target"
    with patch(
        "common.scripts.tmux_lib.tmux_selectLayout",
        return_value=0,
    ), patch(
        "common.scripts.debate_lib.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call with a target that would fail.
        result = debate_newEmptyPane("bogus:window", "/tmp")
    # Test verification: None returned on failure.
    assert result is None


def test_newEmptyPane_returnsNone_onEmptyPaneId():
    # Scenario: subprocess succeeds (rc=0) but stdout is blank; function returns None.
    # Setup: mock subprocess.run to return rc=0 with empty stdout.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "   \n"
    fake_result.stderr = ""
    with patch(
        "common.scripts.tmux_lib.tmux_selectLayout",
        return_value=0,
    ), patch(
        "common.scripts.debate_lib.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call the function.
        result = debate_newEmptyPane("mysession:mywindow", "/tmp")
    # Test verification: None when pane id is empty/whitespace.
    assert result is None


def test_newEmptyPane_callsRetile_beforeSplit():
    # Scenario: tmux_retile is called with window_target before the split-window subprocess.
    # Setup: capture call order via mock.
    call_log: list[str] = []

    def fake_retile(target: str) -> int:
        call_log.append(f"retile:{target}")
        return 0

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%9\n"
    fake_result.stderr = ""

    def fake_run(argv, **kwargs):
        call_log.append(f"split:{argv}")
        return fake_result

    with patch(
        "common.scripts.tmux_lib.tmux_selectLayout",
        side_effect=lambda t, l: fake_retile(t) or 0,
    ), patch(
        "common.scripts.debate_lib.subprocess.run",
        side_effect=fake_run,
    ):
        # Test action: call the function.
        debate_newEmptyPane("s:w", "/home/user")
    # Test verification: retile call appears before split call.
    assert len(call_log) == 2
    assert call_log[0].startswith("retile:")
    assert call_log[1].startswith("split:")


def test_newEmptyPane_passesCorrectCwdToSplit():
    # Scenario: -c <cwd> is present in the split-window argv.
    # Setup: capture argv passed to subprocess.run.
    captured_argv: list[list[str]] = []

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%3\n"
    fake_result.stderr = ""

    def fake_run(argv, **kwargs):
        captured_argv.append(list(argv))
        return fake_result

    with patch(
        "common.scripts.tmux_lib.tmux_selectLayout",
        return_value=0,
    ), patch(
        "common.scripts.debate_lib.subprocess.run",
        side_effect=fake_run,
    ):
        # Test action: call with a specific cwd.
        debate_newEmptyPane("s:w", "/specific/path")
    # Test verification: argv contains '-c' followed by the given cwd.
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert "-c" in argv
    idx = argv.index("-c")
    assert argv[idx + 1] == "/specific/path"


def test_newEmptyPane_retileRcIgnored_doesNotPreventSplit():
    # Scenario: tmux_retile returns nonzero; split still proceeds (RELAXED_COVERAGE).
    # Setup: retile mock returns 1, split mock returns success.
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "%5\n"
    fake_result.stderr = ""
    with patch(
        "common.scripts.tmux_lib.tmux_selectLayout",
        return_value=1,
    ), patch(
        "common.scripts.debate_lib.subprocess.run",
        return_value=fake_result,
    ):
        # Test action: call despite retile failure.
        result = debate_newEmptyPane("s:w", "/tmp")
    # Test verification: pane id still returned (retile rc not checked).
    assert result == "%5"


# ---------------------------------------------------------------------------
# Live tests (real tmux server)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_newEmptyPane_addsPaneToWindow(tmux_session_newpane):
    # Scenario: calling debate_newEmptyPane on an existing window creates a new pane.
    # Setup: session has one pane (from fixture); form window target.
    window_target = f"{tmux_session_newpane}:0"
    before = tmux_listPanes(window_target, "-F", "#{pane_id}")
    # Test action: create a new empty pane.
    pane_id = debate_newEmptyPane(window_target, "/tmp")
    # Test verification: returned pane id is non-None and one more pane exists.
    assert pane_id is not None
    assert pane_id.startswith("%")
    after = tmux_listPanes(window_target, "-F", "#{pane_id}")
    assert len(after) == len(before) + 1


@pytest.mark.live
def test_newEmptyPane_returnedIdInPaneList(tmux_session_newpane):
    # Scenario: the pane id returned by debate_newEmptyPane is present in the live pane list.
    # Setup: form window target.
    window_target = f"{tmux_session_newpane}:0"
    # Test action: create a new pane.
    pane_id = debate_newEmptyPane(window_target, "/tmp")
    # Test verification: pane id appears in listPanes output.
    assert pane_id is not None
    ids = tmux_listPanes(window_target, "-F", "#{pane_id}")
    assert pane_id in ids


@pytest.mark.live
def test_newEmptyPane_returnsNone_onBogusTarget():
    # Scenario: calling debate_newEmptyPane with a nonexistent target returns None.
    # Setup: a session name that does not exist.
    bogus = f"nonexistent-session-{os.getpid()}:0"
    # Test action: attempt to create a pane in the bogus session.
    result = debate_newEmptyPane(bogus, "/tmp")
    # Test verification: None on tmux failure.
    assert result is None


# ---------------------------------------------------------------------------
# Live fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmux_session_newpane():
    # Setup: create a detached tmux session; teardown kills it unconditionally.
    name = f"tmux-py-newemptypane-{os.getpid()}"
    tmux_killSession(name)
    rc = tmux_newSession(name)
    assert rc == 0, "fixture precondition: new session must succeed"
    yield name
    tmux_killSession(name)


# =====================================================================
# debate_sendPromptToAgent tests [tmux -- waitForMarker]
# =====================================================================


# Scenario: marker (basename of instructions path) appears in pane on first poll.
# Setup: capture returns text containing basename; tmux_sendAndSubmit returns 0.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 0 (success rc); send-and-submit called with
# bash-shaped prompt; capture called with 2000 scrollback.
def test_returns_zero_when_marker_seen_immediately(monkeypatch, capsys):
    sent_calls: list[tuple[str, str]] = []
    capture_calls: list[tuple[str, int | None]] = []

    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, txt: sent_calls.append((pane, txt)) or 0,
    )
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: capture_calls.append((pane, n))
        or "noise\nr1_instructions_gemini.txt echoed back\n",
    )
    monkeypatch.setattr("common.scripts.debate_lib.debate_writeFailed", lambda *a, **k: pytest.fail("should not be called"))

    rc = debate_sendPromptToAgent(
        "%7", "r1", "gemini",
        "/debates/x/r1_instructions_gemini.txt",
    )

    assert rc == 0
    assert sent_calls == [
        ("%7", "read /debates/x/r1_instructions_gemini.txt and perform them"),
    ]
    assert capture_calls == [("%7", 2000)]


# Scenario: marker never appears within 30s budget -> timeout path.
# Setup: capture always returns empty; sleep is stubbed to no-op so the loop
# runs synchronously through all 30 ticks.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 1; debate_writeFailed called with bash-faithful
# stage + reason; capture called exactly 30 times (one per second budget).
def test_timeout_returns_one_and_invokes_writeFailed(monkeypatch, capsys):
    capture_count = {"n": 0}
    failed_calls: list[tuple[str, str]] = []

    def fake_capture(pane, n=None):
        capture_count["n"] += 1
        return ""

    monkeypatch.setattr("common.scripts.debate_lib.tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr("common.scripts.debate_lib.tmux_capturePane", fake_capture)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        mod, "debate_writeFailed",
        lambda stage, reason: failed_calls.append((stage, reason)),
    )

    rc = debate_sendPromptToAgent(
        "%9", "r2", "codex",
        "/debates/x/r2_instructions_codex.txt",
    )

    assert rc == 1
    assert capture_count["n"] == 30
    assert failed_calls == [
        ("r2", "send_prompt timeout for codex after 30s"),
    ]
    err = capsys.readouterr().err
    assert "[orch] TIMEOUT: r2/codex did not echo prompt" in err


# Scenario: ANSI escape sequences in pane buffer must be stripped before the
# fixed-string match (bash uses `tr -d '\033'`).
# Setup: capture returns marker wrapped in ESC sequences; if ANSI is not
# stripped the literal basename will not match.
# Test action: invoke debate_sendPromptToAgent.
# Test verification: returns 0 (match succeeded post-strip).
def test_ansi_escapes_are_stripped_before_match(monkeypatch):
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: "\x1b[32mr1_instructions_claude.txt\x1b[0m",
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr("common.scripts.debate_lib.debate_writeFailed", lambda *a, **k: pytest.fail("unexpected"))

    rc = debate_sendPromptToAgent(
        "%3", "r1", "claude",
        "/debates/y/r1_instructions_claude.txt",
    )

    assert rc == 0


# Scenario: marker derivation uses basename of the instructions path, not the
# full path (bash `marker=$(basename "$instructions")`).
# Setup: capture buffer contains ONLY the basename, never the parent dirs.
# Test action: invoke with a deeply nested instructions path.
# Test verification: returns 0; matching by basename succeeded.
def test_marker_is_basename_not_full_path(monkeypatch):
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda pane, txt: 0)
    monkeypatch.setattr(
        mod, "tmux_capturePane",
        lambda pane, n=None: "echoed: r1_instructions_gemini.txt",
    )
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    rc = debate_sendPromptToAgent(
        "%5", "r1", "gemini",
        "/very/deep/path/Debates/2026/r1_instructions_gemini.txt",
    )

    assert rc == 0
