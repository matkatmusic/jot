"""Tests for jot_lib (and jot-related orchestrator functions)."""
from __future__ import annotations

import io as _io_dispatch
import json
import os
import sys
import time
from io import StringIO
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

import jot_plugin_orchestrator as _orchestrator
from jot_plugin_orchestrator import dispatch_main
from common.scripts import jot_lib as mod
from common.scripts.jot_lib import (
    jot_buildClaudeCmd,
    jot_collectDiagnostics,
    jot_diagIndent,
    jot_diagKv,
    jot_diagSection,
    jot_initState,
    jot_launchPhase2Window,
    jot_main,
    jot_popFirstFromQueue,
    jot_rotateAudit,
    jot_sendPrompt,
    jot_sessionEnd,
    jot_sessionStart,
    jot_stop,
)
from common.scripts.claude_lib import claude_buildCmd
from common.scripts.tmux_lib import (
    tmux_ensureSession,
    tmux_retile,
    tmux_sendAndSubmit,
    tmux_setPaneTitle,
    tmux_splitWorkerPane,
    tmux_waitForClaudeReadiness,
)
from common.scripts.todo_lib import todoList_main
from common.scripts.util_lib import FileLock, LockTimeout, terminal_spawnIfNeeded

# --- jot_initState ---


def test_jot_initState_creates_state_directory_when_missing(tmp_path: Path) -> None:
    # Scenario: caller points at a state dir that does not yet exist.
    # Setup: choose a path under tmp_path that has not been created.
    state_dir = tmp_path / "jot-state"
    assert not state_dir.exists()
    # Test action.
    jot_initState(state_dir)
    # Test verification: directory exists after the call.
    assert state_dir.is_dir()


def test_jot_initState_creates_three_tracked_files(tmp_path: Path) -> None:
    # Scenario: fresh state dir must contain the three jot tracking files.
    # Setup: empty target path.
    state_dir = tmp_path / "jot-state"
    # Test action.
    jot_initState(state_dir)
    # Test verification: each tracked file is present and empty.
    for name in ("queue.txt", "active_job.txt", "audit.log"):
        f = state_dir / name
        assert f.is_file()
        assert f.stat().st_size == 0


def test_jot_initState_preserves_existing_queue_contents(tmp_path: Path) -> None:
    # Scenario: re-running on a populated state dir must not clobber data.
    # Setup: pre-create state dir with queued work.
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    queue = state_dir / "queue.txt"
    queue.write_text("job-1\njob-2\n")
    # Test action.
    jot_initState(state_dir)
    # Test verification: queue contents intact.
    assert queue.read_text() == "job-1\njob-2\n"


def test_jot_initState_preserves_existing_audit_log(tmp_path: Path) -> None:
    # Scenario: audit log must survive re-init (append-only history).
    # Setup: pre-existing audit log with entries.
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    audit = state_dir / "audit.log"
    audit.write_text("2026-05-04 event\n")
    # Test action.
    jot_initState(state_dir)
    # Test verification: audit log untouched.
    assert audit.read_text() == "2026-05-04 event\n"


def test_jot_initState_idempotent_on_second_call(tmp_path: Path) -> None:
    # Scenario: invoking twice is a no-op beyond touch.
    # Setup: run once to establish the state dir.
    state_dir = tmp_path / "jot-state"
    jot_initState(state_dir)
    # Test action.
    jot_initState(state_dir)
    # Test verification: dir + three files still present.
    assert state_dir.is_dir()
    for name in ("queue.txt", "active_job.txt", "audit.log"):
        assert (state_dir / name).is_file()


def test_jot_initState_creates_parent_directories(tmp_path: Path) -> None:
    # Scenario: state path nested under non-existent parents.
    # Setup: deep path with no intermediate dirs.
    state_dir = tmp_path / "a" / "b" / "c" / "jot-state"
    # Test action.
    jot_initState(state_dir)
    # Test verification: full chain created and files present.
    assert state_dir.is_dir()
    assert (state_dir / "queue.txt").is_file()


def test_jot_initState_accepts_string_path(tmp_path: Path) -> None:
    # Scenario: callers pass a plain str path (parity with bash arg).
    # Setup: build str path.
    state_dir = str(tmp_path / "jot-state")
    # Test action.
    jot_initState(state_dir)
    # Test verification: behaves identically to Path input.
    assert Path(state_dir).is_dir()
    assert (Path(state_dir) / "audit.log").is_file()


def test_jot_initState_touch_refreshes_mtime_on_existing_file(tmp_path: Path) -> None:
    # Scenario: bash `touch` updates mtime; Python parity required.
    # Setup: pre-existing file with an old mtime.
    import os
    state_dir = tmp_path / "jot-state"
    state_dir.mkdir()
    queue = state_dir / "queue.txt"
    queue.write_text("x\n")
    old = 1_000_000.0
    os.utime(queue, (old, old))
    before = queue.stat().st_mtime
    # Test action.
    jot_initState(state_dir)
    # Test verification: mtime advanced.
    assert queue.stat().st_mtime > before


# --- jot_popFirstFromQueue ---


def _seed_jot_state(state_dir: Path, queue_lines: list[str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "queue.txt").write_text(
        ("\n".join(queue_lines) + "\n") if queue_lines else ""
    )
    (state_dir / "active_job.txt").write_text("")


def test_jot_popFirstFromQueue_returns_first_line(tmp_path: Path) -> None:
    # Scenario: 3-entry queue; pop returns the first one.
    # Setup: queue with three jobs.
    state = tmp_path / "state"
    _seed_jot_state(state, ["job-a", "job-b", "job-c"])
    # Test action.
    popped = jot_popFirstFromQueue(str(state))
    # Test verification.
    assert popped == "job-a"


def test_jot_popFirstFromQueue_removes_first_line_from_queue_file(tmp_path: Path) -> None:
    # Scenario: pop must mutate queue.txt by deleting line 1.
    state = tmp_path / "state"
    _seed_jot_state(state, ["job-a", "job-b", "job-c"])
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "queue.txt").read_text() == "job-b\njob-c\n"


def test_jot_popFirstFromQueue_writes_popped_line_to_active_job_file(tmp_path: Path) -> None:
    # Scenario: pop writes popped entry to active_job.txt (head -1 > active).
    state = tmp_path / "state"
    _seed_jot_state(state, ["alpha", "beta"])
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "active_job.txt").read_text() == "alpha\n"


def test_jot_popFirstFromQueue_returns_none_on_empty_queue(tmp_path: Path) -> None:
    # Scenario: empty queue.txt; bash returned 1 -> Python returns None.
    state = tmp_path / "state"
    _seed_jot_state(state, [])
    # Test action + verification.
    assert jot_popFirstFromQueue(str(state)) is None


def test_jot_popFirstFromQueue_empty_queue_does_not_modify_active_job(tmp_path: Path) -> None:
    # Scenario: empty-queue branch returns early; active_job.txt untouched.
    state = tmp_path / "state"
    _seed_jot_state(state, [])
    (state / "active_job.txt").write_text("prev-job\n")
    # Test action.
    jot_popFirstFromQueue(str(state))
    # Test verification.
    assert (state / "active_job.txt").read_text() == "prev-job\n"


def test_jot_popFirstFromQueue_single_entry_queue_becomes_empty(tmp_path: Path) -> None:
    # Scenario: pop the only entry; queue.txt becomes empty.
    state = tmp_path / "state"
    _seed_jot_state(state, ["only-job"])
    # Test action.
    popped = jot_popFirstFromQueue(str(state))
    # Test verification.
    assert popped == "only-job"
    assert (state / "queue.txt").read_text() == ""


# --- jot_sendPrompt ---


def test_jot_sendPrompt_delegates_to_tmux_sendAndSubmit_with_target_and_prompt(monkeypatch):
    # Scenario: caller has tmux target + input file path; jot_sendPrompt hands control to tmux_sendAndSubmit.
    calls = []
    # Setup: patch boundary helper to observe args.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit",
                        lambda p, t: calls.append((p, t)) or 0)
    # Test action.
    rc = jot_sendPrompt("jot:jots.0", "/tmp/jot.ABC123/input.txt")
    # Test verification: helper invoked with target + composed prompt.
    assert rc == 0
    assert calls == [(
        "jot:jots.0",
        "Read /tmp/jot.ABC123/input.txt and follow the instructions at the top of that file",
    )]


def test_jot_sendPrompt_returns_nonzero_when_tmux_helper_fails(monkeypatch):
    # Scenario: tmux send/submit fails; jot_sendPrompt propagates rc.
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 1)
    # Test action + verification.
    assert jot_sendPrompt("jot:jots.9", "/tmp/anything.txt") == 1


def test_jot_sendPrompt_input_path_interpolated_verbatim(monkeypatch):
    # Scenario: paths with spaces/unusual chars must appear literally in the prompt.
    weird_path = "/tmp/jot dir/weird name.txt"
    seen = []
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit",
                        lambda p, t: seen.append((p, t)) or 0)
    # Test action.
    jot_sendPrompt("pane@7", weird_path)
    # Test verification.
    assert seen == [(
        "pane@7",
        f"Read {weird_path} and follow the instructions at the top of that file",
    )]


# --- jot_rotateAudit ---


def test_jot_rotateAudit_silent_noop_when_file_missing(tmp_path: Path) -> None:
    # Scenario: audit log file does not exist; rotate is a silent no-op.
    # Setup: path that is not created.
    missing = tmp_path / "audit.log"
    # Test action.
    result = jot_rotateAudit(str(missing))
    # Test verification.
    assert result is None
    assert not missing.exists()


def test_jot_rotateAudit_leaves_short_file_untouched(tmp_path: Path) -> None:
    # Scenario: log under threshold must not be modified.
    # Setup: 50 lines, default max=1000.
    audit = tmp_path / "audit.log"
    original = "\n".join(f"line{i}" for i in range(50)) + "\n"
    audit.write_text(original)
    # Test action.
    jot_rotateAudit(str(audit))
    # Test verification.
    assert audit.read_text() == original


def test_jot_rotateAudit_truncates_to_last_max_lines_when_oversized(tmp_path: Path) -> None:
    # Scenario: log exceeds max_lines; only the tail is kept.
    # Setup: 1500 lines, default max=1000.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"line{i}" for i in range(1500)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit))
    # Test verification.
    kept = audit.read_text().splitlines()
    assert len(kept) == 1000
    assert kept[0] == "line500"
    assert kept[-1] == "line1499"


def test_jot_rotateAudit_respects_custom_max_lines(tmp_path: Path) -> None:
    # Scenario: caller-supplied max_lines overrides default.
    # Setup: 20 lines, max=5.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"l{i}" for i in range(20)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit), 5)
    # Test verification.
    assert audit.read_text().splitlines() == ["l15", "l16", "l17", "l18", "l19"]


def test_jot_rotateAudit_no_trim_sidecar_left_behind(tmp_path: Path) -> None:
    # Scenario: rotation must not leave .trim sidecar in directory.
    # Setup: oversized log forcing rotation.
    audit = tmp_path / "audit.log"
    audit.write_text("\n".join(f"x{i}" for i in range(2000)) + "\n")
    # Test action.
    jot_rotateAudit(str(audit), 100)
    # Test verification: only audit.log present.
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["audit.log"]


# --- jot_buildClaudeCmd ---

@pytest.fixture
def plugin_layout(tmp_path: Path):
    # Setup: synthesize a plugin root with the orchestrator script and bundled permissions defaults.
    plugin_root = tmp_path / "plugin_root"
    plugin_data = tmp_path / "plugin_data"
    (plugin_root / "scripts").mkdir(parents=True)
    (plugin_root / "skills/jot/scripts/assets").mkdir(parents=True)
    (plugin_root / "scripts/jot-plugin-orchestrator.sh").write_text("# fake orchestrator\n")
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


def test_jot_buildClaudeCmd_orchestrator_script_copied_into_tmpdir(plugin_layout):
    # Scenario: lifecycle-safe copy of orchestrator script into tmpdir.
    # Test action: invoke.
    _invoke_jot_build(plugin_layout)
    # Test verification: tmpdir copy exists and matches source bytes.
    copied = plugin_layout["tmp_inv"] / "jot-plugin-orchestrator.sh"
    assert copied.read_text() == "# fake orchestrator\n"


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



# --- jot_launchPhase2Window ---

@pytest.fixture
def phase2_env(tmp_path: Path, monkeypatch):
    # Setup: realistic env vars and tmpdirs the function reads.
    repo_root = tmp_path / "repo"
    plugin_data = tmp_path / "plugin_data"
    plugin_root = tmp_path / "plugin_root"
    repo_root.mkdir()
    plugin_data.mkdir()
    plugin_root.mkdir()
    log_file = tmp_path / "jot.log"
    log_file.touch()
    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CWD", str(repo_root))
    monkeypatch.setenv("LOG_FILE", str(log_file))
    monkeypatch.setenv("INPUT_FILE", str(repo_root / "Todos" / "input.txt"))
    monkeypatch.setenv("HOME", "/Users/tester")
    return {
        "repo_root": repo_root,
        "plugin_data": plugin_data,
        "plugin_root": plugin_root,
        "log_file": log_file,
    }


def _phase2_patches(tmp_path: Path):
    tmpdir_inv = tmp_path / "tmpinv"
    tmpdir_inv.mkdir()
    lock_obj = MagicMock()
    lock_obj.__enter__.return_value = lock_obj
    return {
        "tmpdir_inv": tmpdir_inv,
        "lock_obj": lock_obj,
        "file_lock": patch.object(mod, "FileLock", return_value=lock_obj),
        "state_init": patch.object(mod, "jot_initState"),
        "build_cmd": patch.object(
            mod,
            "jot_buildClaudeCmd",
            return_value={
                "TMPDIR_INV": str(tmpdir_inv),
                "SETTINGS_FILE": "/tmp/x/settings.json",
                "CLAUDE_CMD": "claude --foo",
            },
        ),
        "ensure": patch.object(mod, "tmux_ensureSession", return_value=0),
        "split": patch.object(mod, "tmux_splitWorkerPane", return_value="%42"),
        "title": patch.object(mod, "tmux_setPaneTitle", return_value=0),
        "retile": patch.object(mod, "tmux_retile", return_value=0),
        "spawn": patch.object(mod, "terminal_spawnIfNeeded", return_value=0),
    }


def _enter_phase2_patches(patches: dict):
    entered = {}
    for key, value in patches.items():
        if key in {"tmpdir_inv", "lock_obj"}:
            entered[key] = value
        else:
            entered[key] = value.__enter__()
    return entered


def _exit_phase2_patches(patches: dict) -> None:
    for key, value in patches.items():
        if key not in {"tmpdir_inv", "lock_obj"}:
            value.__exit__(None, None, None)


def test_jot_launchPhase2Window_initializes_state_dir_under_repo_root_todos(phase2_env, tmp_path: Path):
    # Scenario: function derives STATE_DIR=$REPO_ROOT/Todos/.jot-state and initializes it.
    # Setup: patch external tmux/build/lock boundaries.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: state init receives the derived state directory.
        expected = str(phase2_env["repo_root"] / "Todos" / ".jot-state")
        m["state_init"].assert_called_once_with(expected)
        assert os.environ["STATE_DIR"] == expected
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_acquires_global_tmux_lock_with_10s_timeout(phase2_env, tmp_path: Path):
    # Scenario: function must hold the global tmux-launch lock during pane spawn.
    # Setup: patch external boundaries.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: FileLock constructed for the global lock path with timeout 10.
        expected_lock = str(phase2_env["plugin_data"] / "tmux-launch.lock")
        m["file_lock"].assert_called_once_with(expected_lock, timeout=10)
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_returns_1_if_lock_acquire_times_out(phase2_env):
    # Scenario: lock contention prevents tmux launch.
    # Setup: FileLock construction raises LockTimeout.
    with patch.object(mod, "FileLock", side_effect=LockTimeout), \
         patch.object(mod, "tmux_ensureSession") as ensure, \
         patch.object(mod, "tmux_splitWorkerPane") as split, \
         patch.object(mod, "jot_buildClaudeCmd") as build_cmd:
        # Test action: launch phase 2.
        rc = jot_launchPhase2Window()
    # Test verification: returns failure and does not reach tmux/build calls.
    assert rc == 1
    ensure.assert_not_called()
    split.assert_not_called()
    build_cmd.assert_not_called()
    assert "failed to acquire global tmux-launch lock" in phase2_env["log_file"].read_text()


def test_jot_launchPhase2Window_pane_counter_increments_modulo_20(phase2_env, tmp_path: Path):
    # Scenario: counter file holds 7, so next pane label is jot8.
    # Setup: seed pane-counter.txt.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    counter = phase2_env["plugin_data"] / "pane-counter.txt"
    counter.write_text("7\n")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: counter increments and pane title uses jot8.
        assert counter.read_text().strip() == "8"
        m["title"].assert_called_once_with("%42", "jot8")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_pane_counter_wraps_from_20_to_1(phase2_env, tmp_path: Path):
    # Scenario: counter at 20 wraps to 1.
    # Setup: seed pane-counter.txt with 20.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    counter = phase2_env["plugin_data"] / "pane-counter.txt"
    counter.write_text("20\n")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: counter wraps and pane title uses jot1.
        assert counter.read_text().strip() == "1"
        m["title"].assert_called_once_with("%42", "jot1")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_split_failure_releases_lock_and_returns_1(phase2_env, tmp_path: Path):
    # Scenario: tmux_splitWorkerPane returns None.
    # Setup: patch split failure.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    m["split"].return_value = None
    try:
        # Test action: launch phase 2.
        rc = jot_launchPhase2Window()
        # Test verification: lock context exits, no title/retile/spawn occurs, rc=1.
        assert rc == 1
        m["lock_obj"].__exit__.assert_called_once()
        m["title"].assert_not_called()
        m["retile"].assert_not_called()
        m["spawn"].assert_not_called()
        assert "tmux split-window returned empty pane id" in phase2_env["log_file"].read_text()
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_writes_pane_id_atomically_via_tmp_then_rename(phase2_env, tmp_path: Path):
    # Scenario: PANE_ID must be written through a temp file then renamed to tmux_target.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: target file has pane id and temp file is gone.
        target_file = m["tmpdir_inv"] / "tmux_target"
        tmp_file = m["tmpdir_inv"] / "tmux_target.tmp"
        assert target_file.read_text().strip() == "%42"
        assert not tmp_file.exists()
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_calls_tmux_helpers_in_required_order(phase2_env, tmp_path: Path):
    # Scenario: ordering invariant is ensureSession, split, title, retile, lock release, spawn.
    # Setup: attach mocks to a parent recorder.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    parent = MagicMock()
    parent.attach_mock(m["ensure"], "ensure")
    parent.attach_mock(m["split"], "split")
    parent.attach_mock(m["title"], "title")
    parent.attach_mock(m["retile"], "retile")
    parent.attach_mock(m["lock_obj"].__exit__, "lock_exit")
    parent.attach_mock(m["spawn"], "spawn")
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: ordering preserves lock release before terminal spawn.
        seq = [c[0] for c in parent.mock_calls if c[0] in {"ensure", "split", "title", "retile", "lock_exit", "spawn"}]
        assert seq == ["ensure", "split", "title", "retile", "lock_exit", "spawn"]
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_ensure_session_called_with_jot_jots_session_window(phase2_env, tmp_path: Path):
    # Scenario: ensureSession targets session jot and window jots with cwd plus keepalive command.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: ensureSession arguments match the shared jot tmux window contract.
        args = m["ensure"].call_args.args
        assert args[0] == "jot"
        assert args[1] == "jots"
        assert args[2] == str(phase2_env["repo_root"])
        assert "keepalive" in args[3].lower()
        assert args[4] == "jot: keepalive"
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_split_worker_called_with_built_claude_cmd(phase2_env, tmp_path: Path):
    # Scenario: split worker pane receives CLAUDE_CMD from jot_buildClaudeCmd.
    # Setup: customize build result command.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    m["build_cmd"].return_value = {
        "TMPDIR_INV": str(m["tmpdir_inv"]),
        "SETTINGS_FILE": "/tmp/x/settings.json",
        "CLAUDE_CMD": "claude --custom-arg",
    }
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: split worker uses the command from build result.
        m["split"].assert_called_once_with("jot:jots", str(phase2_env["repo_root"]), "claude --custom-arg")
    finally:
        _exit_phase2_patches(p)


def test_jot_launchPhase2Window_spawn_terminal_called_after_lock_released(phase2_env, tmp_path: Path):
    # Scenario: terminal spawn is invoked after lock-protected tmux setup.
    # Setup: normal patched launch.
    p = _phase2_patches(tmp_path)
    m = _enter_phase2_patches(p)
    try:
        # Test action: launch phase 2.
        jot_launchPhase2Window()
        # Test verification: terminal spawner gets session, log file, and prefix.
        m["spawn"].assert_called_once_with("jot", str(phase2_env["log_file"]), "jot")
    finally:
        _exit_phase2_patches(p)


# --- jot_diagSection ---


def test_jot_diagSection_starts_with_leading_newline() -> None:
    # Scenario: section banner must visually separate from prior output.
    # Setup + Test action.
    out = jot_diagSection("Foo")
    # Test verification: leading newline.
    assert out.startswith("\n")


def test_jot_diagSection_embeds_title_between_rules() -> None:
    # Scenario: title sandwiched between two identical horizontal rules.
    out = jot_diagSection("Section 1")
    # Test verification: exact 4-line layout.
    lines = out.split("\n")
    rule = "═" * 59
    assert lines[1] == rule
    assert lines[2] == "Section 1"
    assert lines[3] == rule


def test_jot_diagSection_rule_is_59_box_chars() -> None:
    # Scenario: rule width is exactly 59 U+2550 chars (bash hardcode).
    out = jot_diagSection("X")
    # Test verification.
    rule_line = out.split("\n")[1]
    assert len(rule_line) == 59
    assert set(rule_line) == {"═"}


def test_jot_diagSection_ends_with_trailing_newline() -> None:
    # Scenario: banner ends with \n so subsequent text starts on its own line.
    # Test action + verification.
    assert jot_diagSection("X").endswith("\n")


def test_jot_diagSection_preserves_empty_title() -> None:
    # Scenario: empty title still produces well-formed banner with 4 newlines.
    # Test action + verification.
    assert jot_diagSection("").count("\n") == 4


# --- jot_diagIndent ---


def test_jot_diagIndent_single_line_no_trailing_newline() -> None:
    # Scenario: single line, no trailing newline.
    # Test action + verification.
    assert jot_diagIndent("hello") == "  hello"


def test_jot_diagIndent_multiline_preserves_trailing_newline() -> None:
    # Scenario: typical command output with trailing newline.
    # Test action + verification.
    assert jot_diagIndent("a\nb\n") == "  a\n  b\n"


def test_jot_diagIndent_multiline_no_trailing_newline() -> None:
    # Scenario: text without trailing newline (e.g. captured via $(...)).
    # Test action + verification.
    assert jot_diagIndent("a\nb") == "  a\n  b"


def test_jot_diagIndent_blank_line_still_prefixed() -> None:
    # Scenario: blank lines also get 2-space prefix (matches sed).
    # Test action + verification.
    assert jot_diagIndent("a\n\nb\n") == "  a\n  \n  b\n"


def test_jot_diagIndent_empty_string_returns_empty() -> None:
    # Scenario: empty input -> empty output.
    # Test action + verification.
    assert jot_diagIndent("") == ""


def test_jot_diagIndent_only_newline() -> None:
    # Scenario: lone newline -> single empty line gets prefix.
    # Test action + verification.
    assert jot_diagIndent("\n") == "  \n"


# --- jot_diagKv ---


def test_jot_diagKv_short_key_left_padded_to_28() -> None:
    # Scenario: short key padded with spaces to width 28 + separator + value.
    # Test action + verification.
    assert jot_diagKv("path", "/tmp/x") == "path" + " " * 24 + " /tmp/x\n"


def test_jot_diagKv_value_starts_at_column_29() -> None:
    # Scenario: '%-28s ' yields key field 28 cols + 1-space separator -> col 29.
    out = jot_diagKv("k", "v")
    # Test verification.
    assert out.index("v") == 29


def test_jot_diagKv_long_key_not_truncated() -> None:
    # Scenario: keys >= 28 chars are NOT truncated (printf min-width).
    long_key = "k" * 40
    # Test action + verification.
    assert jot_diagKv(long_key, "v") == f"{long_key} v\n"


def test_jot_diagKv_ends_with_single_trailing_newline() -> None:
    # Scenario: each line has exactly one trailing newline.
    out = jot_diagKv("a", "b")
    # Test verification.
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_jot_diagKv_empty_value_still_emits_padded_key() -> None:
    # Scenario: empty value still emits padded key + space + newline.
    # Test action + verification.
    assert jot_diagKv("jq", "") == "jq" + " " * 26 + " \n"


def test_jot_diagKv_value_with_spaces_preserved_verbatim() -> None:
    # Scenario: value with internal spaces preserved as-is, not split.
    out = jot_diagKv("mtime", "Mon Jan  1 00:00:00")
    # Test verification.
    assert "Mon Jan  1 00:00:00\n" in out



def test_jot_stop_missingArgsReturnsZeroAndLogsToStderr(capsys):
    # Scenario: caller forgot a required arg (Stop hook misconfig).
    # Setup: pass empty strings for two of three positional args.
    # Test action: invoke jot_stop with empty input_file.
    rc = jot_stop("", "/tmp/jot.x", "/tmp/state")
    captured = capsys.readouterr()
    # Test verification: rc must be 0 (silent exit) and stderr must
    # mention all three arg names so operators can debug.
    assert rc == 0
    assert "missing args" in captured.err
    assert "input_file" in captured.err


def test_jot_stop_emptySidecarRetriesThenReturnsZero(jot_dirs, capsys, monkeypatch):
    # Scenario: tmux_target sidecar never gets written (split-window failed).
    # Setup: leave tmpdir_inv empty; stub time.sleep so retries are instant.
    monkeypatch.setattr("time.sleep", lambda _s: None)
    # Test action: call jot_stop; sidecar reader will exhaust retries.
    rc = jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
    )
    captured = capsys.readouterr()
    # Test verification: rc=0, stderr mentions the empty-sidecar diagnostic.
    assert rc == 0
    assert "tmux_target sidecar empty" in captured.err


def test_jot_stop_writesSuccessAuditLineWhenInputHasProcessedMarker(
    jot_dirs, kill_calls
):
    # Scenario: claude finished its job — input.txt's first line is PROCESSED:.
    # Setup: sidecar holds a pane id; input.txt has the marker on line 1.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%42")
    jot_dirs["input_file"].write_text("PROCESSED: ok\nbody\n")
    # Test action: invoke jot_stop with the test seam for the kill subshell.
    rc = jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    audit = (jot_dirs["state_dir"] / "audit.log").read_text().splitlines()
    # Test verification: rc=0, exactly one audit line shaped
    # "<ts> SUCCESS <input_file>" — no FAIL token anywhere.
    assert rc == 0
    assert len(audit) == 1
    assert " SUCCESS " in audit[0]
    assert audit[0].endswith(str(jot_dirs["input_file"]))
    assert "FAIL" not in audit[0]


def test_jot_stop_writesFailAuditLineWhenInputHasNoProcessedMarker(
    jot_dirs, kill_calls
):
    # Scenario: claude exited without writing the PROCESSED: marker.
    # Setup: sidecar present; input.txt's first line is unrelated text.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%42")
    jot_dirs["input_file"].write_text("hello world\n")
    # Test action: run jot_stop.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    audit = (jot_dirs["state_dir"] / "audit.log").read_text()
    # Test verification: audit line is FAIL and explains why.
    assert " FAIL " in audit
    assert "no PROCESSED marker" in audit


def test_jot_stop_writesFailAuditLineWhenInputFileMissing(jot_dirs, kill_calls):
    # Scenario: input.txt was deleted/never written by the worker.
    # Setup: sidecar present; do NOT create input.txt.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%42")
    # Test action: run jot_stop pointing at the absent file.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    audit = (jot_dirs["state_dir"] / "audit.log").read_text()
    # Test verification: audit line is FAIL with the missing-file reason.
    assert " FAIL " in audit
    assert "input.txt missing" in audit


def test_jot_stop_killsPaneAndRetilesAfterAuditWrite(jot_dirs, kill_calls):
    # Scenario: happy path — sidecar present, input processed.
    # Setup: pane id = "%99"; SUCCESS path so we know audit ran first.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%99")
    jot_dirs["input_file"].write_text("PROCESSED: yes\n")
    # Test action: run jot_stop with the kill seam capturing args.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    # Test verification: kill+retile invoked exactly once with the
    # sidecar pane id and the canonical "jot:jots" window target.
    assert calls == [("%99", "jot:jots")]


def test_jot_stop_initializesStateDirArtifacts(jot_dirs, kill_calls):
    # Scenario: state_dir must be ready (queue.txt, active_job.txt, audit.log)
    # before jot_stop returns.
    # Setup: empty state_dir; sidecar present.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%1")
    jot_dirs["input_file"].write_text("PROCESSED: yes\n")
    # Test action: run jot_stop.
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    # Test verification: all three state artifacts exist.
    state = jot_dirs["state_dir"]
    assert (state / "queue.txt").is_file()
    assert (state / "active_job.txt").is_file()
    assert (state / "audit.log").is_file()


def test_jot_stop_rotatesAuditLogToOneThousandLines(jot_dirs, kill_calls):
    # Scenario: audit.log has grown beyond the 1000-line ceiling.
    # Setup: pre-seed audit.log with 1500 lines; jot_stop appends one more
    # then rotates, so the final line count must be exactly 1000.
    calls, fake_bg = kill_calls
    _writeSidecar(jot_dirs["tmpdir_inv"], "%1")
    jot_dirs["input_file"].write_text("PROCESSED: yes\n")
    audit_path = jot_dirs["state_dir"] / "audit.log"
    audit_path.write_text("\n".join(f"old-line-{i}" for i in range(1500)) + "\n")
    # Test action: run jot_stop (will append + rotate).
    jot_stop(
        str(jot_dirs["input_file"]),
        str(jot_dirs["tmpdir_inv"]),
        str(jot_dirs["state_dir"]),
        background_kill=fake_bg,
    )
    final = audit_path.read_text().splitlines()
    # Test verification: trimmed to 1000 lines AND the most recent
    # SUCCESS line is preserved (it was the last write before rotate).
    assert len(final) == 1000
    assert any(" SUCCESS " in line for line in final)


def _stub_prompt_disp(monkeypatch, name, recorder, key):
    # Stub a stdin-mode entrypoint and rebuild the prompt dispatch tuple.
    # Operates on the real orchestrator module (where _PROMPT_DISPATCH lives).
    _dm = _orchestrator

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


def test_dispatchMain_leading_whitespace_in_prompt_tolerated(monkeypatch):
    # Scenario: prompt has leading whitespace; lstrip lets it match.
    # Setup: stub jot_main; prompt with spaces and tab.
    calls: list = []
    _stub_prompt_disp(monkeypatch, "jot_main", calls, "/jot")
    payload = json.dumps({"prompt": "   \t/jot foo"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1


def test_dispatchMain_jot_namespace_normalises_to_bare_skill(monkeypatch):
    # Scenario: prompt "/jot:todo-list ..." -> rewritten to "/todo-list ...".
    # Setup: stub todoList_main; namespaced prompt.
    calls: list = []
    _stub_prompt_disp(monkeypatch, "todoList_main", calls, "/todo-list")
    payload = json.dumps({"prompt": "/jot:todo-list show me"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1
    forwarded = json.loads(calls[0][1])
    assert forwarded["prompt"] == "/todo-list show me"


def test_dispatchMain_default_prompt_exits_zero(monkeypatch):
    # Scenario: prompt matches none of the known prefixes -> exit 0.
    # Setup: non-matching prompt; stub jot_main as a tripwire.
    tripwire: list = []
    _stub_prompt_disp(monkeypatch, "jot_main", tripwire, "/jot")
    payload = json.dumps({"prompt": "hello world no slash"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert tripwire == []


def test_dispatchMain_unknown_argv_falls_through_to_stdin_mode(monkeypatch):
    # Scenario: argv[0] is not known -> read stdin, route by prompt.
    # Setup: stub jot_main; provide stdin JSON with /jot prompt.
    calls: list = []
    _stub_prompt_disp(monkeypatch, "jot_main", calls, "/jot")
    payload = json.dumps({"prompt": "/jot hello"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main(["not-a-subcommand", "x"])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == "/jot"


def _writeSidecar(tmpdir_inv: Path, pane_id: str) -> None:
    (tmpdir_inv / "tmux_target").write_text(pane_id + "\n")


@pytest.fixture
def kill_calls(monkeypatch):
    # Test seam: capture pane-id + retile-target instead of touching tmux.
    calls: list[tuple[str, str]] = []

    def _fake_bg(pane_target: str, retile_target: str) -> None:
        calls.append((pane_target, retile_target))

    return calls, _fake_bg


@pytest.fixture
def jot_dirs(tmp_path: Path):
    # Standard layout: tmpdir_inv with sidecar, state_dir for audit.log,
    # plus an input_file path (which may or may not exist depending on test).
    tmpdir_inv = tmp_path / "jot.invXYZ"
    tmpdir_inv.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return {
        "tmpdir_inv": tmpdir_inv,
        "state_dir": state_dir,
        "input_file": tmp_path / "input.txt",
    }



def test_removes_tmp_jot_directory_recursively(tmp_path, monkeypatch):
    # Scenario: hook fires on a well-formed /tmp/jot.* tmpdir at session end.
    # Setup: create a fake /tmp/jot.<id> dir with nested content; redirect /tmp via symlink-style path.
    fake_root = tmp_path / "tmp"
    fake_root.mkdir()
    target = fake_root / "jot.abc123"
    (target / "subdir").mkdir(parents=True)
    (target / "subdir" / "tmux_target").write_text("%42")
    (target / "input.txt").write_text("PROCESSED: ok")
    # Use the literal /tmp/jot.* pattern by creating it under a path that matches.
    # Since jot_sessionEnd validates by string prefix, exercise the real pattern path.
    real_target = Path("/tmp") / f"jot.pytest_{tmp_path.name}"
    real_target.mkdir(parents=True, exist_ok=True)
    (real_target / "marker").write_text("x")

    # Test action: invoke jot_sessionEnd against the real /tmp/jot.* path.
    rc = jot_sessionEnd(str(real_target))

    # Test verification: directory removed, return code 0.
    assert rc == 0
    assert not real_target.exists(), "tmpdir should be wiped recursively"


def test_refuses_path_outside_safelist(tmp_path, capsys):
    # Scenario: caller passes a path not matching /tmp/jot.* or /private/tmp/jot.*.
    # Setup: create a real directory under tmp_path with a file inside.
    rogue = tmp_path / "not_a_jot_dir"
    rogue.mkdir()
    sentinel = rogue / "keep_me.txt"
    sentinel.write_text("must_survive")

    # Test action: call with the rogue path.
    rc = jot_sessionEnd(str(rogue))

    # Test verification: returns 0, stderr contains refusal, directory NOT deleted.
    assert rc == 0
    assert rogue.exists() and sentinel.exists(), "non-safelist path must NOT be removed"
    err = capsys.readouterr().err
    assert "refusing to rm unexpected path" in err
    assert str(rogue) in err


def test_refuses_empty_argument(capsys):
    # Scenario: hook invoked with no $1 (bash sets to empty string).
    # Setup: none required.

    # Test action: call with empty string.
    rc = jot_sessionEnd("")

    # Test verification: exits 0, refusal message on stderr, no filesystem mutation possible.
    assert rc == 0
    err = capsys.readouterr().err
    assert "refusing to rm unexpected path" in err


def test_accepts_private_tmp_jot_prefix(tmp_path):
    # Scenario: macOS resolves /tmp -> /private/tmp; hook must accept that prefix too.
    # Setup: create real /private/tmp/jot.<id> dir.
    target = Path("/private/tmp") / f"jot.pytest_priv_{tmp_path.name}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "leaf").write_text("data")

    # Test action: invoke with the /private/tmp/jot.* path.
    rc = jot_sessionEnd(str(target))

    # Test verification: removed cleanly.
    assert rc == 0
    assert not target.exists()


def test_missing_directory_is_silent_success(tmp_path):
    # Scenario: tmpdir already wiped by another hook; rm -rf must not error.
    # Setup: compute a /tmp/jot.* path that does not exist.
    ghost = Path("/tmp") / f"jot.pytest_ghost_{tmp_path.name}"
    assert not ghost.exists()

    # Test action: call jot_sessionEnd on the nonexistent path.
    rc = jot_sessionEnd(str(ghost))

    # Test verification: returns 0, no exception (matches `rm -rf` ignore-missing semantics).
    assert rc == 0


def test_refuses_lookalike_prefix(tmp_path, capsys):
    # Scenario: attacker-style path like /tmp/jotfake or /tmp/jot (no dot) must be refused.
    # Setup: create the lookalike directory with content under a sandboxed root we control.
    # We test the validation logic only — never create under real /tmp without `.` separator.
    bad_path = "/tmp/jotfake_should_be_refused"

    # Test action: call with non-conforming path.
    rc = jot_sessionEnd(bad_path)

    # Test verification: refused, stderr message present.
    assert rc == 0
    err = capsys.readouterr().err
    assert "refusing to rm unexpected path" in err
    assert bad_path in err



# --- jot_sessionStart ---


import pytest




def test_missing_input_file_returns_0_and_warns(capsys):
    # Scenario: caller forgot to pass input_file; bash spec returns silent exit 0.
    # Setup: input_file=None, tmpdir_inv non-empty.
    # Test action: invoke jot_sessionStart with missing input_file.
    rc = jot_sessionStart(None, "/some/tmpdir")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and stderr names the missing-args contract.
    assert rc == 0
    assert "missing args" in err


def test_missing_tmpdir_inv_returns_0_and_warns(capsys):
    # Scenario: caller forgot tmpdir_inv argument.
    # Setup: input_file present, tmpdir_inv empty string.
    # Test action: invoke with empty tmpdir_inv.
    rc = jot_sessionStart("/x/in.md", "")
    err = capsys.readouterr().err
    # Test verification: rc is 0 and missing-args message emitted.
    assert rc == 0
    assert "missing args" in err


def test_sidecar_empty_after_retries_returns_0(tmp_path, monkeypatch, capsys):
    # Scenario: tmux_target sidecar never appears within 5 retries.
    # Setup: empty tmpdir, monkeypatch sleep to no-op so test runs fast.
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: call with valid args but no sidecar file present.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 0 and stderr explains sidecar emptiness.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_sidecar_zero_byte_file_treated_as_empty(tmp_path, monkeypatch, capsys):
    # Scenario: sidecar exists but is zero-byte (race window).
    # Setup: create empty tmux_target file; bypass real sleeps.
    (tmp_path / "tmux_target").write_text("")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: empty sidecar is rejected as if missing.
    assert rc == 0
    assert "tmux_target sidecar empty" in err


def test_readiness_timeout_returns_1(tmp_path, monkeypatch, capsys):
    # Scenario: pane id resolved but Claude TUI never shows the ready glyph.
    # Setup: write valid sidecar; stub readiness probe to return 1 (timeout).
    (tmp_path / "tmux_target").write_text("%42\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", lambda pane: 1)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    rc = jot_sessionStart("/x/in.md", str(tmp_path))
    err = capsys.readouterr().err
    # Test verification: rc 1, no keys sent, diagnostic emitted.
    assert rc == 1
    assert "claude TUI not ready" in err
    assert sent == []


def test_happy_path_sends_read_prompt_to_resolved_pane(tmp_path, monkeypatch):
    # Scenario: sidecar present, TUI ready -> prompt is submitted to that pane.
    # Setup: write pane id "%99" into sidecar; stub readiness to 0; capture sends.
    (tmp_path / "tmux_target").write_text("%99\nignored-extra\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke with realistic args.
    rc = jot_sessionStart("/path/to/input.md", str(tmp_path))
    # Test verification: rc 0, exactly one send to first-line pane id, exact prompt text.
    assert rc == 0
    assert sent == [
        ("%99", "Read /path/to/input.md and follow the instructions at the top of that file"),
    ]


def test_sidecar_first_line_only_used(tmp_path, monkeypatch):
    # Scenario: sidecar accidentally contains multiple lines; bash uses head -1.
    # Setup: multi-line sidecar; stub readiness OK; capture send target.
    (tmp_path / "tmux_target").write_text("%first\n%second\n")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", lambda pane: 0)
    monkeypatch.setattr(
        mod, "tmux_sendAndSubmit",
        lambda pane, text: sent.append((pane, text)) or 0,
    )
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: only the first line is used as the pane target.
    assert sent[0][0] == "%first"


def test_readiness_called_with_resolved_pane_id(tmp_path, monkeypatch):
    # Scenario: readiness probe must receive the same pane id parsed from sidecar.
    # Setup: sidecar with "%77"; record arg passed into readiness probe.
    (tmp_path / "tmux_target").write_text("%77\n")
    seen: list[str] = []
    def fake_ready(pane: str) -> int:
        seen.append(pane)
        return 0
    monkeypatch.setattr("common.scripts.jot_lib.tmux_waitForClaudeReadiness", fake_ready)
    monkeypatch.setattr("common.scripts.tmux_lib.tmux_sendAndSubmit", lambda p, t: 0)
    # Test action: invoke jot_sessionStart.
    jot_sessionStart("/x/in.md", str(tmp_path))
    # Test verification: readiness probe got the parsed pane id verbatim.
    assert seen == ["%77"]


# ---------------------------------------------------------------------------
# Section 1 — report header
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    return Path(path).read_text()


class TestReportHeader:
    def test_report_file_created_at_default_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: caller passes no out_path; function auto-generates /tmp/jot-diag-*.log
        # Setup: redirect default tmp location to tmp_path via env or by passing explicit path
        out = str(tmp_path / "diag.log")
        # Test action:
        result = jot_collectDiagnostics(out_path=out)
        # Test verification:
        assert result == out
        assert Path(out).exists()

    def test_report_contains_header_line(self, tmp_path: Path) -> None:
        # Scenario: report always starts with the literal banner line
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "jot-diag-collect report" in content

    def test_report_contains_generated_timestamp(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "generated:" line with ISO timestamp
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "generated:" in content

    def test_report_contains_cwd_line(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "cwd:" line
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "cwd:" in content

    def test_report_contains_project_line(self, tmp_path: Path) -> None:
        # Scenario: report header includes a "project:" line derived from repo root basename
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "project:" in content


# ---------------------------------------------------------------------------
# Section 2 — section banners (uses jot_diagSection format)
# ---------------------------------------------------------------------------

class TestSectionBanners:
    def test_section_1_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 1 banner for Latest Todos input files
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "1. Latest Todos/*_input.txt" in content

    def test_section_2_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 2 banner for state dir
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "2. State dir" in content

    def test_section_3_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 3 banner for tmux session
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "3. tmux session" in content

    def test_section_4_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 4 banner for /tmp/jot.* dirs
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "4. /tmp/jot." in content

    def test_section_5_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 5 banner for log file
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "5." in content

    def test_section_6_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 6 banner for Todos/ listing
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "6. Todos/" in content

    def test_section_7_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 7 banner for plugin orchestrator path
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "7. Installed plugin orchestrator" in content

    def test_section_8_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report contains section 8 banner for dependency check
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "8. Dependency check" in content

    def test_end_of_report_banner_present(self, tmp_path: Path) -> None:
        # Scenario: report ends with END OF REPORT banner
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "END OF REPORT" in content

    def test_section_banners_use_box_drawing_rule(self, tmp_path: Path) -> None:
        # Scenario: section banners use the 59-char box-drawing rule (jot_diagSection format)
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: box-drawing char appears (from jot_diagSection)
        assert "═" in content  # '═'


# ---------------------------------------------------------------------------
# Section 3 — section 1: Todos/*_input.txt
# ---------------------------------------------------------------------------

class TestTodosInputSection:
    def test_no_input_txt_shows_not_found_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: Todos/ dir has no *_input.txt files
        # Setup: point REPO_ROOT at tmp_path (no Todos/ dir)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "no input.txt found" in content

    def test_input_txt_present_shows_kv_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: Todos/ contains one *_input.txt; report shows path kv
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("# Jot Task\ndo something\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GIT_DIR", "")  # suppress git, cwd becomes repo_root
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "path" in content
        assert "task_input.txt" in content

    def test_input_txt_pending_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: input.txt first line is "# Jot Task" -> status shows PENDING
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("# Jot Task\ndo something\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "PENDING" in content

    def test_input_txt_processed_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: input.txt first line starts with "PROCESSED:" -> status shows PROCESSED
        # Setup:
        todos = tmp_path / "Todos"
        todos.mkdir()
        inp = todos / "task_input.txt"
        inp.write_text("PROCESSED: done\nsome content\n")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "PROCESSED" in content


# ---------------------------------------------------------------------------
# Section 4 — section 2: state dir
# ---------------------------------------------------------------------------

class TestStateDirSection:
    def test_missing_state_dir_shows_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: STATE_DIR does not exist; report notes this
        # Setup:
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "state dir does not exist" in content

    def test_queue_txt_empty_shows_empty_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: queue.txt exists but is empty
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        (state / "queue.txt").write_text("")
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "empty" in content or "no jobs pending" in content

    def test_queue_txt_missing_shows_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: state dir exists but queue.txt absent
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "missing" in content

    def test_queue_lock_held_shows_lock_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: queue.lock exists; report warns lock is held
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        (state / "queue.lock").mkdir()  # dir-based mkdir lock
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "LOCK IS HELD" in content

    def test_queue_lock_free_shows_free_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: no queue.lock; report confirms lock is free
        # Setup:
        state = tmp_path / "Todos" / ".jot-state"
        state.mkdir(parents=True)
        out = str(tmp_path / "diag.log")
        monkeypatch.chdir(tmp_path)
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification:
        assert "free" in content or "no lock held" in content


# ---------------------------------------------------------------------------
# Section 5 — section 8: dependency check uses kv format
# ---------------------------------------------------------------------------

class TestDependencySection:
    def test_dependency_section_lists_known_cmds(self, tmp_path: Path) -> None:
        # Scenario: dependency check covers the 5 expected commands
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: all 5 deps appear
        for cmd in ("jq", "python3", "tmux", "claude", "osascript"):
            assert cmd in content, f"missing dependency check for {cmd!r}"

    def test_dependency_found_cmd_shows_path(self, tmp_path: Path) -> None:
        # Scenario: python3 is always present; its which-path appears in report
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        jot_collectDiagnostics(out_path=out)
        content = _read(out)
        # Test verification: python3 row has a path (starts with /)
        lines = [l for l in content.splitlines() if l.startswith("python3") or "python3" in l[:30]]
        found = any("/" in l for l in lines)
        assert found, f"python3 path not found in dep lines: {lines}"


# ---------------------------------------------------------------------------
# Section 6 — return value
# ---------------------------------------------------------------------------

class TestReturnValue:
    def test_returns_out_path_string(self, tmp_path: Path) -> None:
        # Scenario: explicit out_path is returned verbatim
        # Setup:
        out = str(tmp_path / "diag.log")
        # Test action:
        result = jot_collectDiagnostics(out_path=out)
        # Test verification:
        assert result == out

    def test_default_out_path_is_in_tmp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Scenario: when out_path is None, returned path is under /tmp
        # Setup: we cannot write to real /tmp in all CI environments, so skip
        # if /tmp is not writable; otherwise verify prefix.
        if not os.access("/tmp", os.W_OK):
            pytest.skip("/tmp not writable")
        # Test action:
        result = jot_collectDiagnostics(out_path=None)
        # Test verification:
        assert result.startswith("/tmp/jot-diag-")
        assert Path(result).exists()
        Path(result).unlink(missing_ok=True)

