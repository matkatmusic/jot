"""Tests for plate_main workspace migration.

Each test covers one behavior. Comments follow RED_GREEN_TDD.md conventions:
  # Scenario:
  # Setup:
  # Test action:
  # Test verification:
"""
from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from _tmp_plate_main import plate_main


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

BASE_ENV = {
    "CLAUDE_PLUGIN_ROOT": "/fake/plugin_root",
    "CLAUDE_PLUGIN_DATA": "/fake/plugin_data",
}


def _make_payload(**overrides: Any) -> str:
    """Return a JSON string representing a minimal valid hook payload."""
    base: dict[str, Any] = {
        "prompt": "/plate",
        "session_id": "sess-abc",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/fake/repo",
    }
    base.update(overrides)
    return json.dumps(base)


def _make_deps(
    *,
    repo_root: str = "/fake/repo",
    emit_return: str = "EMITTED",
) -> dict[str, Any]:
    """Return a dict of injectable mocks suitable for plate_main(**deps)."""
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


# ---------------------------------------------------------------------------
# Env validation
# ---------------------------------------------------------------------------


def test_missing_plugin_root_raises(tmp_path):
    # Scenario: CLAUDE_PLUGIN_ROOT is absent
    # Setup:
    env = {"CLAUDE_PLUGIN_DATA": "/fake/data"}
    # Test action:
    with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_ROOT missing"):
        plate_main(_stdin=_make_payload(), _environ=env, **_make_deps())


def test_missing_plugin_data_raises(tmp_path):
    # Scenario: CLAUDE_PLUGIN_DATA is absent
    # Setup:
    env = {"CLAUDE_PLUGIN_ROOT": "/fake/root"}
    # Test action:
    with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_DATA missing"):
        plate_main(_stdin=_make_payload(), _environ=env, **_make_deps())


# ---------------------------------------------------------------------------
# Fast-path bail-out
# ---------------------------------------------------------------------------


def test_non_plate_input_exits_0_silently():
    # Scenario: raw input has no "/plate substring
    # Setup:
    raw = json.dumps({"prompt": "/jot something", "session_id": "s1", "cwd": "/r"})
    deps = _make_deps()
    # Test action:
    rc = plate_main(_stdin=raw, _environ=BASE_ENV, **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_not_called()


def test_bad_json_after_fast_path_exits_0():
    # Scenario: input contains "/plate but is not valid JSON
    # Setup:
    raw = '"/plate this is not json'
    deps = _make_deps()
    # Test action:
    rc = plate_main(_stdin=raw, _environ=BASE_ENV, **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_not_called()


# ---------------------------------------------------------------------------
# Prompt regex filtering
# ---------------------------------------------------------------------------


def test_typo_prompt_exits_0_silently():
    # Scenario: prompt looks like /plate but has a typo variant
    # Setup:
    raw = _make_payload(prompt="/plate --bogus-flag")
    deps = _make_deps()
    # Test action:
    rc = plate_main(_stdin=raw, _environ=BASE_ENV, **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_not_called()


def test_prompt_with_leading_whitespace_is_accepted():
    # Scenario: prompt has leading whitespace (lstrip applied)
    # Setup:
    raw = _make_payload(prompt="  /plate --done")
    deps = _make_deps()
    # Test action:
    rc = plate_main(_stdin=raw, _environ=BASE_ENV, **deps)
    # Test verification:
    assert rc == 0
    cmd = deps["_subprocess_run"].call_args[0][0]
    assert cmd[2] == "done"


# ---------------------------------------------------------------------------
# Repo-root detection
# ---------------------------------------------------------------------------


def test_missing_repo_root_emits_friendly_message():
    # Scenario: git rev-parse finds no repo (returns empty string)
    # Setup:
    raw = _make_payload()
    deps = _make_deps(repo_root="")
    # Test action:
    rc = plate_main(_stdin=raw, _environ=BASE_ENV, **deps)
    # Test verification:
    assert rc == 0
    deps["_hookjson_emitBlock"].assert_called_once()
    msg = deps["_hookjson_emitBlock"].call_args[0][0]
    assert "git repository" in msg
    assert "git init" in msg


# ---------------------------------------------------------------------------
# Variant -> cli.py argv dispatch
# ---------------------------------------------------------------------------


def _get_cli_args(deps: dict, stdin_payload: str, env: dict | None = None) -> list[str]:
    """Run plate_main and return the positional args passed to python3 cli.py."""
    env = env or BASE_ENV
    plate_main(_stdin=stdin_payload, _environ=env, **deps)
    call_args = deps["_subprocess_run"].call_args[0][0]
    # call_args = ["python3", "<cli_path>", *subcommand_args]
    return call_args[2:]


def test_dispatch_bare_plate_is_push():
    # Scenario: /plate -> push with session_id, transcript, repo_root
    # Setup:
    deps = _make_deps()
    raw = _make_payload(prompt="/plate", session_id="SID", transcript_path="/t.jsonl")
    # Test action:
    args = _get_cli_args(deps, raw)
    # Test verification:
    assert args[0] == "push"
    assert args[1] == "SID"
    assert args[2] == "/t.jsonl"
    assert args[3] == "/fake/repo"


def test_dispatch_done():
    # Scenario: /plate --done -> done <repo_root>
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --done"))
    # Test verification:
    assert args == ["done", "/fake/repo"]


def test_dispatch_drop():
    # Scenario: /plate --drop -> drop <repo_root>
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --drop"))
    # Test verification:
    assert args == ["drop", "/fake/repo"]


def test_dispatch_trash():
    # Scenario: /plate --trash -> trash <repo_root>
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --trash"))
    # Test verification:
    assert args == ["trash", "/fake/repo"]


def test_dispatch_recycle():
    # Scenario: /plate --recycle -> recycle <repo_root>
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --recycle"))
    # Test verification:
    assert args == ["recycle", "/fake/repo"]


def test_dispatch_recycle_list():
    # Scenario: /plate --recycle --list -> recycle <repo_root> --list
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --recycle --list"))
    # Test verification:
    assert args == ["recycle", "/fake/repo", "--list"]


def test_dispatch_recycle_named():
    # Scenario: /plate --recycle feat/my-branch -> recycle <repo_root> feat/my-branch
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --recycle feat/my-branch"))
    # Test verification:
    assert args == ["recycle", "/fake/repo", "feat/my-branch"]


def test_dispatch_show():
    # Scenario: /plate --show -> show <repo_root>
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --show"))
    # Test verification:
    assert args == ["show", "/fake/repo"]


def test_dispatch_next():
    # Scenario: /plate --next -> next <repo_root>
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --next"))
    # Test verification:
    assert args == ["next", "/fake/repo"]


def test_dispatch_next_named():
    # Scenario: /plate --next feat.123 -> next <repo_root> feat.123
    # Setup:
    deps = _make_deps()
    # Test action:
    args = _get_cli_args(deps, _make_payload(prompt="/plate --next feat.123"))
    # Test verification:
    assert args == ["next", "/fake/repo", "feat.123"]


# ---------------------------------------------------------------------------
# Unrecognized variant
# ---------------------------------------------------------------------------


def test_unrecognized_variant_emits_message():
    # Scenario: prompt passes regex but falls through all dispatch branches
    # (Manually inject a prompt that matches regex but not any branch via
    # monkeypatching _PROMPT_RE to accept an extra pattern.)
    # Setup: craft a prompt that the current dispatch map does not handle.
    # We directly call with a patched stdin where prompt is valid per regex
    # but not handled -- impossible with current regex, so we test the else
    # branch by temporarily relaxing via a known pattern not in the map.
    # Instead, verify the emit path for unrecognized by testing that the
    # dispatch else-branch message contains "unrecognized variant".
    import _tmp_plate_main as mod
    original_re = mod._PROMPT_RE
    try:
        mod._PROMPT_RE = re.compile(r"^/plate( --unknown)?$")
        deps = _make_deps()
        rc = plate_main(
            _stdin=_make_payload(prompt="/plate --unknown"),
            _environ=BASE_ENV,
            **deps,
        )
        assert rc == 0
        call_msg = deps["_hookjson_emitBlock"].call_args[0][0]
        assert "unrecognized variant" in call_msg
        assert "/plate --unknown" in call_msg
    finally:
        mod._PROMPT_RE = original_re


# ---------------------------------------------------------------------------
# cli.py output is forwarded
# ---------------------------------------------------------------------------


def test_cli_output_forwarded_via_emit_block():
    # Scenario: cli.py produces stdout; it should be passed to emit_block
    # Setup:
    deps = _make_deps()
    deps["_subprocess_run"].return_value = MagicMock(
        stdout="branch pushed\n", stderr="", returncode=0
    )
    # Test action:
    rc = plate_main(_stdin=_make_payload(), _environ=BASE_ENV, **deps)
    # Test verification:
    assert rc == 0
    emitted = deps["_hookjson_emitBlock"].call_args[0][0]
    assert "branch pushed" in emitted


def test_cli_stderr_included_in_emit_block():
    # Scenario: cli.py writes to stderr; stderr should also be captured
    # Setup:
    deps = _make_deps()
    deps["_subprocess_run"].return_value = MagicMock(
        stdout="", stderr="warning: detached HEAD\n", returncode=1
    )
    # Test action:
    rc = plate_main(_stdin=_make_payload(), _environ=BASE_ENV, **deps)
    # Test verification:
    assert rc == 0
    emitted = deps["_hookjson_emitBlock"].call_args[0][0]
    assert "warning: detached HEAD" in emitted


# ---------------------------------------------------------------------------
# Log-file promotion
# ---------------------------------------------------------------------------


def test_log_file_promoted_to_per_repo_path_when_no_override(tmp_path):
    # Scenario: PLATE_LOG_FILE not set -> log path moved under REPO_ROOT/.plate/
    # Setup:
    env = {**BASE_ENV, "CLAUDE_PLUGIN_DATA": str(tmp_path)}
    repo_root = str(tmp_path / "myrepo")
    (tmp_path / "myrepo").mkdir()
    deps = _make_deps(repo_root=repo_root)
    # Test action:
    plate_main(_stdin=_make_payload(), _environ=env, **deps)
    # Test verification:
    deps["_ensureGitignoreEntry"].assert_called_once_with(
        repo_root, ".plate/plate-log.txt"
    )


def test_log_file_override_respected(tmp_path):
    # Scenario: PLATE_LOG_FILE set explicitly -> gitignore ensure not called
    # Setup:
    override_log = str(tmp_path / "custom.log")
    env = {**BASE_ENV, "PLATE_LOG_FILE": override_log}
    deps = _make_deps()
    # Test action:
    plate_main(_stdin=_make_payload(), _environ=env, **deps)
    # Test verification:
    deps["_ensureGitignoreEntry"].assert_not_called()


# re import needed for test_unrecognized_variant_emits_message
import re  # noqa: E402
