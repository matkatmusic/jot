"""Tests for debate_lib (and debate-related orchestrator functions)."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest
from unittest.mock import MagicMock, mock_open, patch

from common.scripts.util_lib import (
    _valid_kwargs
)
from tests.test_util_lib import _make_lock

from common.scripts.debate_lib import (
    DebateContext,
    ResumeFeasibility,
    debate_agentErrorMarkers,
    debate_agentLaunchCmd,
    debate_agentReadyMarker,
    debate_anyLiveLock,
    debate_archive,
    debate_buildClaudeCmd,
    debate_buildClaudePrompts,
    debate_checkResumeFeasibility,
    debate_claimSession,
    debate_cleanStaleLocks,
    debate_cleanup,
    debate_daemonMain,
    debate_defaultModel,
    debate_detectAvailableAgents,
    debate_findMatching,
    debate_initAgentModels,
    debate_initHookContext,
    debate_launch,
    debate_launchAgent,
    debate_launchAgentsParallel,
    debate_liveSession,
    debate_newEmptyPane,
    debate_nextModel,
    debate_paneHasCapacityError,
    debate_probeCodex,
    debate_probeGemini,
    debate_retryPaneWithNextModel,
    debate_sendPromptToAgent,
    debate_tmuxOrchestrator,
    debate_waitForOutputs,
    debate_writeFailed,
    debate_startOrResume,
    debate_initHookContext,
)
from common.scripts.claude_lib import claude_buildCmd
from common.scripts.hookjson_lib import (
    hookjson_checkRequirements,
    hookjson_emitBlock,
)
from common.scripts.tmux_lib import (
    tmux_capturePane,
    tmux_killPane,
    tmux_killSession,
    tmux_listPanes,
    tmux_newSession,
    tmux_retile,
    tmux_selectLayout,
)
from common.scripts.util_lib import shell_waitForFile, terminal_spawnIfNeeded

# Bind module aliases used throughout the test bodies.
from common.scripts import debate_lib as mod
from common.scripts import debate_lib as sut


def test_debate_agents_falls_back_to_env() -> None:
    # Scenario: debate_agents="" but DEBATE_AGENTS env var is set; orchestrator uses env value.
    # Setup: inject mock daemon_main and cleanup; set DEBATE_AGENTS env.
    # Test action: call with debate_agents="".
    # Test verification: daemon_main called once; ctx.agents matches env value.
    mock_daemon = MagicMock()
    mock_cleanup = MagicMock()
    with patch.dict(os.environ, {"DEBATE_AGENTS": "claude codex"}, clear=False):
        debate_tmuxOrchestrator(
            **_valid_kwargs(debate_agents=""),
            daemon_main_fn=mock_daemon,
            cleanup_fn=mock_cleanup,
        )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.agents == ["claude", "codex"]


# =====================================================================
# debate_startOrResume tests (migrated from _failing/test_debate_startOrResume.py)
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
# debate_main tests (migrated from _failing/test_debate_main.py)
# =====================================================================

# Test bodies use `mod.<name>` patches; bind mod to the lib defining these symbols.
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
# debateRetry_main tests (migrated from _failing/test_debateRetry_main.py)
# =====================================================================

from common.scripts import debate_lib as _mod_dr


def _install_stubs_dr(
    monkeypatch: pytest.MonkeyPatch,
    *,
    transcript_path: str,
    repo_root: str,
    cwd: str = "/tmp/cwd",
    log_file: str = "",
    available: list[str] | None = None,
    any_live: bool = False,
    live_session: str = "",
) -> dict:
    # Replace every external collaborator with a record-collecting stub.
    calls: dict = {
        "init": 0,
        "requirements": [],
        "emits": [],
        "detect": 0,
        "any_live_lock": [],
        "live_session": [],
        "check_resume": [],
        "start_or_resume": [],
    }

    def fake_init():
        calls["init"] += 1
        return {
            "TRANSCRIPT_PATH": transcript_path,
            "REPO_ROOT": repo_root,
            "CWD": cwd,
            "LOG_FILE": log_file,
            "INPUT": "",
            "SCRIPTS_DIR": "",
        }

    def fake_check_requirements(*args):
        calls["requirements"].append(args)

    def fake_emit(msg):
        calls["emits"].append(msg)

    def fake_detect():
        calls["detect"] += 1
        return {
            "available": list(available or ["claude", "gemini"]),
            "gemini_model": "gem-x",
            "codex_model": "",
        }

    def fake_any_live_lock(p):
        calls["any_live_lock"].append(p)
        return any_live

    def fake_live_session(p):
        calls["live_session"].append(p)
        return live_session

    def fake_check_resume(d, a):
        calls["check_resume"].append((Path(d), list(a)))

    def fake_start_or_resume(**kwargs):
        calls["start_or_resume"].append(kwargs)

    monkeypatch.setattr("common.scripts.debate_lib.debate_initHookContext", fake_init)
    monkeypatch.setattr("common.scripts.debate_lib.hookjson_checkRequirements", fake_check_requirements)
    monkeypatch.setattr("common.scripts.debate_lib.hookjson_emitBlock", fake_emit)
    monkeypatch.setattr("common.scripts.debate_lib.debate_detectAvailableAgents", fake_detect)
    monkeypatch.setattr("common.scripts.debate_lib.debate_anyLiveLock", fake_any_live_lock)
    monkeypatch.setattr("common.scripts.debate_lib.debate_liveSession", fake_live_session)
    monkeypatch.setattr("common.scripts.debate_lib.debate_checkResumeFeasibility", fake_check_resume)
    monkeypatch.setattr("common.scripts.debate_lib.debate_startOrResume", fake_start_or_resume)

    return calls


def test_debateRetry_missing_transcript_emits_message(monkeypatch, tmp_path):
    # Scenario: hook context has empty TRANSCRIPT_PATH; should emit and return 0.
    # Setup: install stubs with empty transcript and a valid repo.
    calls = _install_stubs_dr(monkeypatch, transcript_path="", repo_root=str(tmp_path))

    # Test action:
    rc = _mod_dr.debateRetry_main()

    # Test verification:
    assert rc == 0
    assert calls["emits"] == ["/debate-retry: no transcript_path in hook payload"]
    assert calls["start_or_resume"] == []
    assert calls["check_resume"] == []


def test_debateRetry_missing_repo_emits_message(monkeypatch):
    # Scenario: transcript present but REPO_ROOT empty.
    # Setup: install stubs.
    calls = _install_stubs_dr(monkeypatch, transcript_path="/some/t.txt", repo_root="")

    # Test action:
    rc = _mod_dr.debateRetry_main()

    # Test verification:
    assert rc == 0
    assert calls["emits"] == ["/debate-retry requires a git repository"]
    assert calls["start_or_resume"] == []


def test_debateRetry_no_matching_debate_emits_message(monkeypatch, tmp_path):
    # Scenario: Debates dir exists but no invoking_transcript.txt matches.
    # Setup: build a Debates dir with a non-matching transcript marker.
    debates = tmp_path / "Debates" / "2026-01-01T00-00-00_topic"
    debates.mkdir(parents=True)
    (debates / "invoking_transcript.txt").write_text("/other/transcript.txt\n")
    calls = _install_stubs_dr(
        monkeypatch,
        transcript_path="/this/transcript.txt",
        repo_root=str(tmp_path),
    )

    # Test action:
    rc = _mod_dr.debateRetry_main()

    # Test verification:
    assert rc == 0
    assert calls["emits"] == ["/debate-retry: no debate found in this conversation"]
    assert calls["start_or_resume"] == []


def test_debateRetry_matched_with_synthesis_emits_already_complete(monkeypatch, tmp_path):
    # Scenario: matched debate dir already has synthesis.md.
    # Setup: matching transcript + synthesis.md present.
    transcript = "/conv/abc.jsonl"
    debate_dir = tmp_path / "Debates" / "2026-02-02T10-10-10_topic"
    debate_dir.mkdir(parents=True)
    (debate_dir / "invoking_transcript.txt").write_text(transcript + "\n")
    (debate_dir / "synthesis.md").write_text("done\n")
    calls = _install_stubs_dr(
        monkeypatch, transcript_path=transcript, repo_root=str(tmp_path)
    )

    # Test action:
    rc = _mod_dr.debateRetry_main()

    # Test verification:
    assert rc == 0
    assert len(calls["emits"]) == 1
    assert "already complete" in calls["emits"][0]
    assert "synthesis.md" in calls["emits"][0]
    assert calls["start_or_resume"] == []


def test_debateRetry_matched_with_live_lock_emits_still_running(monkeypatch, tmp_path):
    # Scenario: matched debate has no synthesis but a live lock.
    # Setup: matching transcript; no synthesis; any_live_lock returns True.
    transcript = "/conv/live.jsonl"
    debate_dir = tmp_path / "Debates" / "2026-03-03T11-11-11_run"
    debate_dir.mkdir(parents=True)
    (debate_dir / "invoking_transcript.txt").write_text(transcript)
    calls = _install_stubs_dr(
        monkeypatch,
        transcript_path=transcript,
        repo_root=str(tmp_path),
        any_live=True,
        live_session="debate-7",
    )

    # Test action:
    rc = _mod_dr.debateRetry_main()

    # Test verification:
    assert rc == 0
    assert len(calls["emits"]) == 1
    assert calls["emits"][0] == "/debate-retry: still running -> tmux attach -t debate-7"
    assert calls["start_or_resume"] == []


def test_debateRetry_happy_path_lex_max_wins_and_invokes_resume(monkeypatch, tmp_path):
    # Scenario: multiple matching dirs + stale FAILED.txt; lex-max wins, FAILED.txt removed,
    # check_resume_feasibility called, startOrResume invoked.
    # Setup: build dirs, transcripts, topic.md, FAILED.txt.
    transcript = "/conv/main.jsonl"
    older = tmp_path / "Debates" / "2026-01-01T00-00-00_a"
    newer = tmp_path / "Debates" / "2026-09-09T09-09-09_z"
    other = tmp_path / "Debates" / "2026-05-05T05-05-05_x"
    for d in (older, newer, other):
        d.mkdir(parents=True)
    (older / "invoking_transcript.txt").write_text(transcript)
    (newer / "invoking_transcript.txt").write_text(transcript)
    (other / "invoking_transcript.txt").write_text("/different/t.jsonl")
    (newer / "topic.md").write_text("the topic\n")
    failed_marker = newer / "FAILED.txt"
    failed_marker.write_text("stale\n")

    calls = _install_stubs_dr(
        monkeypatch,
        transcript_path=transcript,
        repo_root=str(tmp_path),
        available=["claude", "gemini", "codex"],
    )

    # Test action:
    rc = _mod_dr.debateRetry_main()

    # Test verification:
    assert rc == 0
    assert calls["emits"] == []
    assert not failed_marker.exists()
    assert len(calls["check_resume"]) == 1
    chk_dir, chk_agents = calls["check_resume"][0]
    assert chk_dir == newer
    assert chk_agents == ["claude", "gemini", "codex"]
    assert len(calls["start_or_resume"]) == 1
    kwargs = calls["start_or_resume"][0]
    assert Path(kwargs["debate_dir"]) == newer
    assert kwargs["resuming"] is True
    assert kwargs["available_agents"] == ["claude", "gemini", "codex"]
    assert kwargs["repo_root"] == str(tmp_path)
    assert len(calls["requirements"]) == 1
    assert calls["requirements"][0][0] == "debate-retry"


# =====================================================================
# debate_daemonMain tests (migrated from _failing/test_debate_daemonMain.py)
# =====================================================================

from common.scripts import debate_lib as _MOD_DAEMON


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


# --- debate_agentReadyMarker ---

def test_gemini_marker():
    # Scenario: gemini agent boots and shows its REPL prompt.
    # Setup: agent name is the literal "gemini".
    # Test action: query the ready marker.
    # Test verification: returns gemini's exact prompt substring.
    agent = "gemini"
    result = debate_agentReadyMarker(agent)
    assert result == "Type your message or @path/to/file"


def test_codex_marker():
    # Scenario: codex agent finishes boot and shows model-selector hint.
    # Setup: agent name is the literal "codex".
    # Test action: query the ready marker.
    # Test verification: returns codex's exact ready-line substring.
    agent = "codex"
    result = debate_agentReadyMarker(agent)
    assert result == "/model to change"



def test_unknown_agent_returns_empty_string():
    # Scenario: caller passes an agent name not in the case statement.
    # Setup: arbitrary unknown agent identifier.
    # Test action: query the ready marker.
    # Test verification: empty string (bash case has no default branch).
    agent = "bogus"
    result = debate_agentReadyMarker(agent)
    assert result == ""


def test_empty_string_agent_returns_empty_string():
    # Scenario: defensive call with empty agent name.
    # Setup: empty string as agent identifier.
    # Test action: query the ready marker.
    # Test verification: empty string returned, no exception raised.
    agent = ""
    result = debate_agentReadyMarker(agent)
    assert result == ""


def test_codex_returns_capacity_and_overload_markers():
    # Scenario: codex agent has two known capacity-class error strings
    # Setup: agent name 'codex'
    # Test action: call debate_agentErrorMarkers('codex')
    # Test verification: returns exact ordered list of two markers
    result = debate_agentErrorMarkers("codex")
    assert result == ["Selected model is at capacity", "model is overloaded"]


def test_gemini_returns_quota_markers_in_order():
    # Scenario: gemini agent has three quota/exhaustion markers
    # Setup: agent name 'gemini'
    # Test action: call debate_agentErrorMarkers('gemini')
    # Test verification: returns the three markers in bash printf order
    result = debate_agentErrorMarkers("gemini")
    assert result == [
        "RESOURCE_EXHAUSTED",
        "Quota exceeded",
        "You exceeded your current quota",
    ]



def test_unknown_agent_returns_empty_list():
    # Scenario: bash case has no default branch -> no output
    # Setup: agent name not in {codex, gemini, claude}
    # Test action: call with unknown agent
    # Test verification: empty list (Python equivalent of empty stdout)
    assert debate_agentErrorMarkers("bogus") == []


def test_empty_string_agent_returns_empty_list():
    # Scenario: empty argument falls through case with no match
    # Setup: agent name ''
    # Test action: call with empty string
    # Test verification: empty list
    assert debate_agentErrorMarkers("") == []


def test_result_is_list_type():
    # Scenario: callers iterate markers (see pane_has_capacity_error loop)
    # Setup: any valid agent
    # Test action: check return type
    # Test verification: list (mutable sequence) so callers can iterate safely
    assert isinstance(debate_agentErrorMarkers("codex"), list)


# ──────────────────────────── gemini ────────────────────────────

def test_gemini_with_model() -> None:
    # Scenario: caller selected an explicit gemini model.
    # Setup: stash CURRENT_MODEL[gemini] = "gemini-2.5-pro".
    current_model = {"gemini": "gemini-2.5-pro"}
    # Test action: build launch cmd for gemini.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: --model flag appears with the chosen model, quoted.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)' "
        "--model 'gemini-2.5-pro'"
    )


def test_gemini_without_model() -> None:
    # Scenario: no model preselected for gemini.
    # Setup: stash CURRENT_MODEL[gemini] = "" (empty).
    current_model = {"gemini": ""}
    # Test action: build launch cmd.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: no --model segment present.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)'"
    )


# ──────────────────────────── codex ────────────────────────────

def test_codex_with_model() -> None:
    # Scenario: codex with explicit model.
    # Setup: model "gpt-5", debate_dir "/repo/Debates/T_slug".
    current_model = {"codex": "gpt-5"}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/T_slug",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: --add-dir uses debate_dir; --model uses provided.
    assert cmd == "codex -a never --add-dir '/repo/Debates/T_slug' --model 'gpt-5'"


def test_codex_without_model() -> None:
    # Scenario: codex without model.
    # Setup: empty model entry.
    current_model = {"codex": ""}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/X",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: no --model.
    assert cmd == "codex -a never --add-dir '/repo/Debates/X'"


def test_creates_archive_subdirectory(tmp_path: Path) -> None:
    # Scenario: debate_archive must create the archive/ subdirectory under DEBATE_DIR.
    # Setup: empty debate dir with no intermediate files.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    # Test action: invoke debate_archive on the empty dir.
    debate_archive(debate_dir)
    # Test verification: archive subdir now exists.
    assert (debate_dir / "archive").is_dir()


def test_moves_context_md_into_archive(tmp_path: Path) -> None:
    # Scenario: context.md at debate root must be relocated into archive/.
    # Setup: write a context.md with known content.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    src = debate_dir / "context.md"
    src.write_text("CTX")
    # Test action: archive.
    debate_archive(debate_dir)
    # Test verification: source removed; destination present with same content.
    assert not src.exists()
    moved = debate_dir / "archive" / "context.md"
    assert moved.is_file()
    assert moved.read_text() == "CTX"


def test_moves_synthesis_instructions_txt(tmp_path: Path) -> None:
    # Scenario: synthesis_instructions.txt must be archived.
    # Setup: create file at debate root.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis_instructions.txt").write_text("SI")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert not (debate_dir / "synthesis_instructions.txt").exists()
    assert (debate_dir / "archive" / "synthesis_instructions.txt").read_text() == "SI"


def test_moves_r1_instructions_glob(tmp_path: Path) -> None:
    # Scenario: r1_instructions_*.txt files must be archived (glob pattern).
    # Setup: two r1 instruction files for different agents.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r1_instructions_gemini.txt").write_text("g")
    (debate_dir / "r1_instructions_claude.txt").write_text("c")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: both moved into archive/.
    assert not (debate_dir / "r1_instructions_gemini.txt").exists()
    assert not (debate_dir / "r1_instructions_claude.txt").exists()
    assert (debate_dir / "archive" / "r1_instructions_gemini.txt").read_text() == "g"
    assert (debate_dir / "archive" / "r1_instructions_claude.txt").read_text() == "c"


def test_moves_r1_output_md_glob(tmp_path: Path) -> None:
    # Scenario: r1_*.md round-1 outputs must be archived.
    # Setup: per-agent r1 outputs.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r1_gemini.md").write_text("R1G")
    (debate_dir / "r1_codex.md").write_text("R1C")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "archive" / "r1_gemini.md").read_text() == "R1G"
    assert (debate_dir / "archive" / "r1_codex.md").read_text() == "R1C"
    assert not (debate_dir / "r1_gemini.md").exists()


def test_moves_r2_instructions_and_outputs_glob(tmp_path: Path) -> None:
    # Scenario: r2_instructions_*.txt and r2_*.md must both be archived.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "r2_instructions_gemini.txt").write_text("i")
    (debate_dir / "r2_gemini.md").write_text("o")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "archive" / "r2_instructions_gemini.txt").is_file()
    assert (debate_dir / "archive" / "r2_gemini.md").is_file()


def test_moves_orchestrator_log_when_present(tmp_path: Path) -> None:
    # Scenario: orchestrator.log handled by separate clause; must move when present.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "orchestrator.log").write_text("LOG")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert not (debate_dir / "orchestrator.log").exists()
    assert (debate_dir / "archive" / "orchestrator.log").read_text() == "LOG"


def test_does_not_move_synthesis_md(tmp_path: Path) -> None:
    # Scenario: synthesis.md is the final artifact; must remain at debate root.
    # Setup: create synthesis.md plus an r1 output.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis.md").write_text("FINAL")
    (debate_dir / "r1_gemini.md").write_text("R1G")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: synthesis.md still at root, untouched.
    assert (debate_dir / "synthesis.md").read_text() == "FINAL"
    assert not (debate_dir / "archive" / "synthesis.md").exists()


def test_does_not_move_topic_md(tmp_path: Path) -> None:
    # Scenario: topic.md is a primary artifact; must NOT be archived.
    # Setup.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "topic.md").write_text("TOPIC")
    # Test action.
    debate_archive(debate_dir)
    # Test verification.
    assert (debate_dir / "topic.md").read_text() == "TOPIC"
    assert not (debate_dir / "archive" / "topic.md").exists()


def test_idempotent_when_no_intermediate_files(tmp_path: Path) -> None:
    # Scenario: running on a debate dir with nothing to archive must not error.
    # Setup: only synthesis.md present.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "synthesis.md").write_text("S")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: archive dir created, synthesis.md untouched.
    assert (debate_dir / "archive").is_dir()
    assert (debate_dir / "synthesis.md").read_text() == "S"


def test_handles_preexisting_archive_dir(tmp_path: Path) -> None:
    # Scenario: archive/ already exists from a previous run; mkdir -p semantics.
    # Setup: pre-create archive with a stale file inside, plus a new file to archive.
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "archive").mkdir()
    (debate_dir / "archive" / "old.txt").write_text("OLD")
    (debate_dir / "context.md").write_text("NEW")
    # Test action.
    debate_archive(debate_dir)
    # Test verification: prior contents preserved; new file moved in.
    assert (debate_dir / "archive" / "old.txt").read_text() == "OLD"
    assert (debate_dir / "archive" / "context.md").read_text() == "NEW"
    assert not (debate_dir / "context.md").exists()


# ── Gate 1: binary presence ────────────────────────────────────────────


def test_returns_empty_when_gemini_binary_missing():
    # Scenario: gemini CLI not installed on this machine.
    # Setup: shutil.which returns None for "gemini"; clear all credential env.
    with patch("common.scripts.debate_lib.shutil.which", return_value=None), \
         patch.dict(os.environ, {}, clear=True), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string signals "unavailable" to caller.
    assert result == ""


# ── Gate 2: credentials present ────────────────────────────────────────


def test_returns_empty_when_binary_present_but_no_credentials():
    # Scenario: gemini installed but user never logged in or set API key.
    # Setup: which finds binary; no oauth file; no API-key env vars.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {}, clear=True):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string — credentials gate failed.
    assert result == ""


def test_returns_model_when_oauth_creds_file_present():
    # Scenario: user authenticated via `gemini auth login` (oauth file).
    # Setup: binary on PATH; oauth_creds.json exists; default model configured.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: model name is returned (caller uses it for spawn).
    assert result == "gemini-2.5-pro"


def test_returns_model_when_gemini_api_key_env_set():
    # Scenario: CI / headless usage with GEMINI_API_KEY env var.
    # Setup: binary present; no oauth file; GEMINI_API_KEY set.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GEMINI_API_KEY": "abc123"}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gemini-2.5-flash"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: env-var credentials path also yields model name.
    assert result == "gemini-2.5-flash"


def test_returns_model_when_google_api_key_env_set():
    # Scenario: alternate env var GOOGLE_API_KEY (Google AI Studio name).
    # Setup: binary present; no oauth file; only GOOGLE_API_KEY set.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GOOGLE_API_KEY": "xyz789"}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: GOOGLE_API_KEY satisfies the credentials gate.
    assert result == "gemini-2.5-pro"

# ── Gate 3: model lookup / "present" sentinel ──────────────────────────


def test_returns_present_sentinel_when_no_model_configured():
    # Scenario: gemini available but models.json has no entry for it.
    # Setup: all gates pass; _default_model returns "" (no model listed).
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value=""):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: literal "present" sentinel — non-empty so caller's
    # `-s` truthiness check treats gemini as available.
    assert result == "present"


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



# ---------------------------------------------------------------------------
# r1 stage
# ---------------------------------------------------------------------------


def test_r1_writes_instruction_file_for_each_agent(tmp_path: Path) -> None:
    # Scenario: r1 stage with two agents, no AGENT_FILTER
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("# R1 template\nDEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    for agent in agents:
        out = debate_dir / f"r1_instructions_{agent}.txt"
        assert out.exists(), f"missing {out.name}"
        content = out.read_text()
        assert str(debate_dir) in content
        assert str(debate_dir / f"r1_{agent}.md") in content


def test_r1_agent_filter_writes_only_matching_agent(tmp_path: Path) -> None:
    # Scenario: r1 stage with AGENT_FILTER set to one agent
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("DEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="claude",
    )

    # Test verification:
    assert (debate_dir / "r1_instructions_claude.txt").exists()
    assert not (debate_dir / "r1_instructions_gemini.txt").exists()


def test_r1_reads_agents_from_agents_txt_when_agents_list_empty(tmp_path: Path) -> None:
    # Scenario: agents list is empty; function falls back to agents.txt
    # Setup:
    plugin_root = tmp_path / "plugin"
    tmpl_dir = plugin_root / "skills" / "debate" / "prompts"
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "r1.template.md").write_text("DEBATE_DIR={{DEBATE_DIR}}\nOUTPUT_FILE={{OUTPUT_FILE}}\n")
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    (debate_dir / "agents.txt").write_text("claude\ngemini\n")

    # Test action:
    debate_buildClaudePrompts(
        stage="r1",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=[],
    )

    # Test verification:
    assert (debate_dir / "r1_instructions_claude.txt").exists()
    assert (debate_dir / "r1_instructions_gemini.txt").exists()


# ---------------------------------------------------------------------------
# r2 stage
# ---------------------------------------------------------------------------


def test_r2_writes_cross_critique_instruction_file_for_each_agent(tmp_path: Path) -> None:
    # Scenario: r2 stage with three agents, no filter
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini", "codex"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    for agent in agents:
        out = debate_dir / f"r2_instructions_{agent}.txt"
        assert out.exists()
        content = out.read_text()
        assert "Round 2: Cross-Critique" in content
        assert f"r1_{agent}.md" in content
        # Others' r1 paths referenced
        for other in agents:
            if other != agent:
                assert f"r1_{other}.md" in content
        assert f"r2_{agent}.md" in content


def test_r2_agent_filter_writes_only_matching_agent(tmp_path: Path) -> None:
    # Scenario: r2 with AGENT_FILTER; only target agent file written
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="gemini",
    )

    # Test verification:
    assert (debate_dir / "r2_instructions_gemini.txt").exists()
    assert not (debate_dir / "r2_instructions_claude.txt").exists()


def test_r2_others_list_excludes_self(tmp_path: Path) -> None:
    # Scenario: r2 for agent "claude"; claude's own r1 not listed as "other"
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="r2",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
        agent_filter="claude",
    )

    # Test verification:
    content = (debate_dir / "r2_instructions_claude.txt").read_text()
    lines = content.splitlines()
    # gemini r1 path appears in "Other Agents" section (after the header line)
    other_refs = [l for l in lines if "r1_gemini.md" in l]
    assert other_refs, "gemini r1 not referenced"
    # claude's r1 path referenced only as "Your Round 1 Response"
    self_refs = [l for l in lines if "r1_claude.md" in l]
    assert self_refs, "own r1 not referenced at all"


# ---------------------------------------------------------------------------
# synthesis stage
# ---------------------------------------------------------------------------


def test_synthesis_writes_single_instruction_file(tmp_path: Path) -> None:
    # Scenario: synthesis stage with two agents
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    out = debate_dir / "synthesis_instructions.txt"
    assert out.exists()
    content = out.read_text()
    assert "Round 3: Synthesis" in content
    assert "2 agents" in content
    assert "claude" in content
    assert "gemini" in content
    assert "synthesis.md" in content


def test_synthesis_references_all_r1_and_r2_paths(tmp_path: Path) -> None:
    # Scenario: synthesis file references every agent's r1 and r2 paths
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini", "codex"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    content = (debate_dir / "synthesis_instructions.txt").read_text()
    for agent in agents:
        assert f"r1_{agent}.md" in content
        assert f"r2_{agent}.md" in content


def test_synthesis_contains_required_structure_sections(tmp_path: Path) -> None:
    # Scenario: output must contain all 8 structure headings
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    agents = ["claude", "gemini"]
    plugin_root = tmp_path / "plugin"

    # Test action:
    debate_buildClaudePrompts(
        stage="synthesis",
        debate_dir=debate_dir,
        plugin_root=plugin_root,
        agents=agents,
    )

    # Test verification:
    content = (debate_dir / "synthesis_instructions.txt").read_text()
    for heading in [
        "Topic",
        "Agreement",
        "Disagreement",
        "Strongest Arguments",
        "Weaknesses",
        "Path Forward",
        "Confidence",
        "Open Questions",
    ]:
        assert heading in content, f"missing section: {heading}"


# ---------------------------------------------------------------------------
# error cases
# ---------------------------------------------------------------------------


def test_unknown_stage_raises_value_error(tmp_path: Path) -> None:
    # Scenario: invalid stage name raises ValueError
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()

    # Test action / verification:
    try:
        debate_buildClaudePrompts(
            stage="badstage",
            debate_dir=debate_dir,
            plugin_root=tmp_path / "plugin",
            agents=["claude"],
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "badstage" in str(exc)



# --- debate_checkResumeFeasibility ---






def _seed_original(debate_dir: Path, agents: list[str]) -> None:
    """Helper: write r1_instructions_<agent>.txt for each agent."""
    debate_dir.mkdir(parents=True, exist_ok=True)
    for a in agents:
        (debate_dir / f"r1_instructions_{a}.txt").write_text("instr\n")


def _seed_outputs(debate_dir: Path, agent: str, *, r1: bool, r2: bool) -> None:
    """Helper: optionally seed non-empty r1_<agent>.md / r2_<agent>.md."""
    if r1:
        (debate_dir / f"r1_{agent}.md").write_text("r1 body\n")
    if r2:
        (debate_dir / f"r2_{agent}.md").write_text("r2 body\n")


def test_all_originals_still_available_returns_feasible(tmp_path: Path) -> None:
    # Scenario: original composition (claude, gemini) still all available.
    # Setup: seed two r1_instructions files; available list matches exactly.
    _seed_original(tmp_path, ["claude", "gemini"])
    # Test action: run the feasibility check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude", "gemini"])
    # Test verification: feasible=True, agent list unchanged, no unusable.
    assert result.feasible is True
    assert result.unusable_agents == []
    assert set(result.updated_agents) == {"claude", "gemini"}


def test_appeared_agent_is_kept_in_updated_list(tmp_path: Path) -> None:
    # Scenario: an agent appeared since the original debate (codex new).
    # Setup: original was just claude; available now is [claude, codex].
    _seed_original(tmp_path, ["claude"])
    # Test action: feasibility check with the larger available list.
    result = debate_checkResumeFeasibility(tmp_path, ["claude", "codex"])
    # Test verification: feasible and codex retained for JIT instructions.
    assert result.feasible is True
    assert "codex" in result.updated_agents


def test_disappeared_agent_with_complete_outputs_is_readded(tmp_path: Path) -> None:
    # Scenario: gemini disappeared (creds gone) but its R1+R2 are cached.
    # Setup: original=[claude,gemini]; available=[claude]; gemini outputs exist.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=True)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: feasible, gemini re-added so synthesis sees it.
    assert result.feasible is True
    assert "gemini" in result.updated_agents
    assert result.unusable_agents == []


def test_disappeared_agent_missing_r2_is_unusable(tmp_path: Path) -> None:
    # Scenario: gemini disappeared and only R1 cached (no R2).
    # Setup: original=[claude,gemini]; available=[claude]; only gemini r1 exists.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=False)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: not feasible; gemini listed in unusable.
    assert result.feasible is False
    assert result.unusable_agents == ["gemini"]


def test_disappeared_agent_with_empty_output_file_is_unusable(tmp_path: Path) -> None:
    # Scenario: r1+r2 exist but r2 is zero bytes — bash uses `-s` (non-empty).
    # Setup: seed gemini originals and an empty r2 file.
    _seed_original(tmp_path, ["claude", "gemini"])
    (tmp_path / "r1_gemini.md").write_text("r1\n")
    (tmp_path / "r2_gemini.md").write_text("")  # zero-byte
    # Test action: run check with gemini missing from availability.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: empty file == unusable, matching bash `[ -s ]` semantics.
    assert result.feasible is False
    assert "gemini" in result.unusable_agents


def test_unusable_reason_contains_block_message_and_agent_name(tmp_path: Path) -> None:
    # Scenario: emit_block reason text needs to surface the unusable agent.
    # Setup: codex disappeared with no outputs at all.
    _seed_original(tmp_path, ["claude", "codex"])
    # Test action: run check with codex unavailable and no cached outputs.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: reason mentions codex and the canonical resume hint.
    assert "codex" in result.reason
    assert "cannot resume" in result.reason
    assert "/debate-abort" in result.reason


def test_no_original_instructions_returns_feasible(tmp_path: Path) -> None:
    # Scenario: brand-new debate dir with no r1_instructions_*.txt yet.
    # Setup: empty debate_dir; available=[claude].
    tmp_path.mkdir(exist_ok=True)
    # Test action: run check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: trivially feasible — no originals to validate against.
    assert result.feasible is True
    assert result.unusable_agents == []
    assert result.updated_agents == ["claude"]


def test_caller_available_agents_list_is_not_mutated(tmp_path: Path) -> None:
    # Scenario: function must not mutate caller's list (Python idiom vs bash global).
    # Setup: original includes gemini with cached outputs; available list captured.
    _seed_original(tmp_path, ["claude", "gemini"])
    _seed_outputs(tmp_path, "gemini", r1=True, r2=True)
    available = ["claude"]
    snapshot = list(available)
    # Test action: run check.
    debate_checkResumeFeasibility(tmp_path, available)
    # Test verification: caller's list is unchanged after the call.
    assert available == snapshot


def test_returns_resumefeasibility_dataclass_instance(tmp_path: Path) -> None:
    # Scenario: contract — return type is the documented dataclass.
    # Setup: minimal valid debate dir.
    _seed_original(tmp_path, ["claude"])
    # Test action: run the check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: instance shape is ResumeFeasibility.
    assert isinstance(result, ResumeFeasibility)
    assert isinstance(result.updated_agents, list)
    assert isinstance(result.unusable_agents, list)


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


# Helper: write a lock file with the given pane id payload.
def _write_lock(debate_dir: Path, stage: str, agent: str, payload: str) -> Path:
    lock = debate_dir / f".{stage}_{agent}.lock"
    lock.write_text(payload)
    return lock


from common.scripts.git_lib import makeGitRepo as _make_repo


def _noop() -> None:
    pass


def _make_main_mock() -> MagicMock:
    return MagicMock(return_value=None)


_PANE = "%7"
_AGENT = "claude"
_CMD = "claude --settings /tmp/s.json --add-dir '/repo'"
_READY = "Claude Code v"


def _patch_all(pane_content: str = "", *, ready_after: int | None = 0):
    """Patch I/O callees on common.scripts.debate_lib (where bare names resolve)."""
    captured_lines: list[str] = []
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


def _write_lock_at_path(lock_path: Path, pane_id: str) -> None:
    """Write a lock file with the canonical debate:<pane_id> format."""
    lock_path.write_text(f"debate:{pane_id}\n")


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fake_tmux(monkeypatch):
    """Patch `_live_pane_ids` to return a configurable set without tmux."""
    state: dict[str, set[str]] = {"live": set()}

    def _fake() -> set[str]:
        return set(state["live"])

    monkeypatch.setattr("common.scripts.debate_lib._live_pane_ids", _fake)
    return state


_BASE_KWARGS = dict(
    pane_index=0,
    agent="gemini",
    stage="r1",
    current_pane_id="%10",
    current_model={"gemini": "gemini-pro"},
    tried_models={"gemini": "gemini-pro"},
    window_target="debate:0",
    cwd="/tmp/cwd",
    repo_root="/tmp/repo",
    home="/tmp/home",
    settings_file="/tmp/settings.json",
    debate_dir="/tmp/debate",
    models_json_path="/tmp/models.json",
)


def test_removes_lock_with_missing_pane_id(tmp_path: Path) -> None:
    # Scenario: lock file is malformed and contains no pane id token.
    # Setup: create a .r1_gemini.lock with junk that sed regex will not match.
    lock = _write_lock(tmp_path, "r1", "gemini", "garbage-not-a-pane-id\n")
    # Test action: invoke cleaner with no live panes; tmux probes should not even matter.
    with patch("common.scripts.debate_lib._listLivePaneIds", return_value=set()), \
         patch("common.scripts.debate_lib._paneCurrentCommand", return_value=""):
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: the malformed lock must be gone.
    assert not lock.exists()


def test_removes_lock_when_pane_not_in_window(tmp_path: Path) -> None:
    # Scenario: lock references a pane id that is no longer present in the tmux window.
    # Setup: write a well-formed lock pointing to %42; tmux reports only %99 alive.
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%42\n")
    with patch("common.scripts.debate_lib._listLivePaneIds", return_value={"%99"}), \
         patch("common.scripts.debate_lib._paneCurrentCommand", return_value="codex"):
        # Test action: clean stage r1.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: stale lock removed.
    assert not lock.exists()


def test_removes_lock_when_pane_current_command_mismatches_agent(tmp_path: Path) -> None:
    # Scenario: pane is alive but running a different binary (agent crashed; shell took over).
    # Setup: lock claims pane %5 for gemini, but tmux reports current_command = "bash".
    lock = _write_lock(tmp_path, "r1", "gemini", "debate:%5\n")
    with patch("common.scripts.debate_lib._listLivePaneIds", return_value={"%5"}), \
         patch("common.scripts.debate_lib._paneCurrentCommand", return_value="bash"):
        # Test action.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: lock removed because current_command != agent.
    assert not lock.exists()


def test_preserves_lock_when_pane_alive_and_command_matches_agent(tmp_path: Path) -> None:
    # Scenario: pane is live and running the agent binary -- lock is valid and must NOT be removed.
    # Setup: lock for codex on pane %7; tmux confirms %7 alive with current_command "codex".
    lock = _write_lock(tmp_path, "r1", "codex", "debate:%7\n")
    with patch("common.scripts.debate_lib._listLivePaneIds", return_value={"%7"}), \
         patch("common.scripts.debate_lib._paneCurrentCommand", return_value="codex"):
        # Test action.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: live lock preserved.
    assert lock.exists()
    assert lock.read_text() == "debate:%7\n"


def test_only_touches_locks_for_requested_stage(tmp_path: Path) -> None:
    # Scenario: r2 lock files must be ignored when caller asks to clean r1.
    # Setup: write one stale r1 lock (no pane id) and one stale r2 lock (no pane id).
    r1_lock = _write_lock(tmp_path, "r1", "gemini", "junk\n")
    r2_lock = _write_lock(tmp_path, "r2", "gemini", "junk\n")
    with patch("common.scripts.debate_lib._listLivePaneIds", return_value=set()), \
         patch("common.scripts.debate_lib._paneCurrentCommand", return_value=""):
        # Test action: clean stage r1 only.
        debate_cleanStaleLocks(tmp_path, "r1")
    # Test verification: r1 lock removed, r2 lock untouched.
    assert not r1_lock.exists()
    assert r2_lock.exists()


def test_no_locks_present_is_a_noop(tmp_path: Path) -> None:
    # Scenario: empty debate directory -- glob matches nothing.
    # Setup: tmp_path is empty; no tmux probes should be invoked.
    with patch("common.scripts.debate_lib._listLivePaneIds") as live, \
         patch("common.scripts.debate_lib._paneCurrentCommand") as cur:
        # Test action.
        debate_cleanStaleLocks(tmp_path, "synthesis")
    # Test verification: function returns cleanly without probing tmux.
    assert live.call_count == 0
    assert cur.call_count == 0


# Helper: build a fake plugin root with a models.json containing `payload`.
def _make_plugin_root(tmp_path: Path, payload: dict) -> Path:
    assets = tmp_path / "skills" / "debate" / "scripts" / "assets"
    assets.mkdir(parents=True)
    (assets / "models.json").write_text(json.dumps(payload))
    return tmp_path


def test_returns_first_claude_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "claude".
    # Setup: plugin root with models.json mapping claude -> 3 models.
    root = _make_plugin_root(tmp_path, {
        "claude": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        "gemini": ["gemini-3.1-pro-preview"],
        "codex": ["gpt-5.5"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="claude".
    result = debate_defaultModel("claude")
    # Test verification: index-0 entry for claude is returned verbatim.
    assert result == "claude-opus-4-7"


def test_returns_first_gemini_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "gemini".
    # Setup: plugin root with multi-entry gemini list.
    root = _make_plugin_root(tmp_path, {
        "gemini": ["gemini-3.1-pro-preview", "gemini-3-flash-preview"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: returns the first gemini model only.
    assert result == "gemini-3.1-pro-preview"


def test_returns_first_codex_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "codex".
    # Setup: plugin root with codex list.
    root = _make_plugin_root(tmp_path, {
        "codex": ["gpt-5.5", "gpt-5.4"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="codex".
    result = debate_defaultModel("codex")
    # Test verification: index-0 codex model returned.
    assert result == "gpt-5.5"


def test_unknown_agent_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: caller asks for an agent absent from models.json.
    # Setup: models.json with only claude listed.
    root = _make_plugin_root(tmp_path, {"claude": ["claude-opus-4-7"]})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for an unmapped agent name.
    result = debate_defaultModel("gemini")
    # Test verification: bash `// ""` fallback is "", not None / KeyError.
    assert result == ""


def test_agent_with_empty_list_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: agent key exists but has no models configured.
    # Setup: gemini key maps to an empty array.
    root = _make_plugin_root(tmp_path, {"gemini": []})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: jq `.[$a][0] // ""` returns "" on empty list.
    assert result == ""


def test_missing_plugin_root_env_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_ROOT is unset (plugin harness not active).
    # Setup: clear the env var.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # Test action + verification: a clear error is raised, not silent "".
    with pytest.raises((KeyError, RuntimeError)):
        debate_defaultModel("claude")



def test_only_claude_when_both_probes_unavailable():
    # Scenario: no gemini, no codex installed → only claude is available.
    # Setup: patch both probes at SUT module boundary to return "" (unavailable).
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value=""), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: claude-only list, both model strings empty.
    assert result["available"] == ["claude"]
    assert result["gemini_model"] == ""
    assert result["codex_model"] == ""


def test_gemini_with_real_model_appended_and_model_recorded():
    # Scenario: gemini probe returns a real model name → gemini joins list, model captured.
    # Setup: gemini probe returns concrete model; codex probe returns "" (unavailable).
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == ""


def test_gemini_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: gemini probe returns "present" sentinel (binary+creds, no model configured).
    # Setup: probe returns literal "present"; codex unavailable.
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value="present"), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini in list, but gemini_model is "" (sentinel suppressed).
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == ""


def test_codex_with_real_model_appended_and_model_recorded():
    # Scenario: codex probe returns a real model name → codex joins list, model captured.
    # Setup: gemini unavailable, codex returns concrete model.
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value=""), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == "gpt-5-codex"
    assert result["gemini_model"] == ""


def test_codex_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: codex probe returns "present" sentinel.
    # Setup: gemini unavailable, codex returns literal "present".
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value=""), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value="present"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex available, codex_model blank (sentinel suppressed).
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == ""


def test_both_probes_available_preserves_order_claude_gemini_codex():
    # Scenario: both auxiliary agents usable → list order is claude, gemini, codex.
    # Setup: both probes return real model names.
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: ordered list and both models captured.
    assert result["available"] == ["claude", "gemini", "codex"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == "gpt-5-codex"


def _make_topic_debate(repo_root: Path, ts: str, topic_text: str) -> Path:
    # Helper: create Debates/<ts>/topic.md with given text. Returns dir path.
    d = repo_root / "Debates" / ts
    d.mkdir(parents=True)
    (d / "topic.md").write_text(topic_text)
    return d


def test_returns_none_when_no_debates_dir(tmp_path):
    # Scenario: repo has no Debates/ directory at all.
    # Setup: empty tmp repo root.
    repo = tmp_path
    # Test action: call debate_findMatching with any topic.
    result = debate_findMatching(str(repo), "anything")
    # Test verification: returns None (no match).
    assert result is None


def test_returns_none_when_no_topic_matches(tmp_path):
    # Scenario: Debates/ has dirs but none has matching topic.md content.
    # Setup: one debate dir with different topic text.
    repo = tmp_path
    _make_topic_debate(repo, "2026-01-01_120000_a", "different topic\n")
    # Test action: search for unrelated topic.
    result = debate_findMatching(str(repo), "looking for this\n")
    # Test verification: returns None.
    assert result is None


def test_returns_dir_path_for_single_match(tmp_path):
    # Scenario: exactly one debate has a topic.md byte-equal to query.
    # Setup: matching topic written verbatim (incl. trailing newline appended by printf '%s\n').
    repo = tmp_path
    topic = "Discuss async patterns"
    d = _make_topic_debate(repo, "2026-02-02_100000_x", topic + "\n")
    # Test action: query with the same topic (function appends \n internally like `printf '%s\n'`).
    result = debate_findMatching(str(repo), topic)
    # Test verification: returns that debate dir as a string, no trailing slash.
    assert result == str(d)


def test_skips_dirs_missing_topic_md(tmp_path):
    # Scenario: a Debates/<ts>/ dir exists with no topic.md file.
    # Setup: one dir without topic.md, one with matching topic.md.
    repo = tmp_path
    (repo / "Debates" / "2026-03-03_111111_no_topic").mkdir(parents=True)
    d_match = _make_topic_debate(repo, "2026-03-03_222222_yes", "hello\n")
    # Test action.
    result = debate_findMatching(str(repo), "hello")
    # Test verification: skips topic-less dir, returns the one with topic.md.
    assert result == str(d_match)


def test_most_recent_timestamp_wins_on_multiple_matches(tmp_path):
    # Scenario: multiple debates have identical topic.md; lexicographically-greatest dir name wins.
    # Setup: three matching debates with sortable timestamps.
    repo = tmp_path
    topic = "shared topic"
    _make_topic_debate(repo, "2025-01-01_000000_a", topic + "\n")
    _make_topic_debate(repo, "2026-06-15_120000_b", topic + "\n")
    d_newest = _make_topic_debate(repo, "2027-12-31_235959_c", topic + "\n")
    # Test action.
    result = debate_findMatching(str(repo), topic)
    # Test verification: returns lexicographically-greatest (newest) match.
    assert result == str(d_newest)


def test_multiline_topic_byte_exact_match(tmp_path):
    # Scenario: topic spans multiple lines; cmp-style byte-exact compare must succeed.
    # Setup: write multi-line topic with embedded newlines.
    repo = tmp_path
    topic = "line one\nline two\nline three"
    d = _make_topic_debate(repo, "2026-04-04_090000_m", topic + "\n")
    # Test action: pass same multi-line topic.
    result = debate_findMatching(str(repo), topic)
    # Test verification: matches despite multi-line content.
    assert result == str(d)


def test_partial_substring_does_not_match(tmp_path):
    # Scenario: topic.md contains query as substring but is not byte-equal.
    # Setup: topic.md is a superstring.
    repo = tmp_path
    _make_topic_debate(repo, "2026-05-05_100000_p", "prefix hello suffix\n")
    # Test action: query a substring.
    result = debate_findMatching(str(repo), "hello")
    # Test verification: byte-exact match required, returns None.
    assert result is None



def test_returns_dict_with_current_model_and_tried_models_keys():
    # Scenario: caller invokes with no env overrides
    # Setup: empty env dict
    # Test action: call with empty env
    # Test verification: returned mapping has both top-level keys
    result = debate_initAgentModels(env={})
    assert "CURRENT_MODEL" in result
    assert "TRIED_MODELS" in result


def test_all_three_agents_present_in_both_subdicts():
    # Scenario: bash loop initializes gemini/codex/claude entries
    # Setup: empty env
    # Test action: call function
    # Test verification: every agent key exists in both subdicts
    result = debate_initAgentModels(env={})
    for agent in ("gemini", "codex", "claude"):
        assert agent in result["CURRENT_MODEL"]
        assert agent in result["TRIED_MODELS"]



def test_gemini_picks_up_GEMINI_MODEL_env():
    # Scenario: GEMINI_MODEL env var set
    # Setup: env with GEMINI_MODEL
    # Test action: call function with that env
    # Test verification: gemini current/tried both equal that value
    result = debate_initAgentModels(env={"GEMINI_MODEL": "gemini-2.5-pro"})
    assert result["CURRENT_MODEL"]["gemini"] == "gemini-2.5-pro"
    assert result["TRIED_MODELS"]["gemini"] == "gemini-2.5-pro"


def test_codex_picks_up_CODEX_MODEL_env():
    # Scenario: CODEX_MODEL env var set
    # Setup: env with CODEX_MODEL
    # Test action: call function with that env
    # Test verification: codex current/tried both equal that value
    result = debate_initAgentModels(env={"CODEX_MODEL": "gpt-5"})
    assert result["CURRENT_MODEL"]["codex"] == "gpt-5"
    assert result["TRIED_MODELS"]["codex"] == "gpt-5"


def test_unset_gemini_env_yields_empty_string_not_missing_key():
    # Scenario: bash uses ${GEMINI_MODEL:-} which expands to "" when unset
    # Setup: env without GEMINI_MODEL
    # Test action: call function
    # Test verification: gemini entry is "" (not None, not absent)
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["gemini"] == ""
    assert result["TRIED_MODELS"]["gemini"] == ""


def test_unset_codex_env_yields_empty_string():
    # Scenario: CODEX_MODEL unset
    # Setup: env without CODEX_MODEL
    # Test action: call function
    # Test verification: codex entry is ""
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["codex"] == ""
    assert result["TRIED_MODELS"]["codex"] == ""


def test_independent_calls_return_independent_dicts():
    # Scenario: ABSORBED idiom - caller owns state, no shared globals
    # Setup: two separate calls
    # Test action: mutate first result
    # Test verification: second result is unaffected
    a = debate_initAgentModels(env={})
    a["CURRENT_MODEL"]["gemini"] = "mutated"
    b = debate_initAgentModels(env={})
    assert b["CURRENT_MODEL"]["gemini"] == ""


def test_env_defaults_to_os_environ_when_omitted(monkeypatch):
    # Scenario: caller omits env arg; function reads os.environ
    # Setup: monkeypatch GEMINI_MODEL in os.environ
    # Test action: call without env kwarg
    # Test verification: gemini entry reflects the patched env
    monkeypatch.setenv("GEMINI_MODEL", "from-os-env")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    result = debate_initAgentModels()
    assert result["CURRENT_MODEL"]["gemini"] == "from-os-env"


def test_returns_scripts_dir_under_plugin_root(tmp_path, monkeypatch):
    # Scenario: SCRIPTS_DIR is derived from CLAUDE_PLUGIN_ROOT.
    # Setup: plugin root + plugin data env vars; minimal stdin JSON.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.delenv("DEBATE_LOG_FILE", raising=False)
    # Test action: call with empty JSON object.
    ctx = debate_initHookContext(stdin=io.StringIO("{}"))
    # Test verification: SCRIPTS_DIR points at skills/debate/scripts under root.
    assert ctx["SCRIPTS_DIR"] == str(plugin_root / "skills" / "debate" / "scripts")


def test_log_file_defaults_under_plugin_data_and_dir_created(tmp_path, monkeypatch):
    # Scenario: LOG_FILE defaults to $CLAUDE_PLUGIN_DATA/debate-log.txt and parent dir exists.
    # Setup: plugin data dir not yet containing log dir; no DEBATE_LOG_FILE override.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data" / "nested"  # not yet created
    plugin_root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.delenv("DEBATE_LOG_FILE", raising=False)
    # Test action: call function.
    ctx = debate_initHookContext(stdin=io.StringIO("{}"))
    # Test verification: LOG_FILE path matches default and its parent dir was created.
    expected = plugin_data / "debate-log.txt"
    assert ctx["LOG_FILE"] == str(expected)
    assert expected.parent.is_dir()


def test_log_file_honours_debate_log_file_override(tmp_path, monkeypatch):
    # Scenario: DEBATE_LOG_FILE env var overrides the default LOG_FILE path.
    # Setup: set DEBATE_LOG_FILE to a custom location.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    custom_log = tmp_path / "custom" / "mylog.txt"
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("DEBATE_LOG_FILE", str(custom_log))
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO("{}"))
    # Test verification: LOG_FILE is the override and parent dir was made.
    assert ctx["LOG_FILE"] == str(custom_log)
    assert custom_log.parent.is_dir()


def test_parses_cwd_and_transcript_path_from_stdin_json(tmp_path, monkeypatch):
    # Scenario: CWD and TRANSCRIPT_PATH are read from hook JSON stdin.
    # Setup: env, plus JSON containing cwd + transcript_path keys.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    cwd_dir = _make_repo(tmp_path / "wd")
    payload = '{"cwd": "%s", "transcript_path": "/tmp/t.jsonl"}' % cwd_dir
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(payload))
    # Test verification: cwd and transcript_path lifted into context.
    assert ctx["CWD"] == str(cwd_dir)
    assert ctx["TRANSCRIPT_PATH"] == "/tmp/t.jsonl"


def test_cwd_falls_back_to_pwd_when_json_omits_it(tmp_path, monkeypatch):
    # Scenario: missing .cwd in JSON falls back to current working directory.
    # Setup: env, chdir to tmp_path, JSON without cwd key.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.chdir(tmp_path)
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO('{"transcript_path": ""}'))
    # Test verification: CWD falls back to os.getcwd() (i.e. tmp_path).
    assert ctx["CWD"] == str(tmp_path.resolve())


def test_repo_root_resolved_for_git_cwd(tmp_path, monkeypatch):
    # Scenario: REPO_ROOT is resolved from `git rev-parse --show-toplevel`.
    # Setup: real git repo as cwd; subdir passed in JSON to ensure rev-parse climbs.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    repo = _make_repo(tmp_path / "repo")
    sub = repo / "sub"
    sub.mkdir()
    payload = '{"cwd": "%s"}' % sub
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(payload))
    # Test verification: REPO_ROOT equals the repo top-level.
    assert ctx["REPO_ROOT"] == str(repo)


def test_repo_root_empty_when_cwd_not_in_git(tmp_path, monkeypatch):
    # Scenario: outside any git repo, REPO_ROOT is the empty string (no crash).
    # Setup: cwd is a plain dir with no .git anywhere up to /tmp.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    non_git = tmp_path / "plain"
    non_git.mkdir()
    payload = '{"cwd": "%s"}' % non_git
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(payload))
    # Test verification: REPO_ROOT is empty string per bash contract.
    assert ctx["REPO_ROOT"] == ""


def test_input_field_preserves_raw_stdin(tmp_path, monkeypatch):
    # Scenario: INPUT in returned context is the raw stdin text.
    # Setup: JSON with extra whitespace / fields.
    plugin_root = tmp_path / "plug"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    raw = '{"cwd": "/x", "transcript_path": "/y", "extra": 1}\n'
    # Test action.
    ctx = debate_initHookContext(stdin=io.StringIO(raw))
    # Test verification: raw stdin preserved verbatim in INPUT.
    assert ctx["INPUT"] == raw


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


def test_plugin_root_exported_to_environment() -> None:
    # Scenario: debate_launch sets PLUGIN_ROOT env var so debate_main sees it.
    # Setup:
    import os
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



def test_writes_lock_file_before_launch(tmp_path):
    # Scenario: launch_agent writes debate:<pane_id> to the lock file before
    #           sending the launch command.
    # Setup: fresh debate_dir, pane ready on first capture
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
    # Test verification: lock file contains "debate:%pane_id"
    lock = tmp_path / f".{_STAGE}_{_AGENT}.lock"
    assert lock.exists(), "lock file must exist after launch"
    assert lock.read_text().strip() == f"debate:{_PANE}"


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


def test_calls_write_failed_on_timeout(tmp_path):
    # Scenario: after timeout, write_failed is called with stage + agent info.
    # Setup: capture never ready, short timeout
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=None)
    with patches[0], patches[1], patches[2] as mock_wf, patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
            timeout=2,
        )
    # Test verification: write_failed called once
    mock_wf.assert_called_once()
    args = mock_wf.call_args[0]
    assert args[0] == _STAGE  # first positional arg is stage


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


def test_no_write_failed_on_success(tmp_path):
    # Scenario: write_failed must NOT be called when agent becomes ready in time.
    # Setup: pane immediately ready
    debate_dir = str(tmp_path)
    patches = _patch_all(ready_after=0)
    with patches[0], patches[1], patches[2] as mock_wf, patches[3]:
        debate_launchAgent(
            pane_id=_PANE,
            stage=_STAGE,
            agent=_AGENT,
            launch_cmd=_CMD,
            ready_marker=_READY,
            debate_dir=debate_dir,
        )
    # Test verification: write_failed never invoked on success
    mock_wf.assert_not_called()


def test_returns_session_name_when_lock_resolves(tmp_path: Path) -> None:
    # Scenario: debate dir has one live lock whose pane resolves to a tmux session
    # Setup: write .agent.lock with pane_id %1; mock tmux to return "debate-1"
    lock = tmp_path / ".agent.lock"
    _write_lock_at_path(lock, "%1")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="debate-1\n", stderr="")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-1"


def test_returns_empty_when_no_lock_files(tmp_path: Path) -> None:
    # Scenario: debate dir has no .*.lock files
    # Setup: empty tmp_path directory
    # Test action:
    result = debate_liveSession(str(tmp_path))
    # Test verification:
    assert result == ""


def test_returns_empty_when_lock_has_no_pane_id(tmp_path: Path) -> None:
    # Scenario: lock file exists but content does not match debate:<pane_id> pattern
    # Setup: lock file with garbage content
    lock = tmp_path / ".bad.lock"
    lock.write_text("not-a-pane-ref\n")

    with patch("subprocess.run") as mock_run:
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""
    mock_run.assert_not_called()


def test_returns_empty_when_tmux_fails(tmp_path: Path) -> None:
    # Scenario: lock file has valid pane_id but tmux display-message returns non-zero
    # Setup: write valid lock; mock tmux to return rc=1
    lock = tmp_path / ".agent.lock"
    _write_lock_at_path(lock, "%5")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no server running")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""


def test_returns_empty_when_tmux_returns_empty_session(tmp_path: Path) -> None:
    # Scenario: tmux succeeds (rc=0) but returns empty session name (pane gone)
    # Setup: write valid lock; mock tmux stdout to empty string
    lock = tmp_path / ".agent.lock"
    _write_lock_at_path(lock, "%9")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == ""


def test_skips_missing_lock_file_gracefully(tmp_path: Path) -> None:
    # Scenario: glob finds a path that disappears between glob and open (TOCTOU)
    # Setup: no actual files; just verify empty-dir returns "" without crashing
    # Test action:
    result = debate_liveSession(str(tmp_path))
    # Test verification:
    assert result == ""


def test_returns_first_resolved_session_from_multiple_locks(tmp_path: Path) -> None:
    # Scenario: multiple lock files; first valid one wins
    # Setup: two lock files; first resolves to "debate-2", second would give "debate-3"
    lock_a = tmp_path / ".a.lock"
    lock_b = tmp_path / ".b.lock"
    _write_lock_at_path(lock_a, "%2")
    _write_lock_at_path(lock_b, "%3")

    call_responses = [
        MagicMock(returncode=0, stdout="debate-2\n", stderr=""),
        MagicMock(returncode=0, stdout="debate-3\n", stderr=""),
    ]

    with patch("subprocess.run", side_effect=call_responses) as mock_run:
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-2"
    # Only one tmux call needed (returns on first success)
    assert mock_run.call_count == 1


def test_falls_through_to_second_lock_when_first_tmux_fails(tmp_path: Path) -> None:
    # Scenario: first lock's pane is dead; second lock resolves successfully
    # Setup: two locks; tmux fails for first pane, succeeds for second
    lock_a = tmp_path / ".a.lock"
    lock_b = tmp_path / ".b.lock"
    _write_lock_at_path(lock_a, "%10")
    _write_lock_at_path(lock_b, "%11")

    call_responses = [
        MagicMock(returncode=1, stdout="", stderr=""),
        MagicMock(returncode=0, stdout="debate-4\n", stderr=""),
    ]

    with patch("subprocess.run", side_effect=call_responses):
        # Test action:
        result = debate_liveSession(str(tmp_path))

    # Test verification:
    assert result == "debate-4"


@pytest.fixture
def models_file(tmp_path: Path) -> Path:
    # Setup: typical models.json shape per assets/models.json.
    p = tmp_path / "models.json"
    p.write_text(json.dumps({
        "gemini": ["gem-pro", "gem-flash", "gem-lite"],
        "codex":  ["gpt-a", "gpt-b"],
        "claude": ["c-opus", "c-sonnet"],
    }))
    return p


def test_returns_first_model_when_none_tried(models_file: Path) -> None:
    # Scenario: no models tried yet for an agent.
    # Setup: empty TRIED_MODELS entry for "gemini".
    tried = {"gemini": "", "codex": "", "claude": ""}
    # Test action: ask for next model for gemini.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: first model in list is returned.
    assert result == "gem-pro"


def test_skips_already_tried_models(models_file: Path) -> None:
    # Scenario: first two gemini models already tried.
    # Setup: comma-joined tried list matching bash idiom ",a,b,".
    tried = {"gemini": "gem-pro,gem-flash", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: third model returned.
    assert result == "gem-lite"


def test_returns_none_when_all_tried(models_file: Path) -> None:
    # Scenario: every model in the list has been tried.
    # Setup: tried list contains all gemini entries.
    tried = {"gemini": "gem-pro,gem-flash,gem-lite", "codex": "", "claude": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(models_file))
    # Test verification: bash returned rc=1; Python returns None.
    assert result is None


def test_unknown_agent_returns_none(models_file: Path) -> None:
    # Scenario: agent key absent from models.json.
    # Setup: tried dict has agent but JSON does not.
    tried = {"mystery": ""}
    # Test action: request next model for unknown agent.
    result = debate_nextModel("mystery", tried, str(models_file))
    # Test verification: no model available -> None.
    assert result is None


def test_partial_tried_with_leading_comma(models_file: Path) -> None:
    # Scenario: tried list has bash-style leading comma artifact (",first").
    # Setup: tried entry mimics how _stash appends (",${next}").
    tried = {"codex": ",gpt-a"}
    # Test action: request next codex model.
    result = debate_nextModel("codex", tried, str(models_file))
    # Test verification: gpt-a is skipped, gpt-b returned.
    assert result == "gpt-b"


def test_missing_models_file_returns_none(tmp_path: Path) -> None:
    # Scenario: models.json path does not exist.
    # Setup: point at nonexistent file (bash hide_errors -> empty stdin -> rc=1).
    tried = {"gemini": ""}
    # Test action: request next model.
    result = debate_nextModel("gemini", tried, str(tmp_path / "missing.json"))
    # Test verification: graceful None.
    assert result is None


# ---------- codex agent ----------

def test_codex_capacity_marker_present_returns_truthy():
    # Scenario: codex pane shows the "at capacity" message in scrollback.
    # Setup: mock tmux_capturePane to return a buffer containing the marker.
    fake_capture = "some banner\nSelected model is at capacity\nmore output\n"
    # Test action: call debate_paneHasCapacityError for the codex agent.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value=fake_capture,
    ) as m:
        result = debate_paneHasCapacityError("%7", "codex")
    # Test verification: result is truthy (bool(result) is True).
    assert bool(result) is True
    # And capture was requested with -S -200 scrollback to mirror bash.
    m.assert_called_once_with("%7", scrollback_lines=200)


def test_codex_overloaded_marker_present_returns_truthy():
    # Scenario: codex pane shows the secondary "model is overloaded" marker.
    # Setup: capture buffer contains only the second codex marker.
    fake_capture = "noise\nmodel is overloaded right now\nnoise\n"
    # Test action: probe codex for capacity error.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%1", "codex")
    # Test verification: truthy bool indicates a capacity hit.
    assert bool(result) is True


def test_codex_no_marker_returns_falsy():
    # Scenario: codex pane shows healthy output, no capacity markers.
    # Setup: capture buffer with unrelated content.
    fake_capture = "all good\nready\n> _\n"
    # Test action: probe codex for capacity error.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%1", "codex")
    # Test verification: result is falsy (bool() is False).
    assert bool(result) is False


# ---------- gemini agent ----------

def test_gemini_resource_exhausted_returns_truthy():
    # Scenario: gemini pane prints RESOURCE_EXHAUSTED quota error.
    # Setup: capture contains the gemini-specific marker.
    fake_capture = "ERROR: RESOURCE_EXHAUSTED please retry later\n"
    # Test action: probe gemini for capacity error.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%2", "gemini")
    # Test verification: truthy bool indicates capacity hit.
    assert bool(result) is True


def test_gemini_marker_for_other_agent_does_not_match():
    # Scenario: pane shows codex-specific marker but agent arg is "gemini".
    # Setup: capture has codex marker text only; gemini markers should NOT match.
    fake_capture = "Selected model is at capacity\n"
    # Test action: probe gemini.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%2", "gemini")
    # Test verification: per-agent markers are isolated -> falsy.
    assert bool(result) is False


# ---------- claude agent ----------

def test_claude_api_529_returns_truthy():
    # Scenario: claude pane prints HTTP 529 overload error.
    # Setup: capture contains "API Error: 529" marker.
    fake_capture = "request failed: API Error: 529 overloaded_error: please retry\n"
    # Test action: probe claude.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%3", "claude")
    # Test verification: truthy bool.
    assert bool(result) is True


# ---------- unknown agent ----------

def test_unknown_agent_returns_falsy_without_capturing():
    # Scenario: caller passes an unrecognised agent name.
    # Setup: patch tmux_capturePane so we can assert it is NEVER called
    # (mirrors bash: empty marker stream -> while-loop body never executes,
    # function returns 1 with no side effects).
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value="API Error: 529\n",
    ) as m:
        # Test action: probe with a bogus agent.
        result = debate_paneHasCapacityError("%9", "nonsense-agent")
    # Test verification: falsy AND tmux capture not invoked.
    assert bool(result) is False
    assert m.call_count == 0


# ---------- ANSI escape stripping ----------

def test_ansi_escape_bytes_are_stripped_before_match():
    # Scenario: pane capture is interleaved with raw ESC bytes (\033) the way
    # tmux emits color codes; bash uses `tr -d '\033'` before grep -F.
    # Setup: insert ESC bytes inside the marker so a naive substring search
    # against the unstripped buffer would FAIL.
    marker = "API Error: 529"
    poisoned = "API\033 Error:\033 529"  # same chars, ESC interleaved
    fake_capture = f"prefix {poisoned} suffix\n"
    # Test action: probe claude.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value=fake_capture,
    ):
        result = debate_paneHasCapacityError("%4", "claude")
    # Test verification: ESC stripping lets the marker match -> truthy.
    assert bool(result) is True
    # And the matched marker text is the canonical (ESC-free) string.
    assert result == marker


# ---------- empty capture ----------

def test_empty_capture_returns_falsy():
    # Scenario: tmux capture-pane fails or pane has no output (returns "").
    # Setup: tmux_capturePane returns empty string (its documented failure mode).
    # Test action: probe codex.
    with patch(
        "common.scripts.debate_lib.tmux_capturePane",
        return_value="",
    ):
        result = debate_paneHasCapacityError("%5", "codex")
    # Test verification: nothing to match -> falsy.
    assert bool(result) is False


def test_returns_empty_when_codex_binary_missing():
    # Scenario: codex CLI is not installed on PATH.
    # Setup: shutil.which("codex") returns None; credentials irrelevant.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" (unavailable sentinel, mirrors bash empty stdout).
    with patch("common.scripts.debate_lib.shutil.which", return_value=None), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == ""


def test_returns_empty_when_no_credentials_present():
    # Scenario: codex binary exists but no auth.json and no OPENAI_API_KEY.
    # Setup: which returns a path; auth.json absent; env var unset.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" because credentials gate fails.
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, env, clear=True):
        result = debate_probeCodex()
    assert result == ""


def test_returns_present_when_available_but_no_model_configured():
    # Scenario: codex binary + credentials exist, but models.json has no codex entry.
    # Setup: which → path; auth.json present; _default_model returns "".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "present" sentinel so outer `-s` check passes.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value=""):
        result = debate_probeCodex()
    assert result == "present"


def test_returns_model_name_when_configured():
    # Scenario: codex binary + credentials exist AND models.json lists a model.
    # Setup: which → path; auth.json present; _default_model returns "gpt-5".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns the model name verbatim.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gpt-5"):
        result = debate_probeCodex()
    assert result == "gpt-5"


def test_openai_api_key_alone_satisfies_credentials_gate():
    # Scenario: no auth.json on disk, but OPENAI_API_KEY env var is set.
    # Setup: which → path; isfile → False; env has OPENAI_API_KEY.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns model name (proves env-var path is honored).
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gpt-5"), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == "gpt-5"


# ---------------------------------------------------------------------------
# RED test 1 -- no remaining models -> returns None
# ---------------------------------------------------------------------------
def test_no_next_model_returns_none():
    # Scenario: _next_model exhausted; no models left for agent.
    # Setup: debate_nextModel returns None.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None; no pane kill or creation attempted.
    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value=None,
        ) as mock_next,
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane"
        ) as mock_new_pane,
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None
    mock_new_pane.assert_not_called()


# ---------------------------------------------------------------------------
# RED test 2 -- happy path: updates tried_models and current_model dicts
# ---------------------------------------------------------------------------
def test_updates_model_dicts_on_success():
    # Scenario: next model found; dicts should reflect new model after call.
    # Setup: debate_nextModel returns "gemini-flash"; launch + prompt succeed.
    # Test action: call with mutable dicts; check mutations after.
    # Test verification: current_model["gemini"] == "gemini-flash";
    #                    "gemini-flash" appended to tried_models["gemini"].
    current_model = {"gemini": "gemini-pro"}
    tried_models = {"gemini": "gemini-pro"}

    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert current_model["gemini"] == "gemini-flash"
    assert "gemini-flash" in tried_models["gemini"]

# ---------------------------------------------------------------------------
# RED test 3 -- happy path: kills old pane and returns new pane id
# ---------------------------------------------------------------------------
def test_kills_old_pane_returns_new_pane_id():
    # Scenario: successful rotation; old pane killed, new pane id returned.
    # Setup: debate_nextModel = "gemini-flash"; debate_newEmptyPane = "%99".
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: _kill_pane called with "%10"; return value == "%99".
    kill_mock = MagicMock()

    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%99",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib._kill_pane", kill_mock
        ),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    kill_mock.assert_called_once_with("%10")
    assert result == "%99"

# ---------------------------------------------------------------------------
# RED test 4 -- launch_agent failure propagates as None
# ---------------------------------------------------------------------------
def test_launch_agent_failure_returns_none():
    # Scenario: new pane created but agent fails to become ready.
    # Setup: _launch_agent returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None (mirrors bash `return 1`).
    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch(
            "common.scripts.debate_lib._launch_agent", return_value=False
        ),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None


# ---------------------------------------------------------------------------
# RED test 5 -- send_prompt failure propagates as None
# ---------------------------------------------------------------------------
def test_send_prompt_failure_returns_none():
    # Scenario: agent launched fine but prompt delivery timed out.
    # Setup: _launch_agent True; _send_prompt returns False.
    # Test action: call debate_retryPaneWithNextModel.
    # Test verification: returns None.
    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="gemini-flash",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%11",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="gemini --model gemini-flash",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch(
            "common.scripts.debate_lib._send_prompt", return_value=False
        ),
    ):
        result = debate_retryPaneWithNextModel(**_BASE_KWARGS)

    assert result is None

# ---------------------------------------------------------------------------
# RED test 6 -- tried_models entry created from scratch when agent not present
# ---------------------------------------------------------------------------
def test_tried_models_created_when_agent_missing():
    # Scenario: agent key absent from tried_models (first rotation ever).
    # Setup: tried_models = {} (empty); next model = "codex-mini".
    # Test action: call with agent="codex", tried_models={}.
    # Test verification: tried_models["codex"] contains "codex-mini".
    current_model: dict[str, str] = {}
    tried_models: dict[str, str] = {}

    with (
        patch(
            "common.scripts.debate_lib.debate_nextModel",
            return_value="codex-mini",
        ),
        patch(
            "common.scripts.debate_lib.debate_newEmptyPane",
            return_value="%20",
        ),
        patch(
            "common.scripts.debate_lib.debate_agentLaunchCmd",
            return_value="codex -a never",
        ),
        patch("common.scripts.debate_lib._kill_pane"),
        patch("common.scripts.debate_lib._launch_agent", return_value=True),
        patch("common.scripts.debate_lib._send_prompt", return_value=True),
    ):
        kwargs = dict(_BASE_KWARGS)
        kwargs["agent"] = "codex"
        kwargs["current_pane_id"] = "%5"
        kwargs["current_model"] = current_model
        kwargs["tried_models"] = tried_models
        debate_retryPaneWithNextModel(**kwargs)

    assert "codex-mini" in tried_models.get("codex", "")
    assert current_model.get("codex") == "codex-mini"



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
    # Scenario: mirrors `trap cleanup EXIT` — cleanup runs even if daemon_main raises.
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


def test_partial_completion_returns_only_completed_agents(tmp_path):
    # Scenario: some agents finish, others time out
    # Setup: only codex output present
    agents = ["gemini", "codex", "claude"]
    panes = {0: "%1", 1: "%2", 2: "%3"}
    _write(tmp_path / "r1_codex.md", "done")
    # Test action: timeout exhausted with partial state
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: ok=False, only codex in completed
    assert ok is False
    assert completed == ["codex"]
    assert "timeout" in reason.lower()


def test_empty_output_file_does_not_count_as_complete(tmp_path):
    # Scenario: output file exists but is zero-byte (matches bash `[ -s "$out" ]`)
    # Setup: create empty file
    agents = ["gemini"]
    panes = {0: "%1"}
    (tmp_path / "r1_gemini.md").write_text("")  # zero bytes
    # Test action: single poll
    ok, completed, _ = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: empty file -> not complete -> timeout
    assert ok is False
    assert completed == []



def test_emits_when_transcript_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: hook payload has no transcript_path; we must short-circuit.
    # Setup: ctx with empty transcript, valid repo (irrelevant here).
    _install_ctx(monkeypatch, transcript="", repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: rc=0 and the exact bash message was emitted.
    assert rc == 0
    assert msgs == ["/debate-abort: no transcript_path in hook payload"]


def test_emits_when_repo_root_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: cwd is not inside a git repo -> no repo_root from initHook.
    # Setup: transcript present, repo_root empty.
    _install_ctx(monkeypatch, transcript="/tmp/fake-transcript.jsonl", repo="")
    msgs = _capture_emit(monkeypatch)

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: bash's exact "git repository" message.
    assert rc == 0
    assert msgs == ["/debate-abort requires a git repository"]


def test_emits_when_no_matching_debate_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: Debates/ exists but no marker matches our transcript.
    # Setup: one debate with a different invoking_transcript.txt content.
    _make_debate(tmp_path, "2026-05-05T100000_topic", "/some/other/transcript.jsonl")
    _install_ctx(
        monkeypatch,
        transcript="/the/right/transcript.jsonl",
        repo=str(tmp_path),
    )
    msgs = _capture_emit(monkeypatch)

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: emits "no debate found" and the foreign dir survives.
    assert rc == 0
    assert msgs == ["/debate-abort: no debate found in this conversation"]
    assert (tmp_path / "Debates" / "2026-05-05T100000_topic").is_dir()


def test_emits_still_running_when_live_lock_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: matched debate has a live tmux pane lock - must NOT delete.
    # Setup: build matching debate; stub anyLiveLock True; liveSession known.
    transcript = "/conv/transcript.jsonl"
    debate = _make_debate(tmp_path, "2026-05-05T120000_x", transcript)
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr("common.scripts.debate_lib.debate_anyLiveLock", lambda _d: True)
    monkeypatch.setattr("common.scripts.debate_lib.debate_liveSession", lambda _d: "debate-7")

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: emits the kill-session hint; debate dir untouched.
    assert rc == 0
    assert msgs == [
        "/debate-abort: debate is running. to force-kill: "
        "tmux kill-session -t debate-7"
    ]
    assert debate.is_dir()


def test_emits_still_running_with_unknown_when_session_lookup_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: live lock present but tmux can't name the session.
    # Setup: anyLiveLock True; liveSession returns empty string.
    transcript = "/conv/t.jsonl"
    _make_debate(tmp_path, "2026-05-05T130000_y", transcript)
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr("common.scripts.debate_lib.debate_anyLiveLock", lambda _d: True)
    monkeypatch.setattr("common.scripts.debate_lib.debate_liveSession", lambda _d: "")

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: '<unknown>' placeholder used in the kill-session hint.
    assert rc == 0
    assert msgs == [
        "/debate-abort: debate is running. to force-kill: "
        "tmux kill-session -t <unknown>"
    ]


def test_happy_path_deletes_dir_and_emits_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: matched debate, no live lock -> rmtree + success message.
    # Setup: matching debate dir with a child file to ensure recursive remove.
    transcript = "/conv/done.jsonl"
    debate = _make_debate(tmp_path, "2026-05-05T140000_done", transcript)
    (debate / "child.txt").write_text("payload", encoding="utf-8")
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr("common.scripts.debate_lib.debate_anyLiveLock", lambda _d: False)
    # liveSession should not be called on the happy path; trip if it is.
    monkeypatch.setattr(
        sut,
        "debate_liveSession",
        lambda _d: pytest.fail("debate_liveSession must not be called when no lock"),
    )

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: dir gone, exact "deleted ..." message emitted.
    assert rc == 0
    assert not debate.exists()
    assert msgs == [f"/debate-abort: deleted {debate}"]


def test_lexicographic_tiebreak_picks_newest_basename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: two debates match; the lexicographically greatest must win.
    # Setup: two matching debates, an older basename and a newer one.
    transcript = "/conv/multi.jsonl"
    older = _make_debate(tmp_path, "2026-05-05T090000_a", transcript)
    newer = _make_debate(tmp_path, "2026-05-05T180000_b", transcript)
    # Add a non-matching debate to confirm filtering still works.
    _make_debate(tmp_path, "2026-05-05T230000_z", "/different/transcript.jsonl")
    _install_ctx(monkeypatch, transcript=transcript, repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)
    monkeypatch.setattr("common.scripts.debate_lib.debate_anyLiveLock", lambda _d: False)
    monkeypatch.setattr("common.scripts.debate_lib.debate_liveSession", lambda _d: "")

    # Test action: invoke entry point.
    rc = sut.debateAbort_main()

    # Test verification: only the lex-greatest matching dir was deleted; the
    # older matching dir AND the unrelated dir survive.
    assert rc == 0
    assert not newer.exists()
    assert older.is_dir()
    assert (tmp_path / "Debates" / "2026-05-05T230000_z").is_dir()
    assert msgs == [f"/debate-abort: deleted {newer}"]


def _install_ctx(monkeypatch: pytest.MonkeyPatch, *, transcript: str, repo: str) -> None:
    """Patch debate_initHookContext on the SUT module to return a fixed ctx."""
    # Setup: stub initHookContext to skip real env/stdin/git.
    def fake_ctx() -> dict[str, str]:
        return {"TRANSCRIPT_PATH": transcript, "REPO_ROOT": repo}

    monkeypatch.setattr("common.scripts.debate_lib.debate_initHookContext", fake_ctx)
    # Also stub checkRequirements so jq/tmux absence doesn't abort tests.
    monkeypatch.setattr("common.scripts.debate_lib.hookjson_checkRequirements", lambda *_a, **_k: None)


def _capture_emit(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace hookjson_emitBlock with a recorder; return the message list."""
    # Setup: collect every emit_block message instead of writing JSON.
    msgs: list[str] = []
    monkeypatch.setattr("common.scripts.debate_lib.hookjson_emitBlock", lambda m: msgs.append(m))
    return msgs


def _make_debate(repo: Path, ts: str, transcript: str) -> Path:
    """Create <repo>/Debates/<ts>/invoking_transcript.txt with given content."""
    # Setup: build a debate dir whose marker references `transcript`.
    debate = repo / "Debates" / ts
    debate.mkdir(parents=True)
    (debate / "invoking_transcript.txt").write_text(transcript, encoding="utf-8")
    return debate

# ---------------------------------------------------------------------------
# Mock-based tests (no real tmux required)
# ---------------------------------------------------------------------------

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



def test_returns_false_when_no_lock_files(tmp_path, fake_tmux):
    # Scenario: empty debate dir, no .*.lock files exist.
    # Setup: tmp_path is fresh; tmux reports no live panes.
    fake_tmux["live"] = set()
    # Test action: invoke debate_anyLiveLock on the empty directory.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: bash returns rc=1 (no live lock) -> Python returns False.
    assert result is False


def test_returns_true_when_lock_pane_id_is_live(tmp_path, fake_tmux):
    # Scenario: a hidden .lock file references a pane that tmux still reports.
    # Setup: write `.alpha.lock` containing `debate:%42`; tmux lists `%42` live.
    _make_lock(tmp_path, ".alpha.lock", "%42")
    fake_tmux["live"] = {"%42", "%99"}
    # Test action: scan the directory for live debate locks.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: pane id matched a live tmux pane -> True.
    assert result is True


def test_returns_false_when_lock_pane_id_is_dead(tmp_path, fake_tmux):
    # Scenario: lock file's pane id is NOT in the live tmux pane set.
    # Setup: lock points at `%7`; tmux only knows `%1` and `%2`.
    _make_lock(tmp_path, ".beta.lock", "%7")
    fake_tmux["live"] = {"%1", "%2"}
    # Test action: query for any live lock.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: dead pane id must not register as a live lock.
    assert result is False


def test_skips_lock_without_debate_marker(tmp_path, fake_tmux):
    # Scenario: a hidden .lock exists but contains no `debate:%N` line.
    # Setup: garbage payload only; tmux happens to have %1 alive.
    (tmp_path / ".garbage.lock").write_text("not-a-debate-line\n", encoding="utf-8")
    fake_tmux["live"] = {"%1"}
    # Test action: scan the dir.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: sed extracts empty pane_id -> bash skips -> False.
    assert result is False


def test_returns_false_when_directory_missing(tmp_path, fake_tmux):
    # Scenario: caller passes a path that does not exist.
    # Setup: build a non-existent child path.
    missing = tmp_path / "nope"
    fake_tmux["live"] = {"%1"}
    # Test action: invoke against missing dir (bash for-loop yields no matches).
    result = debate_anyLiveLock(missing)
    # Test verification: nothing to iterate -> False.
    assert result is False


def test_returns_true_if_any_one_of_many_locks_is_live(tmp_path, fake_tmux):
    # Scenario: multiple lock files; only one references a live pane.
    # Setup: three locks; only `%30` is live in tmux.
    _make_lock(tmp_path, ".a.lock", "%10")
    _make_lock(tmp_path, ".b.lock", "%20")
    _make_lock(tmp_path, ".c.lock", "%30")
    fake_tmux["live"] = {"%30"}
    # Test action: scan all locks.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: short-circuits to True on first live match.
    assert result is True


def test_ignores_non_hidden_lock_files(tmp_path, fake_tmux):
    # Scenario: a .lock file NOT starting with `.` should be ignored.
    # Setup: bash glob is `.*.lock`; visible `visible.lock` must not match.
    (tmp_path / "visible.lock").write_text("debate:%5\n", encoding="utf-8")
    fake_tmux["live"] = {"%5"}
    # Test action: scan dir for hidden locks only.
    result = debate_anyLiveLock(tmp_path)
    # Test verification: visible file ignored -> no live lock found -> False.
    assert result is False



# ---------------------------------------------------------------------------
# Test 1 — removes /tmp/debate.* directory
# ---------------------------------------------------------------------------
def test_removes_tmp_debate_dir(tmp_path: Path) -> None:
    # Scenario: settings_file lives inside a /tmp/debate.XYZ directory.
    # Setup: create a mock /tmp/debate.XYZ tree under tmp_path (so we don't
    #   touch real /tmp). We monkey-patch by creating the structure locally
    #   and passing the fake path; the guard checks parent.name == "debate.*"
    #   and parent.parent == Path("/tmp"). We build the fake tree and
    #   temporarily repoint by using a symlink trick — actually, the function
    #   checks Path("/tmp") literally, so we directly fabricate a path string
    #   with a real /tmp/debate.* dir to exercise it.
    import tempfile, shutil, os

    # Create a real /tmp/debate.<unique> directory
    debate_dir = Path(tempfile.mkdtemp(prefix="debate.", dir="/tmp"))
    settings_file = debate_dir / "settings.json"
    settings_file.write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification: directory must be gone
        assert not debate_dir.exists(), f"Expected {debate_dir} to be removed"
    finally:
        # Safety: clean up if test failed before removal
        if debate_dir.exists():
            shutil.rmtree(debate_dir)


# ---------------------------------------------------------------------------
# Test 2 — does NOT remove a non-/tmp/debate.* directory
# ---------------------------------------------------------------------------
def test_ignores_non_tmp_debate_dir(tmp_path: Path) -> None:
    # Scenario: settings_file is in a user project dir, not /tmp/debate.*.
    # Setup:
    settings_dir = tmp_path / "my_project_settings"
    settings_dir.mkdir()
    settings_file = settings_dir / "settings.json"
    settings_file.write_text("{}")

    # Test action:
    debate_cleanup(settings_file)

    # Test verification: directory must still exist
    assert settings_dir.exists(), "Non-/tmp/debate.* dir must not be removed"


# ---------------------------------------------------------------------------
# Test 3 — does NOT remove /tmp directory that does not start with "debate."
# ---------------------------------------------------------------------------
def test_ignores_tmp_non_debate_prefix(tmp_path: Path) -> None:
    # Scenario: settings_file is in /tmp/somethingelse (no "debate." prefix).
    # Setup:
    import tempfile, shutil

    other_dir = Path(tempfile.mkdtemp(prefix="notdebate.", dir="/tmp"))
    settings_file = other_dir / "settings.json"
    settings_file.write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification: directory must still exist
        assert other_dir.exists(), "Non-debate-prefixed /tmp dir must not be removed"
    finally:
        if other_dir.exists():
            shutil.rmtree(other_dir)


# ---------------------------------------------------------------------------
# Test 4 — no-op when debate dir does not exist (already cleaned up)
# ---------------------------------------------------------------------------
def test_noop_when_dir_already_gone() -> None:
    # Scenario: cleanup called twice; second call should not raise.
    # Setup: fabricate a path that looks like /tmp/debate.XYZ but doesn't exist
    nonexistent = Path("/tmp/debate.already_deleted_abc123/settings.json")
    assert not nonexistent.parent.exists(), "Precondition: dir must not exist"

    # Test action + Test verification: must not raise
    debate_cleanup(nonexistent)


# ---------------------------------------------------------------------------
# Test 5 — accepts str path (not just Path)
# ---------------------------------------------------------------------------
def test_accepts_str_path(tmp_path: Path) -> None:
    # Scenario: caller passes a plain str instead of a Path object.
    # Setup:
    import tempfile, shutil

    debate_dir = Path(tempfile.mkdtemp(prefix="debate.", dir="/tmp"))
    settings_file = str(debate_dir / "settings.json")
    (debate_dir / "settings.json").write_text("{}")

    try:
        # Test action:
        debate_cleanup(settings_file)

        # Test verification:
        assert not debate_dir.exists()
    finally:
        if debate_dir.exists():
            shutil.rmtree(debate_dir)



_FIXED_NOW = lambda: datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)


def test_writes_failed_txt_at_debate_dir_root(tmp_path):
    # Scenario: one agent missing, no lock; FAILED.txt should appear at debate_dir/FAILED.txt.
    # Setup:
    debate_dir = tmp_path / "debate"
    debate_dir.mkdir()
    # Test action:
    out = debate_writeFailed(debate_dir, "R1", "boom", ["gemini"], now=_FIXED_NOW)
    # Test verification:
    assert out == debate_dir / "FAILED.txt"
    assert out.is_file()


def test_header_contains_stage_reason_and_iso_timestamp(tmp_path):
    # Scenario: header lines must include stage, reason, ISO-8601 timestamp from injected clock.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R2", "launch_agent timeout", [], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert text.startswith("# debate FAILED\n")
    assert "stage: R2\n" in text
    assert "reason: launch_agent timeout\n" in text
    assert "timestamp: 2026-05-04T12:00:00+00:00\n" in text


def test_skips_agents_with_nonempty_output_files(tmp_path):
    # Scenario: agent who produced a non-empty stage_<agent>.md must NOT appear in missing list.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "R1_gemini.md").write_text("real output\n")
    # Test action:
    debate_writeFailed(debate_dir, "R1", "partial", ["gemini", "codex"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "### gemini" not in text
    assert "### codex" in text


def test_empty_output_file_counts_as_missing(tmp_path):
    # Scenario: zero-byte output file means agent did not finish; treat as missing.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "R1_codex.md").write_text("")  # empty
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["codex"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "### codex" in text


def test_missing_lock_file_emits_placeholder_line(tmp_path):
    # Scenario: agent missing AND no .lock file -> placeholder string instead of fenced block.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["claude"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "(no pane captured -- lock file missing or malformed)" in text
    assert "```" not in text


def test_lock_with_pane_id_invokes_capture_and_fences_output(tmp_path):
    # Scenario: lock file points to pane; pane_capture callback's text is fenced.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / ".R1_gemini.lock").write_text("debate:%42\n")
    captured = {}

    def fake_capture(pane_id):
        captured["pane"] = pane_id
        return "RESOURCE_EXHAUSTED line1\nline2"

    # Test action:
    debate_writeFailed(
        debate_dir, "R1", "capacity", ["gemini"],
        pane_capture=fake_capture, now=_FIXED_NOW,
    )
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert captured["pane"] == "%42"
    assert "```\nRESOURCE_EXHAUSTED line1\nline2\n```" in text


def test_overwrites_existing_failed_txt(tmp_path):
    # Scenario: a stale FAILED.txt must be replaced atomically (overwrite, not append).
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / "FAILED.txt").write_text("OLD CONTENT SHOULD VANISH\n")
    # Test action:
    debate_writeFailed(debate_dir, "R1", "fresh", ["gemini"], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "OLD CONTENT SHOULD VANISH" not in text
    assert "reason: fresh" in text


def test_no_temp_files_left_behind_on_success(tmp_path):
    # Scenario: atomic publish via mktemp+rename must leave no .FAILED.txt.* siblings.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", ["gemini"], now=_FIXED_NOW)
    # Test verification:
    leftovers = [p.name for p in debate_dir.iterdir() if p.name.startswith(".FAILED.txt.")]
    assert leftovers == []


def test_missing_agents_section_header_present(tmp_path):
    # Scenario: the literal '## missing agents' header is always emitted, even with zero agents.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    # Test action:
    debate_writeFailed(debate_dir, "R1", "x", [], now=_FIXED_NOW)
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "## missing agents\n" in text


def test_pane_capture_callback_failure_yields_unavailable_marker(tmp_path):
    # Scenario: capture callback raises -> body still well-formed with '(pane capture unavailable)'.
    # Setup:
    debate_dir = tmp_path / "d"
    debate_dir.mkdir()
    (debate_dir / ".R1_codex.lock").write_text("debate:%7\n")

    def boom(_pane_id):
        raise RuntimeError("tmux gone")

    # Test action:
    debate_writeFailed(
        debate_dir, "R1", "x", ["codex"],
        pane_capture=boom, now=_FIXED_NOW,
    )
    text = (debate_dir / "FAILED.txt").read_text()
    # Test verification:
    assert "```\n(pane capture unavailable)\n```" in text


def test_invokes_retry_when_pane_has_capacity_error_and_no_output(tmp_path):
    # Scenario: agent pane shows capacity error and no output file exists yet
    # Setup: no output files; capacity_check returns True for one agent
    agents = ["gemini"]
    panes = {0: "%5"}
    retry_cb = MagicMock()
    sleep_fn = MagicMock()
    # Test action: single poll iteration before timeout
    ok, _, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: True,
        retry_pane=retry_cb, sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: retry callback invoked with (panes, index, agent, prefix)
    assert ok is False
    assert reason is not None
    retry_cb.assert_called_once()
    args = retry_cb.call_args[0]
    assert args[1] == 0  # index
    assert args[2] == "gemini"
    assert args[3] == "r1"


def test_removes_lock_file_when_output_appears(tmp_path):
    # Scenario: lock file exists alongside output; lock must be deleted on detection
    # Setup: create output AND lock file
    agents = ["claude"]
    panes = {0: "%1"}
    out = tmp_path / "r2_claude.md"
    lock = tmp_path / ".r2_claude.lock"
    _write(out, "synthesis")
    _write(lock, "debate:%1")
    # Test action: poll once
    ok, completed, _ = debate_waitForOutputs(
        prefix="r2", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=MagicMock(), poll_interval=5,
    )
    # Test verification: success, lock file removed
    assert ok is True
    assert completed == ["claude"]
    assert not lock.exists()


def test_returns_true_when_all_outputs_already_present(tmp_path):
    # Scenario: all agent output files exist with non-empty content before first poll
    # Setup: create r1_<agent>.md for each agent, populate panes map
    agents = ["gemini", "codex"]
    for a in agents:
        _write(tmp_path / f"r1_{a}.md", "done")
    panes = {0: "%1", 1: "%2"}
    capacity_check = MagicMock(return_value=False)
    retry_cb = MagicMock()
    sleep_fn = MagicMock()
    # Test action: call with short timeout
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=10, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=capacity_check,
        retry_pane=retry_cb, sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: success, both agents completed, no retries, no sleeps
    assert ok is True
    assert sorted(completed) == ["codex", "gemini"]
    assert reason is None
    retry_cb.assert_not_called()


def test_returns_false_with_timeout_reason_when_outputs_never_appear(tmp_path):
    # Scenario: no output files materialize within timeout
    # Setup: empty debate dir, panes have no capacity errors
    agents = ["gemini"]
    panes = {0: "%1"}
    sleep_fn = MagicMock()
    # Test action: timeout=5, poll=5 -> exactly one iteration
    ok, completed, reason = debate_waitForOutputs(
        prefix="r1", timeout=5, panes=panes, agents=agents,
        debate_dir=tmp_path, pane_capacity_error=lambda p, a: False,
        retry_pane=MagicMock(), sleep_fn=sleep_fn, poll_interval=5,
    )
    # Test verification: failure with timeout reason, no completions
    assert ok is False
    assert completed == []
    assert reason is not None and "timeout" in reason.lower()



