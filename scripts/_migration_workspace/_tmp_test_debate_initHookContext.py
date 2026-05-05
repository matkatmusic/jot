"""RED tests for debate_initHookContext.

Author RED tests from intent + docstring of bash `init_hook_context()`
(MIGRATE tag, jot-plugin-orchestrator.sh ~L2274-L2294). No paired bash _tests
existed; coverage is RELAXED_COVERAGE.

Bash contract:
- Requires CLAUDE_PLUGIN_ROOT and CLAUDE_PLUGIN_DATA env (errors if unset).
- Reads hook JSON from stdin (or pre-set INPUT) and sets:
    SCRIPTS_DIR     = $CLAUDE_PLUGIN_ROOT/skills/debate/scripts
    LOG_FILE        = $DEBATE_LOG_FILE or $CLAUDE_PLUGIN_DATA/debate-log.txt
    INPUT           = stdin contents (raw)
    CWD             = .cwd from JSON, fallback $PWD
    TRANSCRIPT_PATH = .transcript_path from JSON (empty if absent)
    REPO_ROOT       = git -C "$CWD" rev-parse --show-toplevel, "" on failure
- Ensures dirname of LOG_FILE exists (mkdir -p).

Python port returns a dict with these keys (no globals).
"""
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Standard temp file headers: insert workspace dir on sys.path so we can import.
sys.path.insert(0, str(Path(__file__).parent))
from _tmp_debate_initHookContext import debate_initHookContext


# ---------- helpers ----------

def _make_repo(tmp_path: Path) -> Path:
    """Initialise a git repo at tmp_path and return its absolute path."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path.resolve()


# ---------- tests ----------

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
