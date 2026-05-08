from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import io as _io_dispatch
import sys

import jot_plugin_orchestrator
from jot_plugin_orchestrator import dispatch_main
from common.scripts import plate_dispatcher as _plate_mod
from common.scripts.plate_dispatcher import plate_main

_dm = jot_plugin_orchestrator


def _stub_argv(monkeypatch, name, recorder, key):
    # Replace _dm.<name> with a stub and rewire _ARGV_DISPATCH.
    def _fn(*args, **kwargs):
        recorder.append((key, args, kwargs))
        return 0
    monkeypatch.setattr(_dm, name, _fn)
    if key in _dm._ARGV_DISPATCH:
        monkeypatch.setitem(_dm._ARGV_DISPATCH, key, _fn)


def _stub_prompt_disp(monkeypatch, name, recorder, key):
    # Stub a stdin-mode entrypoint and rebuild the prompt dispatch tuple.
    def _fn(*args, **kwargs):
        recorder.append((key, sys.stdin.read()))
        return 0
    monkeypatch.setattr(_dm, name, _fn)
    rebuilt = []
    for prefix, original_fn in _dm._PROMPT_DISPATCH:
        if prefix == key:
            rebuilt.append((prefix, lambda f=_fn: f()))
        else:
            rebuilt.append((prefix, original_fn))
    monkeypatch.setattr(_dm, "_PROMPT_DISPATCH", tuple(rebuilt))


# =====================================================================
# plate_main tests (migrated from _failing/test_plate_main.py)
# Failing tests in the workspace location used hardcoded /fake/plugin_data
# which mkdir cannot create on macOS. Fix: derive paths from tmp_path.
# =====================================================================

import re as _re_pm  # local alias for plate-main test re-patch  # noqa: E402


def _base_env_pm(tmp_path) -> dict:
    # Returns valid env dict whose plugin_data path is writable.
    return {
        "CLAUDE_PLUGIN_ROOT": str(tmp_path / "plugin_root"),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin_data"),
    }


def _make_payload_pm(**overrides) -> str:
    base = {
        "prompt": "/plate",
        "session_id": "sess-abc",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/fake/repo",
    }
    base.update(overrides)
    return json.dumps(base)


def _make_deps_pm(*, repo_root: str | None = None, tmp_path: Path | None = None,
                  emit_return: str = "EMITTED") -> dict:
    # repo_root defaults to a writable tmp_path-derived directory.
    if repo_root is None:
        if tmp_path is None:
            raise AssertionError("_make_deps_pm requires repo_root or tmp_path")
        repo_root_path = tmp_path / "repo"
        repo_root_path.mkdir(parents=True, exist_ok=True)
        repo_root = str(repo_root_path)
    elif repo_root:
        Path(repo_root).mkdir(parents=True, exist_ok=True)
    emit = MagicMock(return_value=emit_return)
    check = MagicMock(return_value=None)
    get_root = MagicMock(return_value=repo_root)
    ensure_gi = MagicMock(return_value=None)
    run = MagicMock(return_value=MagicMock(stdout="ok output", stderr="", returncode=0))
    return {
        "_hookjson_emitBlock": emit,
        "_hookjson_checkRequirements": check,
        "_getGitRepoRoot": get_root,
        "_ensureGitignoreEntry": ensure_gi,
        "_subprocess_run": run,
    }


def _expected_repo_root_pm(tmp_path: Path) -> str:
    # The default repo_root that _make_deps_pm(tmp_path=...) returns.
    return str(tmp_path / "repo")


# Env validation
def test_plateMain_missing_plugin_root_raises(tmp_path):
    # Scenario: CLAUDE_PLUGIN_ROOT is absent.
    # Setup: env with only PLUGIN_DATA.
    env = {"CLAUDE_PLUGIN_DATA": str(tmp_path / "data")}
    # Test action / verification:
    with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_ROOT missing"):
        plate_main(_stdin=_make_payload_pm(), _environ=env, **_make_deps_pm(tmp_path=tmp_path))


def test_plateMain_missing_plugin_data_raises(tmp_path):
    # Scenario: CLAUDE_PLUGIN_DATA is absent.
    # Setup: env with only PLUGIN_ROOT.
    env = {"CLAUDE_PLUGIN_ROOT": str(tmp_path / "root")}
    # Test action / verification:
    with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_DATA missing"):
        plate_main(_stdin=_make_payload_pm(), _environ=env, **_make_deps_pm(tmp_path=tmp_path))


# Fast-path bail-out
def test_plateMain_non_plate_input_exits_0_silently(tmp_path):
    # Scenario: raw input has no "/plate substring.
    # Setup: arbitrary unrelated payload.
    raw = json.dumps({"prompt": "/jot something", "session_id": "s1", "cwd": "/r"})
    deps = _make_deps_pm(tmp_path=tmp_path)
    # Test action:
    rc = plate_main(_stdin=raw, _environ=_base_env_pm(tmp_path), **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_not_called()


def test_plateMain_bad_json_after_fast_path_exits_0(tmp_path):
    # Scenario: input contains "/plate but is not valid JSON.
    # Setup: raw string starts with "/plate but is malformed.
    raw = '"/plate this is not json'
    deps = _make_deps_pm(tmp_path=tmp_path)
    # Test action:
    rc = plate_main(_stdin=raw, _environ=_base_env_pm(tmp_path), **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_not_called()


# Prompt regex filtering
def test_plateMain_typo_prompt_exits_0_silently(tmp_path):
    # Scenario: prompt looks like /plate but has a typo variant.
    # Setup: regex must reject /plate --bogus-flag.
    raw = _make_payload_pm(prompt="/plate --bogus-flag")
    deps = _make_deps_pm(tmp_path=tmp_path)
    # Test action:
    rc = plate_main(_stdin=raw, _environ=_base_env_pm(tmp_path), **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_not_called()


def test_plateMain_prompt_with_leading_whitespace_is_accepted(tmp_path):
    # Scenario: prompt has leading whitespace (lstrip applied).
    # Setup: payload with leading spaces.
    raw = _make_payload_pm(prompt="  /plate --done")
    deps = _make_deps_pm(tmp_path=tmp_path)
    # Test action:
    rc = plate_main(_stdin=raw, _environ=_base_env_pm(tmp_path), **deps)
    # Test verification:
    assert rc == 0
    cmd = deps["_subprocess_run"].call_args[0][0]
    assert cmd[2] == "done"


# Repo-root detection
def test_plateMain_missing_repo_root_emits_friendly_message(tmp_path):
    # Scenario: git_getRepoRoot returns empty string.
    # Setup: deps with repo_root="".
    raw = _make_payload_pm()
    deps = _make_deps_pm(repo_root="")
    # Test action:
    rc = plate_main(_stdin=raw, _environ=_base_env_pm(tmp_path), **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_called_once()
    msg = deps["_hookjson_emitBlock"].call_args[0][0]
    assert "git repository" in msg
    assert "git init" in msg


# Variant -> cli.py argv dispatch
def _get_cli_args_pm(deps, stdin_payload, env):
    plate_main(_stdin=stdin_payload, _environ=env, **deps)
    call_args = deps["_subprocess_run"].call_args[0][0]
    return call_args[2:]


def test_plateMain_dispatch_bare_plate_is_push(tmp_path):
    # Scenario: /plate -> push with session_id, transcript, repo_root.
    # Setup:
    deps = _make_deps_pm(tmp_path=tmp_path)
    raw = _make_payload_pm(prompt="/plate", session_id="SID", transcript_path="/t.jsonl")
    # Test action:
    args = _get_cli_args_pm(deps, raw, _base_env_pm(tmp_path))
    # Test verification:
    assert args[0] == "push"
    assert args[1] == "SID"
    assert args[2] == "/t.jsonl"
    assert args[3] == _expected_repo_root_pm(tmp_path)


def test_plateMain_dispatch_done(tmp_path):
    # Scenario: /plate --done -> done <repo_root>.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --done"), _base_env_pm(tmp_path))
    assert args == ["done", _expected_repo_root_pm(tmp_path)]


def test_plateMain_dispatch_drop(tmp_path):
    # Scenario: /plate --drop -> drop <repo_root>.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --drop"), _base_env_pm(tmp_path))
    assert args == ["drop", _expected_repo_root_pm(tmp_path)]


def test_plateMain_dispatch_trash(tmp_path):
    # Scenario: /plate --trash -> trash <repo_root>.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --trash"), _base_env_pm(tmp_path))
    assert args == ["trash", _expected_repo_root_pm(tmp_path)]


def test_plateMain_dispatch_recycle(tmp_path):
    # Scenario: /plate --recycle -> recycle <repo_root>.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --recycle"), _base_env_pm(tmp_path))
    assert args == ["recycle", _expected_repo_root_pm(tmp_path)]


def test_plateMain_dispatch_recycle_list(tmp_path):
    # Scenario: /plate --recycle --list -> recycle <repo_root> --list.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --recycle --list"), _base_env_pm(tmp_path))
    assert args == ["recycle", _expected_repo_root_pm(tmp_path), "--list"]


def test_plateMain_dispatch_recycle_named(tmp_path):
    # Scenario: /plate --recycle feat/my-branch -> recycle <repo_root> feat/my-branch.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --recycle feat/my-branch"), _base_env_pm(tmp_path))
    assert args == ["recycle", _expected_repo_root_pm(tmp_path), "feat/my-branch"]


def test_plateMain_dispatch_show(tmp_path):
    # Scenario: /plate --show -> show <repo_root>.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --show"), _base_env_pm(tmp_path))
    assert args == ["show", _expected_repo_root_pm(tmp_path)]


def test_plateMain_dispatch_next(tmp_path):
    # Scenario: /plate --next -> next <repo_root>.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --next"), _base_env_pm(tmp_path))
    assert args == ["next", _expected_repo_root_pm(tmp_path)]


def test_plateMain_dispatch_next_named(tmp_path):
    # Scenario: /plate --next feat.123 -> next <repo_root> feat.123.
    deps = _make_deps_pm(tmp_path=tmp_path)
    args = _get_cli_args_pm(deps, _make_payload_pm(prompt="/plate --next feat.123"), _base_env_pm(tmp_path))
    assert args == ["next", _expected_repo_root_pm(tmp_path), "feat.123"]


# Unrecognized variant
def test_plateMain_unrecognized_variant_emits_message(tmp_path):
    # Scenario: prompt passes regex but falls through all dispatch branches.
    # Setup: temporarily relax the module-level regex to admit /plate --unknown.
    original_re = _plate_mod._PROMPT_RE_PLATE
    try:
        _plate_mod._PROMPT_RE_PLATE = _re_pm.compile(r"^/plate( --unknown)?$")
        deps = _make_deps_pm(tmp_path=tmp_path)
        # Test action:
        rc = plate_main(
            _stdin=_make_payload_pm(prompt="/plate --unknown"),
            _environ=_base_env_pm(tmp_path),
            **deps,
        )
        # Test verification:
        assert rc == 0
        call_msg = deps["_hookjson_emitBlock"].call_args[0][0]
        assert "unrecognized variant" in call_msg
        assert "/plate --unknown" in call_msg
    finally:
        _plate_mod._PROMPT_RE_PLATE = original_re


# cli.py output forwarded
def test_plateMain_cli_output_forwarded_via_emit_block(tmp_path):
    # Scenario: cli.py produces stdout; it should be passed to emit_block.
    # Setup: subprocess returns stdout="branch pushed".
    deps = _make_deps_pm(tmp_path=tmp_path)
    deps["_subprocess_run"].return_value = MagicMock(
        stdout="branch pushed\n", stderr="", returncode=0
    )
    # Test action:
    rc = plate_main(_stdin=_make_payload_pm(), _environ=_base_env_pm(tmp_path), **deps)
    # Test verification:
    assert rc == 0
    emitted = deps["_hookjson_emitBlock"].call_args[0][0]
    assert "branch pushed" in emitted


def test_plateMain_cli_stderr_included_in_emit_block(tmp_path):
    # Scenario: cli.py writes to stderr; stderr should also be captured.
    # Setup: subprocess returns stderr text only.
    deps = _make_deps_pm(tmp_path=tmp_path)
    deps["_subprocess_run"].return_value = MagicMock(
        stdout="", stderr="warning: detached HEAD\n", returncode=1
    )
    # Test action:
    rc = plate_main(_stdin=_make_payload_pm(), _environ=_base_env_pm(tmp_path), **deps)
    # Test verification:
    assert rc == 0
    emitted = deps["_hookjson_emitBlock"].call_args[0][0]
    assert "warning: detached HEAD" in emitted


# Log-file promotion
def test_plateMain_log_file_promoted_to_per_repo_path_when_no_override(tmp_path):
    # Scenario: PLATE_LOG_FILE not set -> log path moved under REPO_ROOT/.plate/.
    # Setup: env without PLATE_LOG_FILE; repo_root resolves under tmp_path.
    env = {**_base_env_pm(tmp_path), "CLAUDE_PLUGIN_DATA": str(tmp_path)}
    repo_root = str(tmp_path / "myrepo")
    (tmp_path / "myrepo").mkdir()
    deps = _make_deps_pm(repo_root=repo_root)
    # Test action:
    plate_main(_stdin=_make_payload_pm(), _environ=env, **deps)
    # Test verification:
    deps["_ensureGitignoreEntry"].assert_called_once_with(
        repo_root, ".plate/plate-log.txt"
    )


def test_plateMain_log_file_override_respected(tmp_path):
    # Scenario: PLATE_LOG_FILE set explicitly -> gitignore ensure not called.
    # Setup: env with explicit override.
    override_log = str(tmp_path / "custom.log")
    env = {**_base_env_pm(tmp_path), "PLATE_LOG_FILE": override_log}
    deps = _make_deps_pm(tmp_path=tmp_path)
    # Test action:
    plate_main(_stdin=_make_payload_pm(), _environ=env, **deps)
    # Test verification:
    deps["_ensureGitignoreEntry"].assert_not_called()


def test_dispatchMain_newline_after_slashcommand_tolerated(monkeypatch):
    # Scenario: prompt is "/plate\n..." -> matches.
    # Setup: stub plate_main; literal newline after /plate.
    calls: list = []
    _stub_prompt_disp(monkeypatch, "plate_main", calls, "/plate")
    payload = json.dumps({"prompt": "/plate\nbody line"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1
