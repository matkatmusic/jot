"""Tests for debate_lib -- daemon bucket (debate_daemonMain, debate_launchAgentsParallel)."""
from __future__ import annotations

from pathlib import Path

from unittest.mock import MagicMock

from common.scripts.debate_lib import debate_daemonMain, debate_launchAgentsParallel
from common.scripts import debate_lib as _MOD_DAEMON


# =====================================================================
# debate_daemonMain helpers and tests
# =====================================================================


def _patch_all_daemon(monkeypatch, overrides=None):
    # Return a dict of all patched callables with sensible defaults (rc=0).
    targets = {
        "debate_initAgentModels": MagicMock(return_value=None),
        "debate_cleanStaleLocks": MagicMock(return_value=None),
        "debate_newEmptyPane": MagicMock(side_effect=["pane-r1-0", "pane-r1-1", "pane-r2-0", "pane-r2-1", "pane-synth"]),
        "debate_launchAgentsParallel": MagicMock(return_value=0),
        "debate_waitForOutputs": MagicMock(return_value=0),
        "debate_buildClaudePrompts": MagicMock(return_value=None),
        "debate_launchAgent": MagicMock(return_value=0),
        "debate_sendPromptToAgent": MagicMock(return_value=0),
        "debate_agentLaunchCmd": MagicMock(return_value="claude --cmd"),
        "debate_agentReadyMarker": MagicMock(return_value="READY"),
        "debate_archive": MagicMock(return_value=None),
        "shell_waitForFile": MagicMock(return_value=0),
        "tmux_retile": MagicMock(return_value=None),
        "tmux_killPane": MagicMock(return_value=None),
    }
    if overrides:
        targets.update(overrides)
    for name, mock in targets.items():
        monkeypatch.setattr(_MOD_DAEMON, name, mock)
    return targets


def _base_kwargs_daemon(tmp_path):
    return dict(
        debate_dir=tmp_path,
        session="test-session",
        window_target="test-session:0",
        agents=["alpha", "beta"],
        stage_timeout=30,
        plugin_root="/fake/plugin_root",
    )


class TestDaemonMainHappyPath:
    def test_happy_path_two_agents_returns_zero(self, monkeypatch, tmp_path):
        # Scenario: full 2-agent debate with no pre-existing synthesis.md.
        # Setup: all deps succeed; shell_waitForFile creates synthesis.md.
        mocks = _patch_all_daemon(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth output")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect
        kwargs = _base_kwargs_daemon(tmp_path)

        # Test action:
        result = debate_daemonMain(**kwargs)

        # Test verification:
        assert result == 0
        mocks["debate_launchAgentsParallel"].assert_any_call("r1", ["pane-r1-0", "pane-r1-1"])
        mocks["debate_launchAgentsParallel"].assert_any_call("r2", ["pane-r2-0", "pane-r2-1"])
        mocks["debate_launchAgent"].assert_called_once()
        mocks["debate_archive"].assert_called_once()

    def test_happy_path_calls_init_agent_models(self, monkeypatch, tmp_path):
        # Scenario: debate_initAgentModels is always called first.
        # Setup: standard success path.
        mocks = _patch_all_daemon(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        # Test action:
        debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        mocks["debate_initAgentModels"].assert_called_once_with()


class TestDaemonMainDriftWipesFiles:
    def test_drift_true_unlinks_r2_and_synthesis_instructions(self, monkeypatch, tmp_path):
        # Scenario: composition_drifted=True causes stale artifacts to be removed.
        # Setup: create r2 and synthesis_instructions files in debate_dir.
        (tmp_path / "r2_alpha.md").write_text("old r2")
        (tmp_path / "r2_instructions_alpha.txt").write_text("old r2 instr")
        (tmp_path / ".r2_alpha.lock").write_text("lock")
        (tmp_path / "synthesis_instructions.txt").write_text("old synth instr")
        mocks = _patch_all_daemon(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        # Test action:
        debate_daemonMain(**_base_kwargs_daemon(tmp_path), composition_drifted=True)

        # Test verification:
        assert not (tmp_path / "r2_alpha.md").exists()
        assert not (tmp_path / "r2_instructions_alpha.txt").exists()
        assert not (tmp_path / ".r2_alpha.lock").exists()
        assert not (tmp_path / "synthesis_instructions.txt").exists()

    def test_drift_false_leaves_files_intact(self, monkeypatch, tmp_path):
        # Scenario: composition_drifted=False does not delete any artifact.
        # Setup: r2 artifacts present; r2_instructions for both agents.
        (tmp_path / "r2_alpha.md").write_text("kept")
        (tmp_path / "r2_instructions_alpha.txt").write_text("kept")
        (tmp_path / "r2_instructions_beta.txt").write_text("kept")
        mocks = _patch_all_daemon(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        # Test action:
        debate_daemonMain(**_base_kwargs_daemon(tmp_path), composition_drifted=False)

        # Test verification:
        assert (tmp_path / "r2_alpha.md").exists()
        assert (tmp_path / "r2_instructions_alpha.txt").exists()


class TestDaemonMainMissingR2Instructions:
    def test_missing_r2_instructions_triggers_build(self, monkeypatch, tmp_path):
        # Scenario: agents without r2_instructions_*.txt cause build calls.
        # Setup: only alpha has r2 instructions; beta does not.
        (tmp_path / "r2_instructions_alpha.txt").write_text("alpha instr")
        mocks = _patch_all_daemon(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        # Test action:
        debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification: build called for beta only (r2 stage).
        r2_calls = [
            c for c in mocks["debate_buildClaudePrompts"].call_args_list
            if c.kwargs.get("stage") == "r2"
        ]
        assert len(r2_calls) == 1
        assert r2_calls[0].kwargs["agent_filter"] == "beta"

    def test_present_r2_instructions_skips_build(self, monkeypatch, tmp_path):
        # Scenario: all agents have r2 instructions -- no r2 build call expected.
        # Setup: r2_instructions for both agents.
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all_daemon(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        # Test action:
        debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        r2_build_calls = [
            c for c in mocks["debate_buildClaudePrompts"].call_args_list
            if c.kwargs.get("stage") == "r2"
        ]
        assert len(r2_build_calls) == 0


class TestDaemonMainSynthesisAlreadyComplete:
    def test_nonempty_synthesis_md_skips_launch_and_returns_zero(self, monkeypatch, tmp_path):
        # Scenario: synthesis.md exists and is non-empty -- skip synth launch, archive, return 0.
        # Setup: write non-empty synthesis.md before calling daemon_main.
        (tmp_path / "synthesis.md").write_text("existing synthesis")
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all_daemon(monkeypatch)
        mocks["debate_newEmptyPane"].side_effect = ["pane-r1-0", "pane-r1-1", "pane-r2-0", "pane-r2-1"]

        # Test action:
        result = debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        assert result == 0
        mocks["debate_launchAgent"].assert_not_called()
        mocks["debate_archive"].assert_called_once()

    def test_empty_synthesis_md_does_not_short_circuit(self, monkeypatch, tmp_path):
        # Scenario: synthesis.md exists but is empty (size=0) -- do NOT short-circuit.
        # Setup: zero-byte synthesis.md.
        (tmp_path / "synthesis.md").write_bytes(b"")
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all_daemon(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        # Test action:
        debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification: synth launch was reached.
        mocks["debate_launchAgent"].assert_called_once()


class TestDaemonMainLaunchFailure:
    def test_r1_launch_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: R1 launch fails -- returns 1 immediately.
        # Setup: debate_launchAgentsParallel returns 1 on first call.
        mocks = _patch_all_daemon(monkeypatch, {
            "debate_launchAgentsParallel": MagicMock(return_value=1),
        })

        # Test action:
        result = debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        assert result == 1
        assert mocks["debate_launchAgentsParallel"].call_count == 1

    def test_r1_wait_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: R1 wait_for_outputs fails -- returns 1.
        # Setup: wait returns 1 on first call.
        mocks = _patch_all_daemon(monkeypatch, {
            "debate_waitForOutputs": MagicMock(return_value=1),
        })

        # Test action:
        result = debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        assert result == 1

    def test_r2_launch_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: R2 launch fails after R1 succeeds -- returns 1.
        # Setup: first parallel launch succeeds, second fails.
        mocks = _patch_all_daemon(monkeypatch, {
            "debate_launchAgentsParallel": MagicMock(side_effect=[0, 1]),
        })

        # Test action:
        result = debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        assert result == 1
        assert mocks["debate_launchAgentsParallel"].call_count == 2

    def test_synth_launch_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: synthesis launch agent fails -- returns 1.
        # Setup: r2 instructions present; debate_launchAgent returns 1.
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all_daemon(monkeypatch, {
            "debate_launchAgent": MagicMock(return_value=1),
        })

        # Test action:
        result = debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        assert result == 1
        mocks["debate_archive"].assert_not_called()

    def test_synth_wait_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: shell_waitForFile for synthesis.md times out -- returns 1.
        # Setup: r2 instructions present; shell_waitForFile returns 1.
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all_daemon(monkeypatch, {
            "shell_waitForFile": MagicMock(return_value=1),
        })

        # Test action:
        result = debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        assert result == 1
        mocks["debate_archive"].assert_not_called()

    def test_send_prompt_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: send_prompt_to_agent fails for synthesis -- returns 1.
        # Setup: r2 instructions present; debate_sendPromptToAgent returns 1.
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all_daemon(monkeypatch, {
            "debate_sendPromptToAgent": MagicMock(return_value=1),
        })

        # Test action:
        result = debate_daemonMain(**_base_kwargs_daemon(tmp_path))

        # Test verification:
        assert result == 1


# =====================================================================
# debate_launchAgentsParallel tests [daemon -- launchAll]
# =====================================================================


def _patch_deps(
    monkeypatch,
    *,
    launch_return: bool = True,
    send_return: int = 0,
):
    """Patch all in-flight dep functions on the module under test."""
    mock_launch = MagicMock(return_value=launch_return)
    mock_send = MagicMock(return_value=send_return)
    mock_kill = MagicMock(return_value=0)
    mock_launch_cmd = MagicMock(side_effect=lambda a: _LAUNCH_CMD.get(a, "unknown"))
    mock_ready_marker = MagicMock(side_effect=lambda a: _READY_MARKER.get(a, ""))

    monkeypatch.setattr("common.scripts.debate_lib.debate_launchAgent", mock_launch)
    monkeypatch.setattr("common.scripts.debate_lib.debate_sendPromptToAgent", mock_send)
    monkeypatch.setattr("common.scripts.debate_lib.tmux_killPane", mock_kill)
    monkeypatch.setattr("common.scripts.debate_lib.debate_agentLaunchCmd", mock_launch_cmd)
    monkeypatch.setattr("common.scripts.debate_lib.debate_agentReadyMarker", mock_ready_marker)

    return mock_launch, mock_send, mock_kill


_STAGE = "r1"
_PANES = ["%1", "%2"]
_AGENTS = ["claude", "gemini"]
_LAUNCH_CMD = {"claude": "claude --settings /tmp/s.json", "gemini": "gemini --settings /tmp/g.json"}
_READY_MARKER = {"claude": "Claude Code v", "gemini": "Gemini CLI v"}


def test_happy_path_two_agents_returns_zero(monkeypatch, tmp_path):
    # Scenario: two agents, no skip conditions; both workers succeed.
    # Setup: no output files, no lock files; launch and send return success.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=True, send_return=0)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: returns 0, both agents launched and prompted.
    assert rc == 0
    assert mock_launch.call_count == 2
    assert mock_send.call_count == 2
    mock_kill.assert_not_called()


def test_skip_when_output_file_exists(monkeypatch, tmp_path):
    # Scenario: output file for first agent exists and is non-empty; agent is skipped.
    # Setup: create non-empty output file for agent[0].
    output = tmp_path / f"{_STAGE}_{_AGENTS[0]}.md"
    output.write_text("previous result")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: kill called for skipped pane; only second agent launched.
    mock_kill.assert_any_call(_PANES[0])
    assert mock_launch.call_count == 1
    assert rc == 0


def test_skip_when_lock_file_exists(monkeypatch, tmp_path):
    # Scenario: lock file held for second agent; that agent is skipped.
    # Setup: create lock file for agent[1].
    lock = tmp_path / f".{_STAGE}_{_AGENTS[1]}.lock"
    lock.write_text("debate:%2")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: kill called for locked pane; only first agent launched.
    mock_kill.assert_any_call(_PANES[1])
    assert mock_launch.call_count == 1
    assert rc == 0


def test_partial_failure_returns_one(monkeypatch, tmp_path):
    # Scenario: one worker's send_prompt returns non-zero; overall result is 1.
    # Setup: launch succeeds; send_prompt returns 1 for all calls (simulates failure).
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=True, send_return=1)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: at least one failure => returns 1.
    assert rc == 1


def test_empty_agents_list_returns_zero(monkeypatch, tmp_path):
    # Scenario: no agents provided; no workers launched; wall-time log still emitted.
    # Setup: empty panes and agents lists.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, [], [], tmp_path)

    # Test verification: no calls to any worker dep; returns 0.
    assert rc == 0
    mock_launch.assert_not_called()
    mock_send.assert_not_called()
    mock_kill.assert_not_called()


def test_launch_failure_returns_one(monkeypatch, tmp_path):
    # Scenario: debate_launchAgent returns False for one agent; worker returns 1.
    # Setup: launch returns False (timeout or error); send should not be called.
    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch, launch_return=False, send_return=0)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES[:1], _AGENTS[:1], tmp_path)

    # Test verification: returns 1; send never called because launch failed.
    assert rc == 1
    mock_send.assert_not_called()


def test_empty_output_file_does_not_skip(monkeypatch, tmp_path):
    # Scenario: output file exists but is empty (0 bytes); agent must NOT be skipped.
    # Setup: create zero-byte output file for agent[0].
    output = tmp_path / f"{_STAGE}_{_AGENTS[0]}.md"
    output.write_text("")

    mock_launch, mock_send, mock_kill = _patch_deps(monkeypatch)

    # Test action:
    rc = debate_launchAgentsParallel(_STAGE, _PANES, _AGENTS, tmp_path)

    # Test verification: both agents launched (empty file is not "complete").
    assert mock_launch.call_count == 2
    assert rc == 0
