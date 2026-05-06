"""
Tests for debate_daemonMain.

All deps are monkeypatched -- no real tmux, filesystem, or subprocess calls.
Synthesis.md existence/size is simulated via tmp_path fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODULE = "_tmp_debate_daemonMain"


def _patch_all(monkeypatch: pytest.MonkeyPatch, overrides: dict | None = None) -> dict[str, MagicMock]:
    """Return a dict of all patched callables with sensible defaults (rc=0)."""
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
        monkeypatch.setattr(MODULE, name, mock)
    return targets


def _base_kwargs(tmp_path: Path) -> dict:
    return dict(
        debate_dir=tmp_path,
        session="test-session",
        window_target="test-session:0",
        agents=["alpha", "beta"],
        stage_timeout=30,
        plugin_root="/fake/plugin_root",
    )


# ---------------------------------------------------------------------------
# Ensure the module is importable (workspace path on sys.path)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def workspace_on_path():
    workspace = str(Path(__file__).parent)
    if workspace not in sys.path:
        sys.path.insert(0, workspace)
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_happy_path_two_agents_returns_zero(self, monkeypatch, tmp_path):
        # Scenario: full 2-agent debate with no pre-existing synthesis.md
        # Setup: all deps succeed; synthesis.md does not exist pre-run; created by shell_waitForFile side-effect
        mocks = _patch_all(monkeypatch)
        # shell_waitForFile side-effect: create synthesis.md so archive sees it
        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth output")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect
        # Also need synthesis_instructions.txt absent so build is triggered
        kwargs = _base_kwargs(tmp_path)

        # Test action:
        from _tmp_debate_daemonMain import debate_daemonMain
        result = debate_daemonMain(**kwargs)

        # Test verification:
        assert result == 0
        mocks["debate_launchAgentsParallel"].assert_any_call("r1", ["pane-r1-0", "pane-r1-1"])
        mocks["debate_launchAgentsParallel"].assert_any_call("r2", ["pane-r2-0", "pane-r2-1"])
        mocks["debate_launchAgent"].assert_called_once()
        mocks["debate_archive"].assert_called_once()

    def test_happy_path_calls_init_agent_models(self, monkeypatch, tmp_path):
        # Scenario: debate_initAgentModels is always called first
        # Setup: standard success path
        mocks = _patch_all(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        from _tmp_debate_daemonMain import debate_daemonMain
        debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        mocks["debate_initAgentModels"].assert_called_once_with()


class TestDriftWipesFiles:
    def test_drift_true_unlinks_r2_and_synthesis_instructions(self, monkeypatch, tmp_path):
        # Scenario: composition_drifted=True causes stale artifacts to be removed
        # Setup: create r2 and synthesis_instructions files in debate_dir
        (tmp_path / "r2_alpha.md").write_text("old r2")
        (tmp_path / "r2_instructions_alpha.txt").write_text("old r2 instr")
        (tmp_path / ".r2_alpha.lock").write_text("lock")
        (tmp_path / "synthesis_instructions.txt").write_text("old synth instr")
        mocks = _patch_all(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        debate_daemonMain(**_base_kwargs(tmp_path), composition_drifted=True)

        # Test verification:
        assert not (tmp_path / "r2_alpha.md").exists()
        assert not (tmp_path / "r2_instructions_alpha.txt").exists()
        assert not (tmp_path / ".r2_alpha.lock").exists()
        assert not (tmp_path / "synthesis_instructions.txt").exists()

    def test_drift_false_leaves_files_intact(self, monkeypatch, tmp_path):
        # Scenario: composition_drifted=False does not delete any artifact
        # Setup: create stale r2 artifacts; r2_instructions present so build is skipped
        (tmp_path / "r2_alpha.md").write_text("kept")
        (tmp_path / "r2_instructions_alpha.txt").write_text("kept")
        (tmp_path / "r2_instructions_beta.txt").write_text("kept")
        mocks = _patch_all(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        debate_daemonMain(**_base_kwargs(tmp_path), composition_drifted=False)

        # Test verification:
        assert (tmp_path / "r2_alpha.md").exists()
        assert (tmp_path / "r2_instructions_alpha.txt").exists()


class TestMissingR2Instructions:
    def test_missing_r2_instructions_triggers_build(self, monkeypatch, tmp_path):
        # Scenario: agents without r2_instructions_*.txt cause debate_buildClaudePrompts to be called
        # Setup: only alpha has r2 instructions; beta does not
        (tmp_path / "r2_instructions_alpha.txt").write_text("alpha instr")
        mocks = _patch_all(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification: build called for beta only (r2 stage) + synthesis stage
        r2_calls = [
            c for c in mocks["debate_buildClaudePrompts"].call_args_list
            if c.kwargs.get("stage") == "r2"
        ]
        assert len(r2_calls) == 1
        assert r2_calls[0].kwargs["agent_filter"] == "beta"

    def test_present_r2_instructions_skips_build(self, monkeypatch, tmp_path):
        # Scenario: all agents have r2 instructions -- no r2 build call expected
        # Setup: create r2_instructions for both agents
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        r2_build_calls = [
            c for c in mocks["debate_buildClaudePrompts"].call_args_list
            if c.kwargs.get("stage") == "r2"
        ]
        assert len(r2_build_calls) == 0


class TestSynthesisAlreadyComplete:
    def test_nonempty_synthesis_md_skips_launch_and_returns_zero(self, monkeypatch, tmp_path):
        # Scenario: synthesis.md exists and is non-empty -- skip synth launch, archive, return 0
        # Setup: write non-empty synthesis.md before calling daemon_main
        (tmp_path / "synthesis.md").write_text("existing synthesis")
        # r2_instructions present so no extra build calls
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all(monkeypatch)
        # newEmptyPane only needs R1+R2 panes (4 total), not synth
        mocks["debate_newEmptyPane"].side_effect = ["pane-r1-0", "pane-r1-1", "pane-r2-0", "pane-r2-1"]

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        result = debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        assert result == 0
        mocks["debate_launchAgent"].assert_not_called()
        mocks["debate_archive"].assert_called_once()

    def test_empty_synthesis_md_does_not_short_circuit(self, monkeypatch, tmp_path):
        # Scenario: synthesis.md exists but is empty (size=0) -- do NOT short-circuit
        # Setup: write zero-byte synthesis.md
        (tmp_path / "synthesis.md").write_bytes(b"")
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all(monkeypatch)

        def _wait_side_effect(path, timeout):
            Path(path).write_text("synth")
            return 0
        mocks["shell_waitForFile"].side_effect = _wait_side_effect

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification: synth launch was reached
        mocks["debate_launchAgent"].assert_called_once()


class TestLaunchFailure:
    def test_r1_launch_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: R1 launch fails -- function returns 1 immediately
        # Setup: debate_launchAgentsParallel returns 1 on first call
        mocks = _patch_all(monkeypatch, {
            "debate_launchAgentsParallel": MagicMock(return_value=1),
        })

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        result = debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        assert result == 1
        # R2 never started
        assert mocks["debate_launchAgentsParallel"].call_count == 1

    def test_r1_wait_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: R1 wait_for_outputs fails -- returns 1
        # Setup: wait returns 1 on first call
        mocks = _patch_all(monkeypatch, {
            "debate_waitForOutputs": MagicMock(return_value=1),
        })

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        result = debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        assert result == 1

    def test_r2_launch_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: R2 launch fails after R1 succeeds -- returns 1
        # Setup: first parallel launch succeeds, second fails
        mocks = _patch_all(monkeypatch, {
            "debate_launchAgentsParallel": MagicMock(side_effect=[0, 1]),
        })

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        result = debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        assert result == 1
        assert mocks["debate_launchAgentsParallel"].call_count == 2

    def test_synth_launch_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: synthesis launch agent fails -- returns 1
        # Setup: r2 instructions present; debate_launchAgent returns 1
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all(monkeypatch, {
            "debate_launchAgent": MagicMock(return_value=1),
        })

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        result = debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        assert result == 1
        mocks["debate_archive"].assert_not_called()

    def test_synth_wait_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: shell_waitForFile for synthesis.md times out -- returns 1
        # Setup: r2 instructions present; shell_waitForFile returns 1
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all(monkeypatch, {
            "shell_waitForFile": MagicMock(return_value=1),
        })

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        result = debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        assert result == 1
        mocks["debate_archive"].assert_not_called()

    def test_send_prompt_failure_returns_one(self, monkeypatch, tmp_path):
        # Scenario: send_prompt_to_agent fails for synthesis -- returns 1
        # Setup: r2 instructions present; debate_sendPromptToAgent returns 1
        (tmp_path / "r2_instructions_alpha.txt").write_text("a")
        (tmp_path / "r2_instructions_beta.txt").write_text("b")
        mocks = _patch_all(monkeypatch, {
            "debate_sendPromptToAgent": MagicMock(return_value=1),
        })

        from _tmp_debate_daemonMain import debate_daemonMain

        # Test action:
        result = debate_daemonMain(**_base_kwargs(tmp_path))

        # Test verification:
        assert result == 1
