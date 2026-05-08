"""Tests for debate_lib -- retry bucket (debateRetry, checkResumeFeasibility, findMatching, debateAbort)."""
from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import MagicMock

from common.scripts.debate_lib import (
    ResumeFeasibility,
    debate_checkResumeFeasibility,
    debate_findMatching,
)
from common.scripts import debate_lib as _mod_dr
from common.scripts import debate_lib as sut


# =====================================================================
# debate_retryMain tests
# =====================================================================


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
    rc = _mod_dr.debate_retryMain()

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
    rc = _mod_dr.debate_retryMain()

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
    rc = _mod_dr.debate_retryMain()

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
    rc = _mod_dr.debate_retryMain()

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
    rc = _mod_dr.debate_retryMain()

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
    rc = _mod_dr.debate_retryMain()

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
# debate_checkResumeFeasibility tests
# =====================================================================


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
    # Scenario: r1+r2 exist but r2 is zero bytes -- bash uses `-s` (non-empty).
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
    # Test verification: trivially feasible -- no originals to validate against.
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
    # Scenario: contract -- return type is the documented dataclass.
    # Setup: minimal valid debate dir.
    _seed_original(tmp_path, ["claude"])
    # Test action: run the check.
    result = debate_checkResumeFeasibility(tmp_path, ["claude"])
    # Test verification: instance shape is ResumeFeasibility.
    assert isinstance(result, ResumeFeasibility)
    assert isinstance(result.updated_agents, list)
    assert isinstance(result.unusable_agents, list)


# =====================================================================
# debate_findMatching tests
# =====================================================================


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


# =====================================================================
# debate_abortMain tests [retry -- debate-abort path]
# =====================================================================


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


def test_emits_when_transcript_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: hook payload has no transcript_path; we must short-circuit.
    # Setup: ctx with empty transcript, valid repo (irrelevant here).
    _install_ctx(monkeypatch, transcript="", repo=str(tmp_path))
    msgs = _capture_emit(monkeypatch)

    # Test action: invoke entry point.
    rc = sut.debate_abortMain()

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
    rc = sut.debate_abortMain()

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
    rc = sut.debate_abortMain()

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
    rc = sut.debate_abortMain()

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
    rc = sut.debate_abortMain()

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
    rc = sut.debate_abortMain()

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
    rc = sut.debate_abortMain()

    # Test verification: only the lex-greatest matching dir was deleted; the
    # older matching dir AND the unrelated dir survive.
    assert rc == 0
    assert not newer.exists()
    assert older.is_dir()
    assert (tmp_path / "Debates" / "2026-05-05T230000_z").is_dir()
    assert msgs == [f"/debate-abort: deleted {newer}"]
