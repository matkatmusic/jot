"""Behavioral tests for spawn_summary_agent.spawn() — verifies the three
shell-script residues identified in plans/develop-a-plan-for-nested-bengio.md
have been replaced with Python equivalents.

Each test stubs subprocess/threading so no real tmux/claude/osascript runs.
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Repo root is the working tree these tests live in.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _import_spawn_module():
    """Import spawn_summary_agent freshly for each test (avoids stale state)."""
    sys.path.insert(0, str(_REPO_ROOT))
    import importlib
    import common.scripts.plate.spawn_summary_agent as mod
    return importlib.reload(mod)


def _make_baseline_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Setup: ensure spawn() does NOT short-circuit at line 84 / 86.
    monkeypatch.delenv("PLATE_SKIP_LAUNCH", raising=False)
    monkeypatch.delenv("PLATE_LOG_FILE", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin_data"))


def test_spawnSummaryAgent_emitsPythonStopHookCommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the per-invocation settings.json's SessionEnd hook command
    # must invoke the orchestrator's plate-summary-stop argv route via
    # python3 -- not bash plate-summary-stop.sh.
    # Setup: stub shutil.which / subprocess.Popen / threading.Thread / mkdtemp
    # so spawn() runs to completion without launching real processes.
    mod = _import_spawn_module()
    _make_baseline_env(monkeypatch, tmp_path)

    invocation_dir = tmp_path / "plate-summary-spawn"
    invocation_dir.mkdir()
    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda prefix=None: str(invocation_dir))
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=1))
    monkeypatch.setattr(
        mod.threading, "Thread",
        lambda *a, **kw: SimpleNamespace(start=lambda: None),
    )

    # Test action: drive spawn() with concrete args.
    repo = tmp_path / "repo"
    repo.mkdir()
    mod.spawn(
        repo=repo,
        branch="main",
        tip_sha="deadbeefcafebabe",
        transcript_path=str(tmp_path / "transcript.jsonl"),
    )

    # Test verification: read the written settings.json; isolate the
    # SessionEnd hook command; assert it dispatches via python3 -- not bash.
    settings = json.loads((invocation_dir / "settings.json").read_text())
    cmd = settings["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
    parts = shlex.split(cmd)
    assert parts[0] == "python3", f"expected python3 dispatcher, got: {cmd}"
    assert "plate-summary-stop" in parts, f"missing argv route: {cmd}"
    assert ".sh" not in cmd, f"shell script residue remains: {cmd}"


def test_spawnSummaryAgent_launchesPythonWatcherSubprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the fire-and-forget watcher subprocess must be a direct
    # python3 invocation of the orchestrator's plate-summary-watch route,
    # not a bash -c wrapper around plate-summary-watch.sh.
    # Setup: capture every subprocess.Popen call; stub everything else.
    mod = _import_spawn_module()
    _make_baseline_env(monkeypatch, tmp_path)

    invocation_dir = tmp_path / "plate-summary-spawn"
    invocation_dir.mkdir()
    popen_calls: list[list[str]] = []

    def fake_popen(cmd, *args, **kwargs):  # noqa: ARG001
        popen_calls.append(list(cmd))
        return SimpleNamespace(pid=1)

    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda prefix=None: str(invocation_dir))
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        mod.threading, "Thread",
        lambda *a, **kw: SimpleNamespace(start=lambda: None),
    )

    # Test action.
    repo = tmp_path / "repo"
    repo.mkdir()
    mod.spawn(
        repo=repo,
        branch="main",
        tip_sha="deadbeefcafebabe",
        transcript_path=None,
    )

    # Test verification: the SECOND Popen is the watcher (first is tmux
    # new-session). It must start with python3 + the orchestrator path
    # and target the plate-summary-watch route.
    assert len(popen_calls) >= 2, f"watcher Popen missing; saw {popen_calls}"
    watcher_argv = popen_calls[1]
    assert watcher_argv[0] == "python3", f"watcher must run via python3: {watcher_argv}"
    assert "plate-summary-watch" in watcher_argv, f"missing route: {watcher_argv}"
    assert not any(arg.endswith(".sh") for arg in watcher_argv), (
        f"shell-script residue in watcher argv: {watcher_argv}"
    )
    # Test verification: there are EXACTLY two Popen calls (tmux + watcher).
    # The terminal call has been moved off subprocess into a daemon thread.
    assert len(popen_calls) == 2, (
        f"expected exactly two Popen calls (tmux + watcher); saw {popen_calls}"
    )


def test_spawnSummaryAgent_callsTerminalSpawnInDaemonThread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the terminal-window auto-attach must be a direct call to
    # util_lib.terminal_spawnIfNeeded inside a daemon=True threading.Thread,
    # not a bash -c subprocess that sources platform.sh.
    # Setup: capture Thread construction kwargs + .start() invocation;
    # capture terminal_spawnIfNeeded calls when the thread target is run.
    mod = _import_spawn_module()
    _make_baseline_env(monkeypatch, tmp_path)

    invocation_dir = tmp_path / "plate-summary-spawn"
    invocation_dir.mkdir()
    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda prefix=None: str(invocation_dir))
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=1))

    terminal_calls: list[tuple] = []

    def fake_terminal(session, log_file, log_prefix, maximize):
        terminal_calls.append((session, log_file, log_prefix, maximize))
        return 0

    monkeypatch.setattr(mod, "terminal_spawnIfNeeded", fake_terminal)

    thread_records: list[dict] = []

    class FakeThread:
        def __init__(self, *args, target=None, daemon=None, **kwargs):
            thread_records.append({
                "target": target,
                "daemon": daemon,
                "args": args,
                "kwargs": kwargs,
                "started": False,
            })

        def start(self):
            thread_records[-1]["started"] = True

    monkeypatch.setattr(mod.threading, "Thread", FakeThread)

    # Test action.
    repo = tmp_path / "repo"
    repo.mkdir()
    mod.spawn(
        repo=repo,
        branch="main",
        tip_sha="deadbeefcafebabe",
        transcript_path=None,
    )

    # Test verification: exactly one Thread was constructed with daemon=True
    # and .start() was called.
    assert len(thread_records) == 1, f"expected one Thread; saw {thread_records}"
    rec = thread_records[0]
    assert rec["daemon"] is True, f"thread must be daemon=True; got {rec}"
    assert rec["started"] is True, "thread.start() not called"
    assert callable(rec["target"]), "Thread target must be callable"

    # Test verification: invoking the captured target calls terminal_spawnIfNeeded
    # with the spawn's session_name and log args (no shell hop).
    rec["target"]()
    assert len(terminal_calls) == 1, f"terminal_spawnIfNeeded not invoked; saw {terminal_calls}"
    session_arg, _log_arg, prefix_arg, maximize_arg = terminal_calls[0]
    assert session_arg.startswith("plate-summary-"), f"unexpected session: {session_arg}"
    assert prefix_arg == "plate"
    assert maximize_arg == "compact"
