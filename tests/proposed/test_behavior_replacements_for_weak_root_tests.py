from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.scripts import debate_lib
from common.scripts import jot_lib
from common.scripts import util_lib


def runDebateLaunchWithInjectedPlatform(
    monkeypatch: pytest.MonkeyPatch,
    *,
    is_darwin: bool,
) -> tuple[list[str], list[str]]:
    plugin_root = Path("/plugin/root")
    monkeypatch.delenv("PLUGIN_ROOT", raising=False)
    terminal_events: list[str] = []
    main_events: list[str] = []

    def terminalIsRunning() -> bool:
        terminal_events.append("probe")
        return True

    def launchTerminal() -> None:
        terminal_events.append("launch")

    def debateMain() -> None:
        main_events.append(os.environ["PLUGIN_ROOT"])

    debate_lib.debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=plugin_root,
        _debate_main_fn=debateMain,
        _is_darwin=is_darwin,
        _terminal_running_fn=terminalIsRunning,
        _launch_terminal_fn=launchTerminal,
    )
    return main_events, terminal_events


# Replaces tests/test_debate_main.py::test_always_calls_debate_main
def test_debate_launch_exports_plugin_root_and_delegates_on_non_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: debate_launch resolves launch context, exports PLUGIN_ROOT, and
    # delegates to debate_main on the non-Darwin path.
    # Setup: clear any inherited PLUGIN_ROOT and inject non-spawning terminal
    # functions so the behavior is deterministic.
    # Test action: launch debate orchestration.
    main_events, terminal_events = runDebateLaunchWithInjectedPlatform(
        monkeypatch,
        is_darwin=False,
    )

    # Test verification: main was called with exported plugin root in place,
    # and the terminal probe did not run on non-Darwin.
    assert main_events == ["/plugin/root"]
    assert terminal_events == []


# Replaces tests/test_debate_main.py::test_always_calls_debate_main
def test_debate_launch_exports_plugin_root_and_delegates_on_darwin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: debate_launch resolves launch context, exports PLUGIN_ROOT, and
    # delegates to debate_main on the Darwin path when Terminal is running.
    # Setup: clear any inherited PLUGIN_ROOT and inject non-spawning terminal
    # functions so the behavior is deterministic.
    # Test action: launch debate orchestration.
    main_events, terminal_events = runDebateLaunchWithInjectedPlatform(
        monkeypatch,
        is_darwin=True,
    )

    # Test verification: main was called with exported plugin root in place,
    # and the Darwin terminal probe ran.
    assert main_events == ["/plugin/root"]
    assert terminal_events == ["probe"]


# Replaces tests/test_util_terminal.py::test_darwin_terminal_not_running_launches_terminal
def test_terminal_launchBackground_spawns_osascript_launch_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Scenario: the low-level Terminal launch helper should start osascript
    # with the actual AppleScript launch command.
    # Setup: capture Popen arguments without launching a GUI process.
    popen_calls: list[tuple] = []

    def fakePopen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(util_lib.subprocess, "Popen", fakePopen)

    # Test action: invoke the launch helper.
    util_lib._terminal_launchBackground()

    # Test verification: osascript is launched fire-and-forget with output
    # suppressed.
    args, kwargs = popen_calls[0]
    assert args[0] == ["osascript", "-e", 'tell application "Terminal" to launch']
    assert kwargs["stdout"] is util_lib.subprocess.DEVNULL
    assert kwargs["stderr"] is util_lib.subprocess.DEVNULL


# Replaces tests/test_jot_diag.py::TestDependencySection::test_dependency_section_lists_known_cmds
def test_jot_collectDiagnostics_dependency_section_reports_each_dependency_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the dependency section should report each dependency as a
    # keyed row with either a resolved path or NOT FOUND.
    # Setup: patch shutil.which so every dependency has a deterministic status.
    dependency_paths = {
        "jq": "/bin/jq",
        "python3": "/usr/bin/python3",
        "tmux": None,
        "claude": "/usr/local/bin/claude",
        "osascript": None,
    }

    monkeypatch.setattr(jot_lib.shutil, "which", lambda command: dependency_paths[command])

    # Test action: collect diagnostics into a file.
    out_path = jot_lib.jot_collectDiagnostics(str(tmp_path / "diag.log"))
    report = Path(out_path).read_text()

    # Test verification: every dependency row includes the expected status.
    assert "jq" in report and "/bin/jq" in report
    assert "python3" in report and "/usr/bin/python3" in report
    assert "tmux" in report and "NOT FOUND" in report
    assert "claude" in report and "/usr/local/bin/claude" in report
    assert "osascript" in report and "NOT FOUND" in report


# Replaces tests/test_debate_capacity.py::test_result_is_list_type
def test_debate_agentErrorMarkers_returns_independent_marker_list_per_call() -> None:
    # Scenario: callers may iterate or manipulate one marker list without
    # mutating future marker lookups.
    # Setup: get the codex marker list and mutate the returned object.
    first_result = debate_lib.debate_agentErrorMarkers("codex")
    first_result.append("caller-local marker")

    # Test action: ask for codex markers again.
    second_result = debate_lib.debate_agentErrorMarkers("codex")

    # Test verification: the second lookup returns the canonical markers only.
    assert second_result == ["Selected model is at capacity", "model is overloaded"]
