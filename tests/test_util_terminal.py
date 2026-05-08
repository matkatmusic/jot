from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common.scripts.debate_lib import debate_launch
from common.scripts import util_lib as mod
from common.scripts.util_lib import terminal_spawnIfNeeded


# --- terminal_spawnIfNeeded ---

def test_terminal_spawnIfNeeded_empty_session_raises_value_error():
    # Scenario: caller forgets the required session arg.
    # Test action + verification: ValueError surfaces.
    with pytest.raises(ValueError):
        terminal_spawnIfNeeded("")


def test_terminal_spawnIfNeeded_skips_spawn_when_clients_attached():
    # Scenario: tmux session already has an attached client.
    # Setup: stub tmux list to return a non-empty client line.
    with patch.object(mod, "_terminal_listTmuxClients", return_value="/dev/ttys001 ...\n"), \
         patch.object(mod.subprocess, "Popen") as popen, \
         patch.object(mod.sys, "platform", "darwin"):
        # Test action: call function on darwin.
        rc = terminal_spawnIfNeeded("sess1")
    # Test verification: osascript is not spawned and success is returned.
    assert rc == 0
    popen.assert_not_called()


def test_terminal_spawnIfNeeded_darwin_spawns_osascript_with_attach_command():
    # Scenario: no clients attached, osascript present, darwin host.
    # Setup: stub list_clients empty, which() finds osascript, mock Popen.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(mod, "_terminal_listTmuxClients", return_value=""), \
         patch.object(mod.shutil, "which", return_value="/usr/bin/osascript"), \
         patch.object(mod.sys, "platform", "darwin"), \
         patch.object(mod.subprocess, "Popen", return_value=fake_proc) as popen:
        # Test action: call with default maximize="".
        rc = terminal_spawnIfNeeded("mySess")
    # Test verification: Popen called with osascript; script contains attach command and no maximize block.
    assert rc == 0
    args, _kwargs = popen.call_args
    assert args[0] == ["osascript"]
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "tmux attach -t mySess" in sent
    assert "set bounds of front window" not in sent


def test_terminal_spawnIfNeeded_darwin_maximize_yes_includes_full_desktop_block():
    # Scenario: caller requests maximize="yes" for a large pane layout.
    # Setup: use darwin happy-path stubs.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(mod, "_terminal_listTmuxClients", return_value=""), \
         patch.object(mod.shutil, "which", return_value="/x/osascript"), \
         patch.object(mod.sys, "platform", "darwin"), \
         patch.object(mod.subprocess, "Popen", return_value=fake_proc):
        # Test action: invoke with maximize="yes".
        terminal_spawnIfNeeded("s", "/dev/null", "tmux", "yes")
    # Test verification: AppleScript stdin contains full-screen bounds assignment.
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "set bounds of front window to screenBounds" in sent
    assert "winW to 1000" not in sent


def test_terminal_spawnIfNeeded_darwin_maximize_compact_includes_centred_1000x700_block():
    # Scenario: caller requests compact geometry for a single-pane spawner.
    # Setup: use darwin happy-path stubs.
    fake_proc = MagicMock()
    fake_proc.communicate.return_value = (b"", b"")
    with patch.object(mod, "_terminal_listTmuxClients", return_value=""), \
         patch.object(mod.shutil, "which", return_value="/x/osascript"), \
         patch.object(mod.sys, "platform", "darwin"), \
         patch.object(mod.subprocess, "Popen", return_value=fake_proc):
        # Test action: invoke with maximize="compact".
        terminal_spawnIfNeeded("s", "/dev/null", "tmux", "compact")
    # Test verification: stdin includes 1000x700 centering math.
    sent = fake_proc.communicate.call_args.kwargs["input"].decode("utf-8")
    assert "winW to 1000" in sent
    assert "winH to 700" in sent


def test_terminal_spawnIfNeeded_darwin_missing_osascript_writes_advisory_and_returns_zero(tmp_path):
    # Scenario: darwin host but osascript binary is not on PATH.
    # Setup: which() returns None; real tmp log file.
    log = tmp_path / "spawn.log"
    with patch.object(mod, "_terminal_listTmuxClients", return_value=""), \
         patch.object(mod.shutil, "which", return_value=None), \
         patch.object(mod.sys, "platform", "darwin"), \
         patch.object(mod.subprocess, "Popen") as popen:
        # Test action: invoke with log_file pointing at tmp file.
        rc = terminal_spawnIfNeeded("abc", str(log), "myprefix")
    # Test verification: Popen never called, advisory line appended.
    assert rc == 0
    popen.assert_not_called()
    text = log.read_text()
    assert "myprefix: osascript unavailable" in text
    assert "tmux attach -t abc" in text


def test_terminal_spawnIfNeeded_non_darwin_writes_advisory_and_does_not_spawn(tmp_path):
    # Scenario: linux host invokes the spawner.
    # Setup: sys.platform stubbed to linux; real tmp log file.
    log = tmp_path / "spawn.log"
    with patch.object(mod, "_terminal_listTmuxClients", return_value=""), \
         patch.object(mod.sys, "platform", "linux"), \
         patch.object(mod.subprocess, "Popen") as popen:
        # Test action: invoke with custom log_prefix.
        rc = terminal_spawnIfNeeded("zzz", str(log), "plate")
    # Test verification: Popen never called, advisory contains non-Darwin.
    assert rc == 0
    popen.assert_not_called()
    text = log.read_text()
    assert "plate: non-Darwin host" in text
    assert "tmux attach -t zzz" in text


def test_terminal_spawnIfNeeded_dev_null_log_does_not_create_file(tmp_path, monkeypatch):
    # Scenario: caller passes default /dev/null log on non-darwin.
    # Setup: cwd switched to tmp_path so any accidental write would land here.
    monkeypatch.chdir(tmp_path)
    with patch.object(mod, "_terminal_listTmuxClients", return_value=""), \
         patch.object(mod.sys, "platform", "linux"):
        # Test action: invoke with log_file="/dev/null".
        rc = terminal_spawnIfNeeded("s", "/dev/null", "tmux")
    # Test verification: no spurious files created in cwd; rc 0.
    assert rc == 0
    assert list(tmp_path.iterdir()) == []


def test_terminal_spawnIfNeeded_advisory_write_failure_is_swallowed():
    # Scenario: log file path is unwritable.
    # Setup: monkeypatch open() to raise OSError.
    with patch.object(mod, "_terminal_listTmuxClients", return_value=""), \
         patch.object(mod.sys, "platform", "linux"), \
         patch("builtins.open", side_effect=OSError("EACCES")):
        # Test action + verification: function returns 0, no exception escapes.
        assert terminal_spawnIfNeeded("s", "/some/real/path.log", "tmux") == 0


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


def _noop() -> None:
    pass


def _make_main_mock() -> MagicMock:
    return MagicMock(return_value=None)

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
