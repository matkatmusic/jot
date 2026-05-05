"""Tests for debate_main (workspace migration).

One behavior per test. All in-flight deps + subprocess + filesystem-affecting
externals are mocked. Plain ASCII only - no em-dash/en-dash/Unicode arrows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tmp_debate_main as mod  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ctx(tmp_path: Path, *, prompt: str, repo_root: str | None = None,
         transcript_path: str = "") -> dict:
    """Build a debate_initHookContext()-shaped dict."""
    return {
        "SCRIPTS_DIR": str(tmp_path / "scripts"),
        "LOG_FILE": str(tmp_path / "debate-log.txt"),
        "INPUT": json.dumps({"prompt": prompt, "cwd": str(tmp_path),
                             "transcript_path": transcript_path}),
        "CWD": str(tmp_path),
        "TRANSCRIPT_PATH": transcript_path,
        "REPO_ROOT": str(tmp_path) if repo_root is None else repo_root,
    }


def _detect(available: list[str]) -> dict:
    """Build a debate_detectAvailableAgents() result."""
    return {"available": available, "gemini_model": "gem-x", "codex_model": "cdx-y"}


# --------------------------------------------------------------------------- #
# 1. Non-/debate input bails fast with rc=0.
# --------------------------------------------------------------------------- #
def test_non_debate_input_returns_zero(tmp_path):
    # Scenario: hook fires for an unrelated prompt; debate_main must no-op.
    # Setup: context whose INPUT does not contain the literal '"/debate'.
    ctx = {
        "SCRIPTS_DIR": "", "LOG_FILE": "", "INPUT": '{"prompt":"hello"}',
        "CWD": str(tmp_path), "TRANSCRIPT_PATH": "", "REPO_ROOT": str(tmp_path),
    }
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "hookjson_emitBlock") as emit, \
         patch.object(mod, "debate_startOrResume") as start:
        # Test action: invoke debate_main.
        rc = mod.debate_main()
    # Test verification: rc 0, no emit, no dispatch.
    assert rc == 0
    emit.assert_not_called()
    start.assert_not_called()


# --------------------------------------------------------------------------- #
# 2. Missing topic emits usage block.
# --------------------------------------------------------------------------- #
def test_missing_topic_emits_usage(tmp_path):
    # Scenario: prompt is bare '/debate' with no topic argument.
    # Setup: build context and patch deps.
    ctx = _ctx(tmp_path, prompt="/debate")
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "hookjson_emitBlock") as emit, \
         patch.object(mod, "debate_startOrResume") as start:
        # Test action: run debate_main.
        rc = mod.debate_main()
    # Test verification: usage message emitted, no dispatch.
    assert rc == 0
    emit.assert_called_once_with("debate: no topic provided. Usage: /debate <topic>")
    start.assert_not_called()


# --------------------------------------------------------------------------- #
# 3. Missing repo emits 'requires a git repository' block.
# --------------------------------------------------------------------------- #
def test_missing_repo_emits_block(tmp_path):
    # Scenario: caller is not inside a git repo (REPO_ROOT empty).
    # Setup: context with REPO_ROOT="" but valid topic.
    ctx = _ctx(tmp_path, prompt="/debate should we ship", repo_root="")
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "hookjson_emitBlock") as emit, \
         patch.object(mod, "debate_startOrResume") as start:
        # Test action.
        rc = mod.debate_main()
    # Test verification.
    assert rc == 0
    emit.assert_called_once_with("debate requires a git repository.")
    start.assert_not_called()


# --------------------------------------------------------------------------- #
# 4. Existing dir with synthesis.md emits 'already complete'.
# --------------------------------------------------------------------------- #
def test_existing_with_synthesis_emits_already_complete(tmp_path):
    # Scenario: a prior debate dir for this topic already has synthesis.md.
    # Setup: create a debate dir with synthesis.md and stub findMatching.
    existing = tmp_path / "Debates" / "2026-05-05T00-00-00_topic"
    existing.mkdir(parents=True)
    (existing / "synthesis.md").write_text("done\n")
    ctx = _ctx(tmp_path, prompt="/debate topic")
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "debate_detectAvailableAgents",
                      return_value=_detect(["claude", "gemini"])), \
         patch.object(mod, "debate_findMatching", return_value=str(existing)), \
         patch.object(mod, "hookjson_emitBlock") as emit, \
         patch.object(mod, "debate_startOrResume") as start:
        # Test action.
        rc = mod.debate_main()
    # Test verification: emit message contains 'already complete' and ASCII separators.
    assert rc == 0
    msg = emit.call_args.args[0]
    assert "already complete" in msg
    assert "synthesis.md" in msg
    assert "—" not in msg  # no em-dash
    start.assert_not_called()


# --------------------------------------------------------------------------- #
# 5. Existing dir with live lock emits 'already running'.
# --------------------------------------------------------------------------- #
def test_existing_with_live_lock_emits_already_running(tmp_path):
    # Scenario: existing debate dir is mid-flight; tmux session still live.
    # Setup: dir exists, no synthesis.md, anyLiveLock True, liveSession 'debate-3'.
    existing = tmp_path / "Debates" / "2026-05-05T00-00-00_topic"
    existing.mkdir(parents=True)
    ctx = _ctx(tmp_path, prompt="/debate topic")
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "debate_detectAvailableAgents",
                      return_value=_detect(["claude", "gemini"])), \
         patch.object(mod, "debate_findMatching", return_value=str(existing)), \
         patch.object(mod, "debate_anyLiveLock", return_value=True), \
         patch.object(mod, "debate_liveSession", return_value="debate-3"), \
         patch.object(mod, "hookjson_emitBlock") as emit, \
         patch.object(mod, "debate_startOrResume") as start:
        # Test action.
        rc = mod.debate_main()
    # Test verification: ASCII '->' arrow and live name present; no Unicode arrow.
    assert rc == 0
    msg = emit.call_args.args[0]
    assert "already running" in msg
    assert "-> tmux attach -t debate-3" in msg
    assert "→" not in msg  # no Unicode right arrow
    start.assert_not_called()


# --------------------------------------------------------------------------- #
# 6. Existing dir without synthesis or live lock -> resuming=True dispatch.
# --------------------------------------------------------------------------- #
def test_existing_without_synthesis_or_lock_resumes(tmp_path):
    # Scenario: stale debate dir survives; resume path must engage.
    # Setup: existing dir with no synthesis.md, anyLiveLock False, FAILED.txt present.
    existing = tmp_path / "Debates" / "2026-05-05T00-00-00_topic"
    existing.mkdir(parents=True)
    (existing / "FAILED.txt").write_text("rip\n")
    ctx = _ctx(tmp_path, prompt="/debate topic")
    feas = MagicMock()
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "debate_detectAvailableAgents",
                      return_value=_detect(["claude", "gemini"])), \
         patch.object(mod, "debate_findMatching", return_value=str(existing)), \
         patch.object(mod, "debate_anyLiveLock", return_value=False), \
         patch.object(mod, "debate_checkResumeFeasibility",
                      return_value=feas) as check, \
         patch.object(mod, "debate_startOrResume") as start, \
         patch.object(mod, "hookjson_emitBlock"):
        # Test action.
        rc = mod.debate_main()
    # Test verification: resume feasibility called, FAILED.txt removed,
    # startOrResume called with resuming=True.
    assert rc == 0
    check.assert_called_once()
    assert not (existing / "FAILED.txt").exists()
    assert start.call_args.kwargs["resuming"] is True
    assert Path(start.call_args.kwargs["debate_dir"]) == existing


# --------------------------------------------------------------------------- #
# 7. Fresh debate with <2 agents emits agent-count message.
# --------------------------------------------------------------------------- #
def test_fresh_under_two_agents_emits_count_block(tmp_path):
    # Scenario: only one agent passed smoke tests; fresh debate must abort.
    # Setup: findMatching None, available=['claude'].
    ctx = _ctx(tmp_path, prompt="/debate ship it")
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "debate_detectAvailableAgents",
                      return_value=_detect(["claude"])), \
         patch.object(mod, "debate_findMatching", return_value=None), \
         patch.object(mod, "hookjson_emitBlock") as emit, \
         patch.object(mod, "debate_startOrResume") as start:
        # Test action.
        rc = mod.debate_main()
    # Test verification: ASCII '>=', no Unicode geq, no dispatch.
    assert rc == 0
    msg = emit.call_args.args[0]
    assert ">=2 agents" in msg
    assert "claude" in msg
    assert "≥" not in msg  # no Unicode '>='
    start.assert_not_called()


# --------------------------------------------------------------------------- #
# 8. Fresh happy path writes topic.md/context.md and dispatches startOrResume.
# --------------------------------------------------------------------------- #
def test_fresh_happy_path_creates_artifacts_and_dispatches(tmp_path):
    # Scenario: clean repo, two agents, no transcript - 'no conversation context' branch.
    # Setup: findMatching None, available=2, transcript_path empty.
    ctx = _ctx(tmp_path, prompt="/debate Should we Adopt Rust?")
    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "debate_detectAvailableAgents",
                      return_value=_detect(["claude", "gemini"])), \
         patch.object(mod, "debate_findMatching", return_value=None), \
         patch.object(mod, "debate_startOrResume") as start, \
         patch.object(mod, "hookjson_emitBlock"):
        # Test action.
        rc = mod.debate_main()
    # Test verification: dir created with slugged name, topic.md + context.md present,
    # startOrResume called with resuming=False.
    assert rc == 0
    debates_root = tmp_path / "Debates"
    assert debates_root.is_dir()
    created = list(debates_root.iterdir())
    assert len(created) == 1
    debate_dir = created[0]
    # Slug derived from 'should-we-adopt-rust' (first 40 chars, trailing - stripped).
    assert debate_dir.name.endswith("_should-we-adopt-rust")
    assert (debate_dir / "topic.md").read_text() == "Should we Adopt Rust?\n"
    assert (debate_dir / "context.md").read_text() == "(no conversation context available)\n"
    assert start.call_args.kwargs["resuming"] is False
    assert Path(start.call_args.kwargs["debate_dir"]) == debate_dir


# --------------------------------------------------------------------------- #
# 9. Fresh path with transcript runs capture-conversation script via subprocess.
# --------------------------------------------------------------------------- #
def test_fresh_with_transcript_invokes_capture_subprocess(tmp_path, monkeypatch):
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
    ctx = _ctx(tmp_path, prompt="/debate topic", transcript_path=str(transcript))

    def fake_run(cmd, stdout, stderr, check):
        # Test setup: simulate capture writing useful output to context.md handle.
        stdout.write("captured context\n")
        return MagicMock(returncode=0)

    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "debate_detectAvailableAgents",
                      return_value=_detect(["claude", "gemini"])), \
         patch.object(mod, "debate_findMatching", return_value=None), \
         patch.object(mod.subprocess, "run", side_effect=fake_run) as run_mock, \
         patch.object(mod, "debate_startOrResume"), \
         patch.object(mod, "hookjson_emitBlock"):
        # Test action.
        rc = mod.debate_main()
    # Test verification: subprocess.run called once; context.md has captured payload.
    assert rc == 0
    assert run_mock.call_count == 1
    debate_dir = next((tmp_path / "Debates").iterdir())
    assert (debate_dir / "context.md").read_text() == "captured context\n"
    assert (debate_dir / "invoking_transcript.txt").read_text() == f"{transcript}\n"


# --------------------------------------------------------------------------- #
# 10. Fresh path with transcript but failed capture writes failure marker.
# --------------------------------------------------------------------------- #
def test_fresh_capture_failure_writes_failure_marker(tmp_path, monkeypatch):
    # Scenario: capture-conversation.py returns non-zero -> fallback marker.
    # Setup: transcript + script exist; subprocess returns rc=1.
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("x")
    plugin_root = tmp_path / "plugin"
    cap_dir = plugin_root / "skills" / "jot" / "scripts"
    cap_dir.mkdir(parents=True)
    (cap_dir / "capture-conversation.py").write_text("# stub\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    ctx = _ctx(tmp_path, prompt="/debate topic", transcript_path=str(transcript))

    def fake_run(cmd, stdout, stderr, check):
        return MagicMock(returncode=1)

    with patch.object(mod, "debate_initHookContext", return_value=ctx), \
         patch.object(mod, "hookjson_checkRequirements"), \
         patch.object(mod, "debate_detectAvailableAgents",
                      return_value=_detect(["claude", "gemini"])), \
         patch.object(mod, "debate_findMatching", return_value=None), \
         patch.object(mod.subprocess, "run", side_effect=fake_run), \
         patch.object(mod, "debate_startOrResume"), \
         patch.object(mod, "hookjson_emitBlock"):
        # Test action.
        rc = mod.debate_main()
    # Test verification: context.md contains the failure marker text.
    assert rc == 0
    debate_dir = next((tmp_path / "Debates").iterdir())
    assert (debate_dir / "context.md").read_text() == "(conversation capture failed)\n"
