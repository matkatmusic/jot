"""Behavioral tests for spawn_summary_agent.spawn() — verifies the three
shell-script residues identified in plans/develop-a-plan-for-nested-bengio.md
have been replaced with Python equivalents.

Each test stubs subprocess and terminal_spawnIfNeeded so no real
tmux/claude/osascript runs.
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


def _stub_bg_loader(monkeypatch: pytest.MonkeyPatch, mod) -> None:
    # Stub bgPermissions_loadClaude on the spawn_summary_agent module so
    # spawn() does not need a real CLAUDE_PLUGIN_ROOT/bundle to run; the
    # returned static-allow array stands in for the JSON-bundled plate floor.
    def fake_loader(tool, *, env, extra_allow=None, bundle_path=None, log_file=None):
        # Echo a minimal static floor so callers can still see Bash git/text rules
        # plus the extra_allow merge.
        static = ["Bash(git log:*)", "Bash(rtk git log:*)", "Bash(grep:*)", "Bash(rtk grep:*)"]
        return json.dumps(static + list(extra_allow or []))

    monkeypatch.setattr(mod, "bgPermissions_loadClaude", fake_loader)


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
    _stub_bg_loader(monkeypatch, mod)

    invocation_dir = tmp_path / "plate-summary-spawn"
    invocation_dir.mkdir()
    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda prefix=None: str(invocation_dir))
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=1))
    monkeypatch.setattr(mod, "terminal_spawnIfNeeded", lambda *a, **kw: 0)

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
    _stub_bg_loader(monkeypatch, mod)

    invocation_dir = tmp_path / "plate-summary-spawn"
    invocation_dir.mkdir()
    popen_calls: list[tuple[list[str], dict]] = []

    def fake_popen(cmd, *args, **kwargs):  # noqa: ARG001
        popen_calls.append((list(cmd), dict(kwargs)))
        return SimpleNamespace(pid=1)

    monkeypatch.setattr(mod.tempfile, "mkdtemp", lambda prefix=None: str(invocation_dir))
    monkeypatch.setattr(mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mod, "terminal_spawnIfNeeded", lambda *a, **kw: 0)

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
    watcher_argv, watcher_kwargs = popen_calls[1]
    assert watcher_argv[0] == "python3", f"watcher must run via python3: {watcher_argv}"
    assert "plate-summary-watch" in watcher_argv, f"missing route: {watcher_argv}"
    assert not any(arg.endswith(".sh") for arg in watcher_argv), (
        f"shell-script residue in watcher argv: {watcher_argv}"
    )
    # Test verification: watcher must detach from the hook's process group
    # via start_new_session=True. Without this, /plate's UserPromptSubmit
    # hook reaping delivers SIGHUP to the watcher before its first poll
    # and the tmux pane stays alive forever (the bug fix-plate-bugs fixes).
    assert watcher_kwargs.get("start_new_session") is True, (
        f"watcher Popen must set start_new_session=True; saw kwargs={watcher_kwargs}"
    )
    # Test verification: there are EXACTLY two Popen calls (tmux + watcher).
    # terminal_spawnIfNeeded is stubbed; its osascript Popen does not count.
    assert len(popen_calls) == 2, (
        f"expected exactly two Popen calls (tmux + watcher); saw {popen_calls}"
    )


def test_spawnSummaryAgent_callsTerminalSpawnInline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the terminal-window auto-attach must be a direct, inline
    # call to util_lib.terminal_spawnIfNeeded -- NOT wrapped in a daemon
    # thread or a bash -c subprocess. terminal_spawnIfNeeded is itself
    # non-blocking (Popen osascript with start_new_session=True), so the
    # earlier daemon-thread wrapper is unnecessary AND dangerous: when
    # spawn() is reached via a UserPromptSubmit hook the orchestrator
    # process exits within milliseconds, killing the daemon thread before
    # it ever reaches the Popen call.
    # Setup: capture terminal_spawnIfNeeded invocations directly.
    mod = _import_spawn_module()
    _make_baseline_env(monkeypatch, tmp_path)
    _stub_bg_loader(monkeypatch, mod)

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

    # Test action.
    repo = tmp_path / "repo"
    repo.mkdir()
    mod.spawn(
        repo=repo,
        branch="main",
        tip_sha="deadbeefcafebabe",
        transcript_path=None,
    )

    # Test verification: terminal_spawnIfNeeded was invoked exactly once
    # synchronously during spawn() with the per-invocation session_name
    # and the documented prefix/maximize args.
    assert len(terminal_calls) == 1, f"terminal_spawnIfNeeded not invoked; saw {terminal_calls}"
    session_arg, _log_arg, prefix_arg, maximize_arg = terminal_calls[0]
    assert session_arg.startswith("plate-summary-"), f"unexpected session: {session_arg}"
    assert prefix_arg == "plate"
    assert maximize_arg == "compact"


def test_spawnSummaryAgent_doesNotImportThreading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the daemon-thread wrapper around terminal_spawnIfNeeded
    # was the bug; once removed, the threading import should also be
    # gone so a future regression that re-introduces the wrapper fails
    # at import time.
    mod = _import_spawn_module()
    # Test verification: module exposes no threading attribute.
    assert not hasattr(mod, "threading"), (
        "spawn_summary_agent must not import threading; "
        "the daemon-thread wrapper around terminal_spawnIfNeeded was the bug"
    )
