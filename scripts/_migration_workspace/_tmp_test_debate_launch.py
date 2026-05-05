"""
Tests for debate_launch (workspace TDD).

RELAXED_COVERAGE: no paired bash _tests exist; tests authored from
intent + docstring. All upstream callees mocked at module boundary.

Test shape: one behavior per test, with required section comments.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# sys.path: allow running from repo root or workspace directly.
# ---------------------------------------------------------------------------
_WORKSPACE = Path(__file__).resolve().parent
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from _tmp_debate_launch import debate_launch  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop() -> None:
    pass


def _make_main_mock() -> MagicMock:
    return MagicMock(return_value=None)


# ===========================================================================
# 1. Always calls debate_main
# ===========================================================================

def test_always_calls_debate_main() -> None:
    # Scenario: debate_launch always delegates to debate_main regardless of OS.
    # Setup:
    main_mock = _make_main_mock()
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=lambda: True,
        _launch_terminal_fn=_noop,
    )
    # Test verification:
    main_mock.assert_called_once_with()


# ===========================================================================
# 2. Darwin + Terminal NOT running -> launches Terminal then calls debate_main
# ===========================================================================

def test_darwin_terminal_not_running_launches_terminal() -> None:
    # Scenario: on Darwin, when Terminal is not running, osascript is invoked.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running = lambda: False
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=terminal_running,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    launch_mock.assert_called_once_with()
    main_mock.assert_called_once_with()


# ===========================================================================
# 3. Darwin + Terminal already running -> skips launch
# ===========================================================================

def test_darwin_terminal_already_running_skips_launch() -> None:
    # Scenario: on Darwin, when Terminal is already running, do NOT launch it.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running = lambda: True
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=terminal_running,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    launch_mock.assert_not_called()
    main_mock.assert_called_once_with()


# ===========================================================================
# 4. Non-Darwin -> never launches Terminal regardless of pgrep result
# ===========================================================================

def test_non_darwin_never_launches_terminal() -> None:
    # Scenario: on non-Darwin (Linux/CI), Terminal.app guard is skipped entirely.
    # Setup:
    main_mock = _make_main_mock()
    launch_mock = MagicMock()
    terminal_running_mock = MagicMock(return_value=False)
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=terminal_running_mock,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    terminal_running_mock.assert_not_called()
    launch_mock.assert_not_called()
    main_mock.assert_called_once_with()


# ===========================================================================
# 5. PLUGIN_ROOT exported to environment
# ===========================================================================

def test_plugin_root_exported_to_environment() -> None:
    # Scenario: debate_launch sets PLUGIN_ROOT env var so debate_main sees it.
    # Setup:
    import os
    plugin_root = Path("/my/plugin/root")
    main_mock = _make_main_mock()
    # Remove any pre-existing value so setdefault fires.
    os.environ.pop("PLUGIN_ROOT", None)
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=plugin_root,
        _debate_main_fn=main_mock,
        _is_darwin=False,
        _terminal_running_fn=lambda: True,
        _launch_terminal_fn=_noop,
    )
    # Test verification:
    assert os.environ.get("PLUGIN_ROOT") == str(plugin_root)


# ===========================================================================
# 6. Terminal launch is fire-and-forget (does NOT block debate_main)
# ===========================================================================

def test_terminal_launch_before_debate_main() -> None:
    # Scenario: Terminal is launched BEFORE debate_main is called (ordering).
    # Setup:
    call_order: list[str] = []
    main_mock = MagicMock(side_effect=lambda: call_order.append("main"))
    launch_mock = MagicMock(side_effect=lambda: call_order.append("launch"))
    # Test action:
    debate_launch(
        scripts_dir=Path("/fake/scripts"),
        plugin_root=Path("/fake/plugin"),
        _debate_main_fn=main_mock,
        _is_darwin=True,
        _terminal_running_fn=lambda: False,
        _launch_terminal_fn=launch_mock,
    )
    # Test verification:
    assert call_order == ["launch", "main"], (
        f"Expected launch before main, got: {call_order}"
    )
