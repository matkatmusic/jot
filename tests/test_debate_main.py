"""Tests for debate_lib (and debate-related orchestrator functions) -- main bucket."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from unittest.mock import MagicMock, mock_open, patch

from common.scripts.util_lib import _valid_kwargs

from common.scripts.debate_lib import (
    DebateContext,
    debate_buildClaudeCmd,
    debate_initHookContext,
    debate_launch,
    debate_startOrResume,
    debate_tmuxOrchestrator,
)

# Bind module aliases used throughout the test bodies.
from common.scripts import debate_lib as mod
from common.scripts import debate_lib as sut


# =====================================================================
# debate_startOrResume tests
# =====================================================================

_MOD_DEBATE_SOR = "common.scripts.debate_lib"


def _make_subject_sor(tmp_path: Path, *, resuming: bool = False) -> dict:
    # Return a minimal valid kwargs dict for debate_startOrResume.
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


class TestDebateStartOrResumeFreshStart:
    # Scenario: A brand-new debate with no existing instruction files.

    def test_all_r1_prompts_built_when_files_missing(self, tmp_path):
        # Setup: debate_dir exists but contains no instruction files.
        kwargs = _make_subject_sor(tmp_path)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
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
        kwargs = _make_subject_sor(tmp_path)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
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
        kwargs = _make_subject_sor(tmp_path)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
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
        kwargs = _make_subject_sor(tmp_path)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts"),
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen") as mock_popen,
            patch("builtins.open", mock_open()),
        ):
            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: Popen called with start_new_session=True.
            assert mock_popen.call_count == 1
            _, pkwargs = mock_popen.call_args
            assert pkwargs["start_new_session"] is True

    def test_emit_block_says_spawned_on_fresh_start(self, tmp_path):
        # Scenario: emit text must include "spawned" (not "resumed") on a new debate.
        # Setup: resuming=False.
        kwargs = _make_subject_sor(tmp_path, resuming=False)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts"),
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock") as mock_emit,
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: final emit contains "spawned".
            emit_text: str = mock_emit.call_args_list[-1].args[0]
            assert "spawned" in emit_text
            assert "resumed" not in emit_text


class TestDebateStartOrResumeNoDrift:
    # Scenario: resuming a debate where the agent roster has not changed.

    def test_composition_drifted_false_when_agents_match(self, tmp_path):
        # Setup: create r1 files that exactly match available_agents.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")
        (tmp_path / "r1_instructions_gemini.txt").write_text("x")
        (tmp_path / "r2_instructions_claude.txt").write_text("x")
        (tmp_path / "r2_instructions_gemini.txt").write_text("x")
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject_sor(tmp_path, resuming=True)

        captured_env: dict = {}

        def fake_popen(cmd, **kw):
            captured_env.update(kw.get("env", {}))
            return MagicMock()

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts"),
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-1"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen", side_effect=fake_popen),
            patch("builtins.open", mock_open()),
        ):
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

        kwargs = _make_subject_sor(tmp_path, resuming=True)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-1"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
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

        kwargs = _make_subject_sor(tmp_path, resuming=True)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts"),
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-1"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock") as mock_emit,
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: final emit contains "resumed".
            emit_text: str = mock_emit.call_args_list[-1].args[0]
            assert "resumed" in emit_text


class TestDebateStartOrResumeWithDrift:
    # Scenario: resuming a debate where the agent roster has changed.

    def test_composition_drifted_true_when_agents_differ(self, tmp_path):
        # Setup: r1 files only have "claude" on disk, but "gemini" is new.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")
        (tmp_path / "r2_instructions_claude.txt").write_text("x")
        (tmp_path / "r2_instructions_gemini.txt").write_text("x")
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject_sor(tmp_path, resuming=True)

        captured_env: dict = {}

        def fake_popen(cmd, **kw):
            captured_env.update(kw.get("env", {}))
            return MagicMock()

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts"),
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-2"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen", side_effect=fake_popen),
            patch("builtins.open", mock_open()),
        ):
            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: daemon receives COMPOSITION_DRIFTED=1.
            assert captured_env.get("COMPOSITION_DRIFTED") == "1"


class TestDebateStartOrResumeClaimFailure:
    # Scenario: debate_claimSession returns falsy -- must emit error and exit 0.

    def test_exits_zero_and_emits_error_on_claim_failure(self, tmp_path):
        # Setup: claim returns None (falsy).
        kwargs = _make_subject_sor(tmp_path)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts"),
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value=None),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock") as mock_emit,
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded") as mock_terminal,
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen") as mock_popen,
            patch("builtins.open", mock_open()),
        ):
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


class TestDebateStartOrResumePromptBuildSkipped:
    # Scenario: only build prompts for the stages that are actually missing.

    def test_only_missing_r1_is_built(self, tmp_path):
        # Setup: claude r1 exists, gemini r1 is absent.
        (tmp_path / "r1_instructions_claude.txt").write_text("x")

        kwargs = _make_subject_sor(tmp_path)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
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
        # Setup: only synthesis file exists; r1/r2 absent.
        (tmp_path / "synthesis_instructions.txt").write_text("x")

        kwargs = _make_subject_sor(tmp_path)

        with (
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudePrompts") as mock_prompts,
            patch(f"{_MOD_DEBATE_SOR}.debate_buildClaudeCmd"),
            patch(f"{_MOD_DEBATE_SOR}.debate_claimSession", return_value="debate-0"),
            patch(f"{_MOD_DEBATE_SOR}.hookjson_emitBlock"),
            patch(f"{_MOD_DEBATE_SOR}.terminal_spawnIfNeeded"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.run"),
            patch(f"{_MOD_DEBATE_SOR}.subprocess.Popen"),
            patch("builtins.open", mock_open()),
        ):
            # Test action:
            debate_startOrResume(**kwargs)

            # Test verification: no synthesis call.
            synth_calls = [
                c
                for c in mock_prompts.call_args_list
                if c.kwargs.get("stage") == "synthesis"
            ]
            assert len(synth_calls) == 0


# =====================================================================
# debate_main tests
# =====================================================================

from common.scripts import debate_lib as _mod_dm  # noqa: E402


def _ctx_dm(tmp_path: Path, *, prompt: str, repo_root: str | None = None,
            transcript_path: str = "") -> dict:
    # Build a debate_initHookContext()-shaped dict.
    return {
        "SCRIPTS_DIR": str(tmp_path / "scripts"),
        "LOG_FILE": str(tmp_path / "debate-log.txt"),
        "INPUT": json.dumps({"prompt": prompt, "cwd": str(tmp_path),
                             "transcript_path": transcript_path}),
        "CWD": str(tmp_path),
        "TRANSCRIPT_PATH": transcript_path,
        "REPO_ROOT": str(tmp_path) if repo_root is None else repo_root,
    }


def _detect_dm(available: list[str]) -> dict:
    return {"available": available, "gemini_model": "gem-x", "codex_model": "cdx-y"}


def test_debateMain_non_debate_input_returns_zero(tmp_path):
    # Scenario: hook fires for an unrelated prompt; debate_main must no-op.
    # Setup: context whose INPUT does not contain the literal '"/debate'.
    ctx = {
        "SCRIPTS_DIR": "", "LOG_FILE": "", "INPUT": '{"prompt":"hello"}',
        "CWD": str(tmp_path), "TRANSCRIPT_PATH": "", "REPO_ROOT": str(tmp_path),
    }
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "hookjson_emitBlock") as emit, \
         patch.object(_mod_dm, "debate_startOrResume") as start:
        # Test action: invoke debate_main.
        rc = _mod_dm.debate_main()
    # Test verification: rc 0, no emit, no dispatch.
    assert rc == 0
    emit.assert_not_called()
    start.assert_not_called()


def test_debateMain_missing_topic_emits_usage(tmp_path):
    # Scenario: prompt is bare '/debate' with no topic argument.
    # Setup: build context and patch deps.
    ctx = _ctx_dm(tmp_path, prompt="/debate")
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "hookjson_emitBlock") as emit, \
         patch.object(_mod_dm, "debate_startOrResume") as start:
        # Test action: run debate_main.
        rc = _mod_dm.debate_main()
    # Test verification: usage message emitted, no dispatch.
    assert rc == 0
    emit.assert_called_once_with("debate: no topic provided. Usage: /debate <topic>")
    start.assert_not_called()


def test_debateMain_missing_repo_emits_block(tmp_path):
    # Scenario: caller is not inside a git repo (REPO_ROOT empty).
    # Setup: context with REPO_ROOT="" but valid topic.
    ctx = _ctx_dm(tmp_path, prompt="/debate should we ship", repo_root="")
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "hookjson_emitBlock") as emit, \
         patch.object(_mod_dm, "debate_startOrResume") as start:
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    emit.assert_called_once_with("debate requires a git repository.")
    start.assert_not_called()


def test_debateMain_existing_with_synthesis_emits_already_complete(tmp_path):
    # Scenario: a prior debate dir for this topic already has synthesis.md.
    # Setup: create a debate dir with synthesis.md and stub findMatching.
    existing = tmp_path / "Debates" / "2026-05-05T00-00-00_topic"
    existing.mkdir(parents=True)
    (existing / "synthesis.md").write_text("done\n")
    ctx = _ctx_dm(tmp_path, prompt="/debate topic")
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "debate_detectAvailableAgents",
                      return_value=_detect_dm(["claude", "gemini"])), \
         patch.object(_mod_dm, "debate_findMatching", return_value=str(existing)), \
         patch.object(_mod_dm, "hookjson_emitBlock") as emit, \
         patch.object(_mod_dm, "debate_startOrResume") as start:
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    msg = emit.call_args.args[0]
    assert "already complete" in msg
    assert "synthesis.md" in msg
    start.assert_not_called()


def test_debateMain_existing_with_live_lock_emits_already_running(tmp_path):
    # Scenario: existing debate dir is mid-flight; tmux session still live.
    # Setup: dir exists, no synthesis.md, anyLiveLock True, liveSession 'debate-3'.
    existing = tmp_path / "Debates" / "2026-05-05T00-00-00_topic"
    existing.mkdir(parents=True)
    ctx = _ctx_dm(tmp_path, prompt="/debate topic")
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "debate_detectAvailableAgents",
                      return_value=_detect_dm(["claude", "gemini"])), \
         patch.object(_mod_dm, "debate_findMatching", return_value=str(existing)), \
         patch.object(_mod_dm, "debate_anyLiveLock", return_value=True), \
         patch.object(_mod_dm, "debate_liveSession", return_value="debate-3"), \
         patch.object(_mod_dm, "hookjson_emitBlock") as emit, \
         patch.object(_mod_dm, "debate_startOrResume") as start:
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    msg = emit.call_args.args[0]
    assert "already running" in msg
    assert "-> tmux attach -t debate-3" in msg
    start.assert_not_called()


def test_debateMain_existing_without_synthesis_or_lock_resumes(tmp_path):
    # Scenario: stale debate dir survives; resume path must engage.
    # Setup: existing dir with no synthesis.md, anyLiveLock False, FAILED.txt present.
    existing = tmp_path / "Debates" / "2026-05-05T00-00-00_topic"
    existing.mkdir(parents=True)
    (existing / "FAILED.txt").write_text("rip\n")
    ctx = _ctx_dm(tmp_path, prompt="/debate topic")
    feas = MagicMock()
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "debate_detectAvailableAgents",
                      return_value=_detect_dm(["claude", "gemini"])), \
         patch.object(_mod_dm, "debate_findMatching", return_value=str(existing)), \
         patch.object(_mod_dm, "debate_anyLiveLock", return_value=False), \
         patch.object(_mod_dm, "debate_checkResumeFeasibility",
                      return_value=feas) as check, \
         patch.object(_mod_dm, "debate_startOrResume") as start, \
         patch.object(_mod_dm, "hookjson_emitBlock"):
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    check.assert_called_once()
    assert not (existing / "FAILED.txt").exists()
    assert start.call_args.kwargs["resuming"] is True
    assert Path(start.call_args.kwargs["debate_dir"]) == existing


def test_debateMain_fresh_under_two_agents_emits_count_block(tmp_path):
    # Scenario: only one agent passed smoke tests; fresh debate must abort.
    # Setup: findMatching None, available=['claude'].
    ctx = _ctx_dm(tmp_path, prompt="/debate ship it")
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "debate_detectAvailableAgents",
                      return_value=_detect_dm(["claude"])), \
         patch.object(_mod_dm, "debate_findMatching", return_value=None), \
         patch.object(_mod_dm, "hookjson_emitBlock") as emit, \
         patch.object(_mod_dm, "debate_startOrResume") as start:
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    msg = emit.call_args.args[0]
    assert ">=2 agents" in msg
    assert "claude" in msg
    start.assert_not_called()


def test_debateMain_fresh_happy_path_creates_artifacts_and_dispatches(tmp_path):
    # Scenario: clean repo, two agents, no transcript - 'no conversation context' branch.
    # Setup: findMatching None, available=2, transcript_path empty.
    ctx = _ctx_dm(tmp_path, prompt="/debate Should we Adopt Rust?")
    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "debate_detectAvailableAgents",
                      return_value=_detect_dm(["claude", "gemini"])), \
         patch.object(_mod_dm, "debate_findMatching", return_value=None), \
         patch.object(_mod_dm, "debate_startOrResume") as start, \
         patch.object(_mod_dm, "hookjson_emitBlock"):
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    debates_root = tmp_path / "Debates"
    assert debates_root.is_dir()
    created = list(debates_root.iterdir())
    assert len(created) == 1
    debate_dir = created[0]
    assert debate_dir.name.endswith("_should-we-adopt-rust")
    assert (debate_dir / "topic.md").read_text() == "Should we Adopt Rust?\n"
    assert (debate_dir / "context.md").read_text() == "(no conversation context available)\n"
    assert start.call_args.kwargs["resuming"] is False
    assert Path(start.call_args.kwargs["debate_dir"]) == debate_dir


def test_debateMain_fresh_with_transcript_invokes_capture_subprocess(tmp_path, monkeypatch):
    # Scenario: transcript exists and capture script exists - subprocess.run hit.
    # Setup: create transcript file + fake capture script + plugin_root env.
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('{"role":"user"}\n')
    plugin_root = tmp_path / "plugin"
    cap_dir = plugin_root / "skills" / "jot" / "scripts"
    cap_dir.mkdir(parents=True)
    capture_script = cap_dir / "capture-conversation.py"
    capture_script.write_text("# stub\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    ctx = _ctx_dm(tmp_path, prompt="/debate topic", transcript_path=str(transcript))

    def fake_run(cmd, stdout, stderr, check):
        # Test setup: simulate capture writing useful output to context.md handle.
        stdout.write("captured context\n")
        return MagicMock(returncode=0)

    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "debate_detectAvailableAgents",
                      return_value=_detect_dm(["claude", "gemini"])), \
         patch.object(_mod_dm, "debate_findMatching", return_value=None), \
         patch.object(_mod_dm.subprocess, "run", side_effect=fake_run) as run_mock, \
         patch.object(_mod_dm, "debate_startOrResume"), \
         patch.object(_mod_dm, "hookjson_emitBlock"):
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    assert run_mock.call_count == 1
    debate_dir = next((tmp_path / "Debates").iterdir())
    assert (debate_dir / "context.md").read_text() == "captured context\n"
    assert (debate_dir / "invoking_transcript.txt").read_text() == f"{transcript}\n"


def test_debateMain_fresh_capture_failure_writes_failure_marker(tmp_path, monkeypatch):
    # Scenario: capture-conversation.py returns non-zero -> fallback marker.
    # Setup: transcript + script exist; subprocess returns rc=1.
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("x")
    plugin_root = tmp_path / "plugin"
    cap_dir = plugin_root / "skills" / "jot" / "scripts"
    cap_dir.mkdir(parents=True)
    (cap_dir / "capture-conversation.py").write_text("# stub\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    ctx = _ctx_dm(tmp_path, prompt="/debate topic", transcript_path=str(transcript))

    def fake_run(cmd, stdout, stderr, check):
        return MagicMock(returncode=1)

    with patch.object(_mod_dm, "debate_initHookContext", return_value=ctx), \
         patch.object(_mod_dm, "hookjson_checkRequirements"), \
         patch.object(_mod_dm, "debate_detectAvailableAgents",
                      return_value=_detect_dm(["claude", "gemini"])), \
         patch.object(_mod_dm, "debate_findMatching", return_value=None), \
         patch.object(_mod_dm.subprocess, "run", side_effect=fake_run), \
         patch.object(_mod_dm, "debate_startOrResume"), \
         patch.object(_mod_dm, "hookjson_emitBlock"):
        # Test action.
        rc = _mod_dm.debate_main()
    # Test verification.
    assert rc == 0
    debate_dir = next((tmp_path / "Debates").iterdir())
    assert (debate_dir / "context.md").read_text() == "(conversation capture failed)\n"


# =====================================================================
# debate_buildClaudeCmd tests [main]
# =====================================================================


def test_creates_tmpdir_and_settings_file_path(tmp_path, monkeypatch):
    # Scenario: Function provisions a fresh tmpdir under /tmp and returns a
    # settings.json path inside it.
    # Setup: stub permissions_seed (no-op) and expand_permissions ('[]').
    seeded = []
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()
    (tmp_path / "root" / "skills" / "debate" / "scripts" / "assets").mkdir(parents=True)

    def fake_seed(*args, **kwargs):
        seeded.append(args)

    def fake_expand(perm_file, cwd, repo_root, home):
        return "[]"

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=fake_seed,
        expand_permissions_fn=fake_expand,
    )

    # Test verification: tmpdir exists, settings_file lives inside it.
    assert Path(result["tmpdir_inv"]).is_dir()
    assert result["tmpdir_inv"].startswith("/tmp/debate.")
    assert result["settings_file"] == str(Path(result["tmpdir_inv"]) / "settings.json")


def test_writes_settings_json_with_allow_and_empty_hooks(tmp_path, monkeypatch):
    # Scenario: Settings file is written with permissions.allow from
    # expand_permissions output and an empty hooks object.
    # Setup:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()

    allow_value = '["Bash(echo:*)","Read"]'

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: allow_value,
    )

    # Test verification: parse settings.json round-trip.
    body = json.loads(Path(result["settings_file"]).read_text())
    assert body["permissions"]["allow"] == ["Bash(echo:*)", "Read"]
    assert body["hooks"] == {}


def test_returns_claude_cmd_with_settings_and_add_dir(tmp_path, monkeypatch):
    # Scenario: Returned cmd string contains --settings <file> and --add-dir
    # <cwd>, plus a trailing newline (claude_buildCmd contract).
    # Setup:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()
    cwd = str(tmp_path / "work")
    (tmp_path / "work").mkdir()

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=cwd,
        repo_root=cwd,
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    cmd = result["cmd"]
    assert cmd.endswith("\n")
    assert f"--settings '{result['settings_file']}'" in cmd
    assert f"--add-dir '{cwd}'" in cmd
    assert cmd.startswith("claude ")


def test_invokes_permissions_seed_with_expected_paths(tmp_path, monkeypatch):
    # Scenario: permissions_seed is called once with the documented six args.
    # Setup:
    data = tmp_path / "data"
    root = tmp_path / "root"
    data.mkdir()
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    log = str(tmp_path / "log.txt")
    captured = {}

    def fake_seed(perm_file, default_file, default_sha, prior_sha, log_file, label):
        captured["perm_file"] = perm_file
        captured["default_file"] = default_file
        captured["default_sha"] = default_sha
        captured["prior_sha"] = prior_sha
        captured["log_file"] = log_file
        captured["label"] = label

    # Test action:
    debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=log,
        permissions_seed_fn=fake_seed,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    assert captured["perm_file"] == str(data / "debate-permissions.local.json")
    assert captured["default_file"] == str(
        root / "skills/debate/scripts/assets/permissions.default.json"
    )
    assert captured["default_sha"] == str(
        root / "skills/debate/scripts/assets/permissions.default.json.sha256"
    )
    assert captured["prior_sha"] == str(data / "debate-permissions.default.sha256")
    assert captured["log_file"] == log
    assert captured["label"] == "debate"


def test_creates_claude_plugin_data_dir_if_missing(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_DATA dir does not yet exist; function mkdir -p's it.
    # Setup: data dir intentionally NOT created.
    data = tmp_path / "data_nonexistent"
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))

    # Test action:
    debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    assert data.is_dir()


# =====================================================================
# debate_launch tests [main]
# =====================================================================


def _noop() -> None:
    pass


def _make_main_mock() -> MagicMock:
    return MagicMock(return_value=None)


def test_always_calls_debate_main() -> None:
    # Scenario: debate_launch always delegates to debate_main regardless of OS.
    # Setup:
    main_mock = _make_main_mock()
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=lambda: True,
        _launch_terminal_fn=_noop,
    )
    # Test verification:
    main_mock.assert_called_once_with()


def test_skipTerminalCheck_envBypassesDarwinTerminalProbe(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scenario: DEBATE_SKIP_TERMINAL_CHECK=1 must short-circuit the macOS Terminal.app
    # probe entirely, so neither _terminal_running nor _launch_terminal_background
    # fires - even when the platform is Darwin and Terminal is "not running".
    # Setup: env var set, simulate Darwin, sentinel-fail both terminal hooks so any
    # call would raise. Inject debate_main mock so we don't run real orchestration.
    monkeypatch.setenv("DEBATE_SKIP_TERMINAL_CHECK", "1")
    main_mock = _make_main_mock()
    probe_calls: list[bool] = []

    def _explode_probe() -> bool:
        probe_calls.append(True)
        raise AssertionError("terminal probe ran despite DEBATE_SKIP_TERMINAL_CHECK=1")

    def _explode_launch() -> None:
        raise AssertionError("Terminal.app launched despite DEBATE_SKIP_TERMINAL_CHECK=1")

    # Test action: call debate_launch on a "Darwin" platform with the skip env set.
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=_explode_probe,
        _launch_terminal_fn=_explode_launch,
    )
    # Test verification: neither terminal hook ran; debate_main still delegated.
    assert probe_calls == []
    main_mock.assert_called_once_with()


def test_plugin_root_exported_to_environment() -> None:
    # Scenario: debate_launch sets PLUGIN_ROOT env var so debate_main sees it.
    # Setup:
    plugin_root = Path("/my/plugin/root")
    main_mock = _make_main_mock()
    # Remove any pre-existing value so setdefault fires.
    os.environ.pop("PLUGIN_ROOT", None)
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=plugin_root,
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=lambda: True,
        _launch_terminal_fn=_noop,
    )
    # Test verification:
    assert os.environ.get("PLUGIN_ROOT") == str(plugin_root)


# =====================================================================
# debate_tmuxOrchestrator context-build tests [main]
# =====================================================================


def test_raises_when_session_empty() -> None:
    # Scenario: caller passes empty SESSION; orchestrator must abort like bash `:?` guard.
    # Setup: all args valid except session="".
    # Test action: call debate_tmuxOrchestrator with session="".
    # Test verification: ValueError raised with "SESSION required".
    with pytest.raises(ValueError, match="SESSION required"):
        debate_tmuxOrchestrator(**_valid_kwargs(session=""))


def test_raises_when_debate_agents_empty_and_no_env() -> None:
    # Scenario: caller passes empty debate_agents and env var absent; must abort.
    # Setup: no DEBATE_AGENTS env var, debate_agents="".
    # Test action: call with debate_agents="".
    # Test verification: ValueError raised with "DEBATE_AGENTS".
    env = {k: v for k, v in os.environ.items() if k != "DEBATE_AGENTS"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="DEBATE_AGENTS"):
            debate_tmuxOrchestrator(**_valid_kwargs(debate_agents=""))


def test_window_target_composed_from_session_and_window_name() -> None:
    # Scenario: window_target must be "SESSION:WINDOW_NAME" matching bash `WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"`.
    # Setup: inject mock daemon_main; pass distinct session and window_name.
    # Test action: call debate_tmuxOrchestrator with session="mysession" window_name="mywin".
    # Test verification: ctx.window_target == "mysession:mywin".
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(session="mysession", window_name="mywin"),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.window_target == "mysession:mywin"


def test_stage_timeout_is_900_seconds() -> None:
    # Scenario: STAGE_TIMEOUT must be 15*60=900 (bash hard-code).
    # Setup: inject mock daemon_main.
    # Test action: call debate_tmuxOrchestrator with valid args.
    # Test verification: ctx.stage_timeout == 900.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.stage_timeout == 900


def test_agents_parsed_from_space_separated_string() -> None:
    # Scenario: DEBATE_AGENTS is a space-separated string; must be split into list.
    # Setup: debate_agents="claude gemini codex".
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: ctx.agents == ["claude", "gemini", "codex"].
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(debate_agents="claude gemini codex"),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.agents == ["claude", "gemini", "codex"]


def test_daemon_main_called_once_with_context() -> None:
    # Scenario: daemon_main must be called exactly once, receiving the DebateContext.
    # Setup: inject mock daemon_main and cleanup.
    # Test action: call debate_tmuxOrchestrator with valid args.
    # Test verification: mock_daemon called once; arg is DebateContext instance.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    mock_daemon.assert_called_once()
    ctx = mock_daemon.call_args[0][0]
    assert isinstance(ctx, DebateContext)


def test_cleanup_called_even_when_daemon_raises() -> None:
    # Scenario: mirrors `trap cleanup EXIT` -- cleanup runs even if daemon_main raises.
    # Setup: daemon_main raises RuntimeError; inject mock cleanup.
    # Test action: call debate_tmuxOrchestrator; catch the raised error.
    # Test verification: cleanup called exactly once despite the exception.
    mock_cleanup = MagicMock()
    mock_daemon = MagicMock(side_effect=RuntimeError("daemon exploded"))
    with pytest.raises(RuntimeError, match="daemon exploded"):
        debate_tmuxOrchestrator(
            **_valid_kwargs(),
            daemon_main_fn=mock_daemon,
            cleanup_fn=mock_cleanup,
        )
    mock_cleanup.assert_called_once()


def test_returns_zero_on_success() -> None:
    # Scenario: successful run must return 0 (POSIX exit-code convention).
    # Setup: daemon_main and cleanup are no-ops.
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: return value is 0.
    result = debate_tmuxOrchestrator(
        **_valid_kwargs(),
        daemon_main_fn=MagicMock(),
        cleanup_fn=MagicMock(),
    )
    assert result == 0


def test_context_stores_all_positional_args() -> None:
    # Scenario: all seven positional args must be stored verbatim on the context object.
    # Setup: inject distinct values for all positional args.
    # Test action: call debate_tmuxOrchestrator.
    # Test verification: each ctx field matches the supplied value.
    mock_daemon = MagicMock()
    debate_tmuxOrchestrator(
        debate_dir="/d/debate",
        session="s1",
        window_name="w1",
        settings_file="/d/settings.json",
        cwd="/d/cwd",
        repo_root="/d/repo",
        plugin_root="/d/plugin",
        debate_agents="agent_a",
        daemon_main_fn=mock_daemon,
        cleanup_fn=MagicMock(),
    )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.debate_dir == "/d/debate"
    assert ctx.session == "s1"
    assert ctx.window_name == "w1"
    assert ctx.settings_file == "/d/settings.json"
    assert ctx.cwd == "/d/cwd"
    assert ctx.repo_root == "/d/repo"
    assert ctx.plugin_root == "/d/plugin"


# =====================================================================
# debate_initHookContext error tests [main]
# =====================================================================


def test_missing_plugin_root_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_ROOT unset must raise (mirrors bash `:?` guard).
    # Setup: clear CLAUDE_PLUGIN_ROOT, set CLAUDE_PLUGIN_DATA.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    # Test action + Test verification: must raise (RuntimeError or KeyError).
    with pytest.raises((RuntimeError, KeyError, OSError)):
        debate_initHookContext(stdin=io.StringIO("{}"))


def test_missing_plugin_data_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_DATA unset must raise (mirrors bash `:?` guard).
    # Setup: set CLAUDE_PLUGIN_ROOT, clear CLAUDE_PLUGIN_DATA.
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    # Test action + Test verification.
    with pytest.raises((RuntimeError, KeyError, OSError)):
        debate_initHookContext(stdin=io.StringIO("{}"))
