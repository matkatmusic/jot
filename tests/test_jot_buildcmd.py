"""Tests for jot_lib jot_buildClaudeCmd (Claude command + settings + hooks construction)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from common.scripts.jot_lib import jot_buildClaudeCmd

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- jot_buildClaudeCmd ---

@pytest.fixture
def plugin_layout(tmp_path: Path):
    # Setup: synthesize a plugin root with the orchestrator script and bundled permissions defaults.
    plugin_root = tmp_path / "plugin_root"
    plugin_data = tmp_path / "plugin_data"
    (plugin_root / "scripts").mkdir(parents=True)
    (plugin_root / "skills/jot/scripts/assets").mkdir(parents=True)
    (plugin_root / "scripts/jot_plugin_orchestrator.py").write_text("# fake orchestrator\n")
    (plugin_root / "skills/jot/scripts/assets/permissions.default.json").write_text("{}")
    (plugin_root / "skills/jot/scripts/assets/permissions.default.json.sha256").write_text("deadbeef")

    fixed_tmp = tmp_path / "jot.ABCDEF"
    fixed_tmp.mkdir()

    seed_calls: list[tuple] = []
    expand_calls: list[tuple] = []

    def fake_seed(perm_file, default_file, default_sha, prior_sha, log_file, label):
        seed_calls.append((perm_file, default_file, default_sha, prior_sha, log_file, label))
        Path(perm_file).write_text('{"permissions":{"allow":[]}}')
        return 0

    def fake_expand(perm_file, env):
        expand_calls.append((perm_file, dict(env)))
        return '["Bash(echo:*)", "Read(*)"]'

    return {
        "plugin_root": plugin_root,
        "plugin_data": plugin_data,
        "tmp_inv": fixed_tmp,
        "seed_calls": seed_calls,
        "expand_calls": expand_calls,
        "fake_seed": fake_seed,
        "fake_expand": fake_expand,
    }


def _invoke_jot_build(layout, **overrides):
    kwargs = dict(
        claude_plugin_root=str(layout["plugin_root"]),
        claude_plugin_data=str(layout["plugin_data"]),
        cwd="/work/proj",
        repo_root="/work/proj",
        home="/Users/x",
        input_file="/work/proj/Todos/2026_input.txt",
        state_dir="/work/proj/Todos/.jot-state",
        log_file=str(layout["plugin_data"] / "jot-log.txt"),
        permissions_seed=layout["fake_seed"],
        expand_permissions=layout["fake_expand"],
        tmpdir_factory=lambda: str(layout["tmp_inv"]),
    )
    kwargs.update(overrides)
    return jot_buildClaudeCmd(**kwargs)


def test_jot_buildClaudeCmd_returns_tmpdir_inv_from_factory(plugin_layout):
    # Scenario: bash mktemp -d is replaced by injectable tmpdir_factory.
    # Test action: invoke jot_buildClaudeCmd.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: returned TMPDIR_INV is the factory's directory.
    assert out["TMPDIR_INV"] == str(plugin_layout["tmp_inv"])


def test_jot_buildClaudeCmd_settings_file_lives_under_tmpdir(plugin_layout):
    # Scenario: bash sets SETTINGS_FILE="$TMPDIR_INV/settings.json".
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: SETTINGS_FILE path equals tmpdir_inv/settings.json.
    assert out["SETTINGS_FILE"] == f"{plugin_layout['tmp_inv']}/settings.json"


def test_jot_buildClaudeCmd_permissions_file_under_plugin_data(plugin_layout):
    # Scenario: bash sets PERMISSIONS_FILE="$CLAUDE_PLUGIN_DATA/permissions.local.json".
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: PERMISSIONS_FILE path resolves under plugin_data.
    assert out["PERMISSIONS_FILE"] == f"{plugin_layout['plugin_data']}/permissions.local.json"


def test_jot_buildClaudeCmd_orchestrator_script_not_copied_into_tmpdir(plugin_layout):
    # Scenario: hook commands reference the source orchestrator via the literal plugin-root path baked at write time; no per-invocation copy.
    # Test action: invoke.
    _invoke_jot_build(plugin_layout)
    # Test verification: tmpdir contains no orchestrator copy.
    copied = plugin_layout["tmp_inv"] / "jot_plugin_orchestrator.py"
    assert not copied.exists()


def test_jot_buildClaudeCmd_hook_commands_reference_plugin_root_orchestrator(plugin_layout):
    # Scenario: hook command strings must embed the literal absolute plugin-root path to scripts/jot_plugin_orchestrator.py.
    # The worker claude does NOT inherit CLAUDE_PLUGIN_ROOT from the parent host, so a ${CLAUDE_PLUGIN_ROOT} shell token in
    # the worker's hooks.json expands to empty and the SessionStart hook silently fails. Bake the absolute path at write time.
    # Test action: invoke and parse hooks.json.
    out = _invoke_jot_build(plugin_layout)
    parsed = json.loads(Path(out["HOOKS_JSON_FILE"]).read_text())
    # Test verification: every hook command embeds the literal plugin-root orchestrator path, with no env-var token and no tmpdir copy.
    expected_path = f"{plugin_layout['plugin_root']}/scripts/jot_plugin_orchestrator.py"
    for key in ("SessionStart", "Stop", "SessionEnd"):
        cmd = parsed[key][0]["hooks"][0]["command"]
        assert expected_path in cmd, f"{key} hook missing literal plugin-root path: {cmd}"
        assert "${CLAUDE_PLUGIN_ROOT}" not in cmd, f"{key} hook still contains shell var token: {cmd}"
        assert f"{plugin_layout['tmp_inv']}/jot_plugin_orchestrator.py" not in cmd


def test_jot_buildClaudeCmd_plugin_data_dir_is_created(plugin_layout):
    # Scenario: bash `mkdir -p "$CLAUDE_PLUGIN_DATA"` ensures the dir exists.
    # Setup: plugin_data does not exist before invoke.
    assert not plugin_layout["plugin_data"].exists()
    # Test action: invoke.
    _invoke_jot_build(plugin_layout)
    # Test verification: plugin_data exists as a directory afterwards.
    assert plugin_layout["plugin_data"].is_dir()


def test_jot_buildClaudeCmd_permissions_seed_invoked_with_expected_args(plugin_layout):
    # Scenario: function delegates seeding to permissions_seed dependency.
    # Test action: invoke.
    _invoke_jot_build(plugin_layout)
    # Test verification: seed called once with the six bash args in order.
    calls = plugin_layout["seed_calls"]
    assert len(calls) == 1
    perm_file, default_file, default_sha, prior_sha, log_file, label = calls[0]
    assert perm_file == f"{plugin_layout['plugin_data']}/permissions.local.json"
    assert default_file == f"{plugin_layout['plugin_root']}/skills/jot/scripts/assets/permissions.default.json"
    assert default_sha == default_file + ".sha256"
    assert prior_sha == f"{plugin_layout['plugin_data']}/permissions.default.sha256"
    assert label == "jot"


def test_jot_buildClaudeCmd_expand_permissions_receives_cwd_home_repo_root(plugin_layout):
    # Scenario: bash exports CWD/HOME/REPO_ROOT before running the python helper.
    # Test action: invoke with distinct values.
    _invoke_jot_build(plugin_layout, cwd="/A", home="/B", repo_root="/C")
    # Test verification: env contains all three keys with the input values.
    perm_file, env = plugin_layout["expand_calls"][0]
    assert env["CWD"] == "/A"
    assert env["HOME"] == "/B"
    assert env["REPO_ROOT"] == "/C"
    assert perm_file == f"{plugin_layout['plugin_data']}/permissions.local.json"


def test_jot_buildClaudeCmd_hooks_json_file_is_written_and_valid_json(plugin_layout):
    # Scenario: bash writes hooks.json via heredoc into TMPDIR_INV.
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: hooks.json exists, parses, and has the three hook keys.
    hooks_path = Path(out["HOOKS_JSON_FILE"])
    assert hooks_path == plugin_layout["tmp_inv"] / "hooks.json"
    parsed = json.loads(hooks_path.read_text())
    assert set(parsed.keys()) == {"SessionStart", "Stop", "SessionEnd"}


def test_jot_buildClaudeCmd_hooks_json_session_start_command_includes_input_file_and_tmpdir(plugin_layout):
    # Scenario: SessionStart hook command embeds INPUT_FILE and TMPDIR_INV.
    # Test action: parse generated hooks.json.
    out = _invoke_jot_build(plugin_layout, input_file="/p/Todos/IN.txt")
    # Test verification: SessionStart command string contains both paths.
    parsed = json.loads(Path(out["HOOKS_JSON_FILE"]).read_text())
    cmd = parsed["SessionStart"][0]["hooks"][0]["command"]
    assert "/p/Todos/IN.txt" in cmd
    assert str(plugin_layout["tmp_inv"]) in cmd
    assert "jot-session-start" in cmd


def test_jot_buildClaudeCmd_hooks_json_stop_command_includes_state_dir(plugin_layout):
    # Scenario: Stop hook is the only hook that gets the state_dir argument.
    # Test action: parse hooks.json.
    out = _invoke_jot_build(plugin_layout, state_dir="/p/Todos/.jot-state")
    # Test verification: Stop command contains state_dir; SessionEnd does not.
    parsed = json.loads(Path(out["HOOKS_JSON_FILE"]).read_text())
    stop_cmd = parsed["Stop"][0]["hooks"][0]["command"]
    end_cmd = parsed["SessionEnd"][0]["hooks"][0]["command"]
    assert "/p/Todos/.jot-state" in stop_cmd
    assert "/p/Todos/.jot-state" not in end_cmd


def test_jot_buildClaudeCmd_claude_cmd_contains_settings_and_cwd(plugin_layout):
    # Scenario: final CLAUDE_CMD comes from claude_buildCmd.
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout, cwd="/work/abc")
    # Test verification: CLAUDE_CMD string contains settings path and cwd.
    assert out["SETTINGS_FILE"] in out["CLAUDE_CMD"]
    assert "/work/abc" in out["CLAUDE_CMD"]
    assert out["CLAUDE_CMD"].startswith("claude ")


def test_jot_buildClaudeCmd_settings_file_written_with_expanded_allow_json(plugin_layout):
    # Scenario: claude_buildCmd writes settings JSON containing expanded allow JSON.
    # Test action: invoke.
    out = _invoke_jot_build(plugin_layout)
    # Test verification: settings.json on disk contains the sentinel allow entries.
    body = Path(out["SETTINGS_FILE"]).read_text()
    assert '"Bash(echo:*)"' in body
    assert '"Read(*)"' in body


def test_jot_pluginOrchestrator_isImportable_fromArbitraryCwd(tmp_path: Path):
    # Scenario: SessionStart hook spawns the orchestrator from a worker pane whose cwd is the user's repo, not the plugin tree. The orchestrator must self-bootstrap its sys.path to find common/scripts/* without needing a sibling 'common/' subtree at its parent.
    # Setup: invoke the real source orchestrator from tmp_path (no 'common/' sibling) so a regression to relative-parent path resolution would surface as ModuleNotFoundError.
    src = REPO_ROOT / "scripts" / "jot_plugin_orchestrator.py"
    assert src.exists(), src
    # Test action: invoke as the SessionStart hook would, with a non-existent input file (orchestrator may exit nonzero, but must not fail on import).
    result = subprocess.run(
        [sys.executable, str(src), "jot-session-start", "/no/such/input.txt", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    # Test verification: stderr must be free of Python import errors. Other failures (missing sidecar, etc.) are acceptable here.
    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert "ImportError" not in result.stderr, result.stderr
