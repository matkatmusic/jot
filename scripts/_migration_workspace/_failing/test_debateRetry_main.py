"""Tests for debateRetry_main (workspace pair).

One behavior per test, per RED_GREEN_TDD.md conventions. All in-flight deps
plus sys.stdin replaced via monkeypatch; tmp_path used for filesystem.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the workspace dir importable (sibling files use `_tmp_*` names).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tmp_debateRetry_main as mod


# ---------------------------------------------------------------------------
# Shared monkeypatch helper: stub all collaborators on the module under test.
# ---------------------------------------------------------------------------
def _install_stubs(
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
    """Replace every external collaborator with a record-collecting stub.

    Returns a dict whose entries the test asserts against.
    """
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

    monkeypatch.setattr(mod, "debate_initHookContext", fake_init)
    monkeypatch.setattr(mod, "hookjson_checkRequirements", fake_check_requirements)
    monkeypatch.setattr(mod, "hookjson_emitBlock", fake_emit)
    monkeypatch.setattr(mod, "debate_detectAvailableAgents", fake_detect)
    monkeypatch.setattr(mod, "debate_anyLiveLock", fake_any_live_lock)
    monkeypatch.setattr(mod, "debate_liveSession", fake_live_session)
    monkeypatch.setattr(mod, "debate_checkResumeFeasibility", fake_check_resume)
    monkeypatch.setattr(mod, "debate_startOrResume", fake_start_or_resume)

    # Ensure stdin is never read by accident.
    monkeypatch.setattr(sys, "stdin", None)
    return calls


def test_missing_transcript_emits_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Scenario: hook context has empty TRANSCRIPT_PATH; should emit and return 0.
    # Setup: install stubs with empty transcript and a valid repo.
    calls = _install_stubs(monkeypatch, transcript_path="", repo_root=str(tmp_path))

    # Test action: invoke entrypoint.
    rc = mod.debateRetry_main()

    # Test verification: rc==0; exactly one emit with the no-transcript message;
    # no orchestration side-effects fired.
    assert rc == 0
    assert calls["emits"] == ["/debate-retry: no transcript_path in hook payload"]
    assert calls["start_or_resume"] == []
    assert calls["check_resume"] == []


def test_missing_repo_emits_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scenario: transcript present but REPO_ROOT empty; should emit + return 0.
    # Setup: install stubs with a transcript but empty repo_root.
    calls = _install_stubs(monkeypatch, transcript_path="/some/t.txt", repo_root="")

    # Test action: invoke entrypoint.
    rc = mod.debateRetry_main()

    # Test verification: rc==0; emit explains missing git repo; no orchestration.
    assert rc == 0
    assert calls["emits"] == ["/debate-retry requires a git repository"]
    assert calls["start_or_resume"] == []


def test_no_matching_debate_emits_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Scenario: Debates dir exists but no invoking_transcript.txt matches.
    # Setup: build a Debates dir with a non-matching transcript marker.
    debates = tmp_path / "Debates" / "2026-01-01T00-00-00_topic"
    debates.mkdir(parents=True)
    (debates / "invoking_transcript.txt").write_text("/other/transcript.txt\n")
    calls = _install_stubs(
        monkeypatch,
        transcript_path="/this/transcript.txt",
        repo_root=str(tmp_path),
    )

    # Test action: invoke entrypoint.
    rc = mod.debateRetry_main()

    # Test verification: rc==0; not-found message emitted; no orchestration.
    assert rc == 0
    assert calls["emits"] == ["/debate-retry: no debate found in this conversation"]
    assert calls["start_or_resume"] == []


def test_matched_debate_with_synthesis_emits_already_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: matched debate dir already has synthesis.md => terminal complete.
    # Setup: matching transcript + synthesis.md present.
    transcript = "/conv/abc.jsonl"
    debate_dir = tmp_path / "Debates" / "2026-02-02T10-10-10_topic"
    debate_dir.mkdir(parents=True)
    (debate_dir / "invoking_transcript.txt").write_text(transcript + "\n")
    (debate_dir / "synthesis.md").write_text("done\n")
    calls = _install_stubs(
        monkeypatch, transcript_path=transcript, repo_root=str(tmp_path)
    )

    # Test action: invoke entrypoint.
    rc = mod.debateRetry_main()

    # Test verification: rc==0; emit cites synthesis.md; no orchestration.
    assert rc == 0
    assert len(calls["emits"]) == 1
    assert "already complete" in calls["emits"][0]
    assert "synthesis.md" in calls["emits"][0]
    assert calls["start_or_resume"] == []


def test_matched_debate_with_live_lock_emits_still_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: matched debate has no synthesis but a live lock => still running.
    # Setup: matching transcript; no synthesis; any_live_lock returns True.
    transcript = "/conv/live.jsonl"
    debate_dir = tmp_path / "Debates" / "2026-03-03T11-11-11_run"
    debate_dir.mkdir(parents=True)
    (debate_dir / "invoking_transcript.txt").write_text(transcript)
    calls = _install_stubs(
        monkeypatch,
        transcript_path=transcript,
        repo_root=str(tmp_path),
        any_live=True,
        live_session="debate-7",
    )

    # Test action: invoke entrypoint.
    rc = mod.debateRetry_main()

    # Test verification: rc==0; emit names the live session via tmux attach;
    # uses ASCII '->' and not Unicode arrow; no orchestration fired.
    assert rc == 0
    assert len(calls["emits"]) == 1
    assert calls["emits"][0] == "/debate-retry: still running -> tmux attach -t debate-7"
    assert "→" not in calls["emits"][0]
    assert calls["start_or_resume"] == []


def test_happy_path_lex_max_wins_and_invokes_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: multiple matching debate dirs exist + a stale FAILED.txt;
    # the lexicographically-largest basename must win, FAILED.txt must be
    # removed, check_resume_feasibility called, startOrResume invoked.
    # Setup: two matching dirs + one non-matching; stale FAILED.txt in winner.
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

    calls = _install_stubs(
        monkeypatch,
        transcript_path=transcript,
        repo_root=str(tmp_path),
        available=["claude", "gemini", "codex"],
    )

    # Test action: invoke entrypoint.
    rc = mod.debateRetry_main()

    # Test verification: rc==0; no emit_block (happy path); FAILED.txt gone;
    # check_resume_feasibility received the newer dir + agents list;
    # startOrResume received resuming=True with debate_dir == newer.
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
    # Requirements check fired exactly once with debate-retry label.
    assert len(calls["requirements"]) == 1
    assert calls["requirements"][0][0] == "debate-retry"
