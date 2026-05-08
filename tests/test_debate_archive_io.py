"""Tests for debate_lib -- archive_io bucket (debate_archive, debate_initHookContext, debate_cleanup, debate_writeFailed, debate_waitForOutputs path/io, launchAgent failure I/O)."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

from unittest.mock import MagicMock, patch

from common.scripts.debate_lib import (
    debate_archive,
    debate_cleanup,
    debate_initHookContext,
    debate_launchAgent,
    debate_waitForOutputs,
    debate_writeFailed,
)
from common.scripts.git_lib import git_makeRepo as _make_repo


# =====================================================================
# debate_archive tests
# =====================================================================


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


# =====================================================================
# debate_initHookContext tests [archive_io -- paths]
# =====================================================================


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


# =====================================================================
# debate_launchAgent failure-side I/O tests [archive_io]
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


# =====================================================================
# debate_waitForOutputs partial completion / empty file [archive_io]
# =====================================================================


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


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


# =====================================================================
# debate_cleanup tests
# =====================================================================


def test_removes_tmp_debate_dir(tmp_path: Path) -> None:
    # Scenario: settings_file lives inside a /tmp/debate.* directory.
    # Setup: create a mock /tmp/debate.XYZ tree under tmp_path (so we don't
    #   touch real /tmp). We monkey-patch by creating the structure locally
    #   and passing the fake path; the guard checks parent.name == "debate.*"
    #   and parent.parent == Path("/tmp"). We build the fake tree and
    #   temporarily repoint by using a symlink trick -- actually, the function
    #   checks Path("/tmp") literally, so we directly fabricate a path string
    #   with a real /tmp/debate.* dir to exercise it.
    import tempfile, shutil

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


def test_noop_when_dir_already_gone() -> None:
    # Scenario: cleanup called twice; second call should not raise.
    # Setup: fabricate a path that looks like /tmp/debate.XYZ but doesn't exist
    nonexistent = Path("/tmp/debate.already_deleted_abc123/settings.json")
    assert not nonexistent.parent.exists(), "Precondition: dir must not exist"

    # Test action + Test verification: must not raise
    debate_cleanup(nonexistent)


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


# =====================================================================
# debate_writeFailed tests
# =====================================================================


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


# =====================================================================
# debate_waitForOutputs success / timeout (no capacity-error retry path) [archive_io]
# =====================================================================


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
