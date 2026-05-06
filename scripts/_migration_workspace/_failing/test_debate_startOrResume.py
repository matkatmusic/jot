"""
Tests for debate_startOrResume.

Naming convention: debate_behaviorUsingCamelCase
Each test covers exactly one behavior.
All subprocess calls and imported dependencies are mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level patch target aliases (avoids repetition)
# ---------------------------------------------------------------------------
_MOD = "_tmp_debate_startOrResume"


def _make_subject(tmp_path: Path, *, resuming: bool = False) -> dict:
    """Return a minimal valid kwargs dict for debate_startOrResume."""
    return dict(
        debate_dir=tmp_path,
        available_agents=["claude", "gemini"],
        resuming=resuming,
        cwd="/repo",
        repo_root="/repo",
        settings_file="/repo/settings.json",
        log_file="/repo/debate.log",
        plugin_root="/repo/plugin",
        gemini_model="gemini-2.0",
        codex_model="codex-001",
    )


# ---------------------------------------------------------------------------
# Happy path: fresh start
# ---------------------------------------------------------------------------
class TestFreshStart:
    # Scenario: A brand-new debate with no existing instruction files.
    # All prompt stages must be built, daemon launched, terminal spawned, emit sent.

    def test_all_r1_prompts_built_when_files_missing(self, tmp_path):
        # Setup: debate_dir exists but contains no instruction files.
        kwargs = _make_subject(tmp_path)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action: invoke with no existing files.
            debate_startOrResume(**kwargs)

            # Test verification: r1 built for each agent.
            r1_calls = [
                c for c in mock_prompts.call_args_list if c.kwargs.get("stage") == "r1"
            ]
            assert len(r1_calls) == 2

    def test_r2_prompts_built_when_files_missing(self, tmp_path):
        # Scenario: fresh start -- r2 instruction files are absent.
        # Setup: no files in debate_dir.
        kwargs = _make_subject(tmp_path)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: r2 built for each agent.
            r2_calls = [
                c for c in mock_prompts.call_args_list if c.kwargs.get("stage") == "r2"
            ]
            assert len(r2_calls) == 2

    def test_synthesis_prompt_built_when_file_missing(self, tmp_path):
        # Scenario: fresh start -- synthesis_instructions.txt is absent.
        # Setup: empty debate_dir.
        kwargs = _make_subject(tmp_path)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: synthesis stage called once.
            synth_calls = [
                c
                for c in mock_prompts.call_args_list
                if c.kwargs.get("stage") == "synthesis"
            ]
            assert len(synth_calls) == 1

    def test_daemon_launched_with_start_new_session(self, tmp_path):
        # Scenario: daemon must be fully detached (replaces bash `& disown`).
        # Setup: empty debate_dir, claim returns "debate-0".
        kwargs = _make_subject(tmp_path)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts"),
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen") as mock_popen,
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: Popen called with start_new_session=True.
            assert mock_popen.call_count == 1
            _, pkwargs = mock_popen.call_args
            assert pkwargs["start_new_session"] is True

    def test_emit_block_says_spawned_on_fresh_start(self, tmp_path):
        # Scenario: emit text must include "spawned" (not "resumed") on a new debate.
        # Setup: resuming=False.
        kwargs = _make_subject(tmp_path, resuming=False)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts"),
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD}.hookjson_emitBlock") as mock_emit,
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: final emit contains "spawned".
            emit_text: str = mock_emit.call_args_list[-1].args[0]
            assert "spawned" in emit_text
            assert "resumed" not in emit_text


# ---------------------------------------------------------------------------
# Resume with no drift
# ---------------------------------------------------------------------------
class TestResumeNoDrift:
    # Scenario: resuming a debate where the agent roster has not changed.

    def test_composition_drifted_false_when_agents_match(self, tmp_path):
        # Setup: create r1 files that exactly match available_agents.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")
        (tmp_path / "r1_instructions_gemini.txt").write_text("x")
        # Also create r2/synthesis so prompt build is skipped.
        (tmp_path / "r2_instructions_claude.txt").write_text("x")
        (tmp_path / "r2_instructions_gemini.txt").write_text("x")
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject(tmp_path, resuming=True)

        captured_env: dict = {}

        def fake_popen(cmd, **kw):
            captured_env.update(kw.get("env", {}))
            return MagicMock()

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts"),
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-1"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen", side_effect=fake_popen),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: daemon receives COMPOSITION_DRIFTED=0.
            assert captured_env.get("COMPOSITION_DRIFTED") == "0"

    def test_prompts_skipped_when_all_files_exist(self, tmp_path):
        # Scenario: no prompt rebuilds when all instruction files are present.
        # Setup: pre-create every instruction file.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")
        (tmp_path / "r1_instructions_gemini.txt").write_text("x")
        (tmp_path / "r2_instructions_claude.txt").write_text("x")
        (tmp_path / "r2_instructions_gemini.txt").write_text("x")
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject(tmp_path, resuming=True)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-1"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: no prompt build calls at all.
            assert mock_prompts.call_count == 0

    def test_emit_block_says_resumed(self, tmp_path):
        # Scenario: final emit must say "resumed" when resuming=True.
        # Setup: pre-create files to avoid triggering prompt builds.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")
        (tmp_path / "r1_instructions_gemini.txt").write_text("x")
        (tmp_path / "r2_instructions_claude.txt").write_text("x")
        (tmp_path / "r2_instructions_gemini.txt").write_text("x")
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject(tmp_path, resuming=True)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts"),
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-1"),
            patch(f"{_MOD}.hookjson_emitBlock") as mock_emit,
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: final emit contains "resumed".
            emit_text: str = mock_emit.call_args_list[-1].args[0]
            assert "resumed" in emit_text


# ---------------------------------------------------------------------------
# Resume with drift
# ---------------------------------------------------------------------------
class TestResumeWithDrift:
    # Scenario: resuming a debate where the agent roster has changed.

    def test_composition_drifted_true_when_agents_differ(self, tmp_path):
        # Setup: r1 files only have "claude" on disk, but "gemini" is new.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")
        # Note: gemini is absent -- so sets differ.
        (tmp_path / "r2_instructions_claude.txt").write_text("x")
        (tmp_path / "r2_instructions_gemini.txt").write_text("x")
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject(tmp_path, resuming=True)

        captured_env: dict = {}

        def fake_popen(cmd, **kw):
            captured_env.update(kw.get("env", {}))
            return MagicMock()

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts"),
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-2"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen", side_effect=fake_popen),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: daemon receives COMPOSITION_DRIFTED=1.
            assert captured_env.get("COMPOSITION_DRIFTED") == "1"


# ---------------------------------------------------------------------------
# Claim failure
# ---------------------------------------------------------------------------
class TestClaimFailure:
    # Scenario: debate_claimSession returns falsy -- must emit error and exit 0.

    def test_exits_zero_and_emits_error_on_claim_failure(self, tmp_path):
        # Setup: claim returns None (falsy).
        kwargs = _make_subject(tmp_path)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts"),
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value=None),
            patch(f"{_MOD}.hookjson_emitBlock") as mock_emit,
            patch(f"{_MOD}.terminal_spawnIfNeeded") as mock_terminal,
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen") as mock_popen,
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action: must raise SystemExit(0).
            with pytest.raises(SystemExit) as exc_info:
                debate_startOrResume(**kwargs)

            # Test verification: exit code is 0, error emitted, daemon NOT launched.
            assert exc_info.value.code == 0
            assert mock_emit.call_count == 1
            error_text: str = mock_emit.call_args.args[0]
            assert "could not claim" in error_text
            mock_popen.assert_not_called()
            mock_terminal.assert_not_called()


# ---------------------------------------------------------------------------
# Prompt build skipped when files already exist
# ---------------------------------------------------------------------------
class TestPromptBuildSkippedWhenFilesExist:
    # Scenario: only build prompts for the stages that are actually missing.

    def test_only_missing_r1_is_built(self, tmp_path):
        # Setup: claude r1 exists, gemini r1 is absent.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")
        # r2 and synthesis absent -- irrelevant to this specific behavior.

        kwargs = _make_subject(tmp_path)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: r1 called exactly once (only for gemini).
            r1_calls = [
                c for c in mock_prompts.call_args_list if c.kwargs.get("stage") == "r1"
            ]
            assert len(r1_calls) == 1
            assert r1_calls[0].kwargs["agent_filter"] == "gemini"

    def test_synthesis_not_built_when_file_exists(self, tmp_path):
        # Scenario: synthesis_instructions.txt already present -- skip build.
        # Setup: only synthesis file exists; r1/r2 absent (they will be built,
        # but we only assert synthesis is NOT built).
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject(tmp_path)

        with (
            patch(f"{_MOD}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD}.debate_buildClaudeCmd"),
            patch(f"{_MOD}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD}.hookjson_emitBlock"),
            patch(f"{_MOD}.terminal_spawnIfNeeded"),
            patch(f"{_MOD}.subprocess.run"),
            patch(f"{_MOD}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            from _tmp_debate_startOrResume import debate_startOrResume

            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: no synthesis call.
            synth_calls = [
                c
                for c in mock_prompts.call_args_list
                if c.kwargs.get("stage") == "synthesis"
            ]
            assert len(synth_calls) == 0
