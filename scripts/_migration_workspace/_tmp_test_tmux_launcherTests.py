"""Migration tests for bash `tmux_launcher_tests` (TEST tag).

Ports each PASS/FAIL assertion in the bash function to one pytest test.
Each test exercises real tmux via @pytest.mark.live; functions-under-test
(`tmux_ensureSession`, `tmux_splitWorkerPane`, `tmux_ensureKeepalivePane`)
are migrated in parallel and exposed via `from jot_plugin_orchestrator import *`.
"""

import os
import sys
import subprocess
import pytest

# Make the production module importable from the workspace temp file.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jot_plugin_orchestrator import *  # noqa: F401,F403


# ---------- helpers ----------

def _tmux_has_session(name: str) -> bool:
    # Setup helper: shell out to real tmux to check session existence.
    r = subprocess.run(
        ["tmux", "has-session", "-t", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def _tmux_window_exists(session: str, window: str) -> bool:
    # Setup helper: list windows and grep for an exact name match.
    r = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return False
    return window in r.stdout.splitlines()


def _tmux_pane_has_title(target: str, title: str) -> bool:
    # Setup helper: query pane_title via display-message.
    r = subprocess.run(
        ["tmux", "display-message", "-p", "-t", target, "#{pane_title}"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == title


def _tmux_show_option(target: str, opt: str) -> str:
    # Setup helper: read tmux option value, empty string on miss.
    r = subprocess.run(
        ["tmux", "show-options", "-t", target, "-v", opt],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def _kill(name: str) -> None:
    # Teardown helper: best-effort session kill.
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.fixture
def tmux_session():
    # Provide a unique session name and clean up after the test.
    name = f"tmux-sh-launcher-test-{os.getpid()}"
    _kill(name)
    yield name
    _kill(name)


# ---------- tests ----------

@pytest.mark.live
def test_ensure_session_creates_new_session(tmux_session):
    # Scenario: ensure_session on a missing session creates it (Path 1).
    # Setup: session name guaranteed absent by fixture.
    # Test action: invoke tmux_ensureSession with main window + keepalive.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test verification: tmux now reports the session exists.
    assert _tmux_has_session(tmux_session)


@pytest.mark.live
def test_ensure_session_sets_keepalive_pane_title(tmux_session):
    # Scenario: keepalive pane created by ensure_session has the requested title.
    # Setup: create the session via ensure_session.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: read pane_title for main window.
    # Test verification: title equals "keepalive".
    assert _tmux_pane_has_title(f"{tmux_session}:main", "keepalive")


@pytest.mark.live
def test_ensure_session_applies_pane_border_status_top(tmux_session):
    # Scenario: ensure_session sets pane-border-status=top via set_option_t.
    # Setup: create session.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: read tmux option.
    border = _tmux_show_option(tmux_session, "pane-border-status")
    # Test verification: option is "top".
    assert border == "top"


@pytest.mark.live
def test_split_worker_pane_returns_pane_id(tmux_session):
    # Scenario: split_worker_pane creates a pane and returns its %id.
    # Setup: ensure session exists first.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: split a worker pane in main window.
    worker = tmux_splitWorkerPane(f"{tmux_session}:main", "/tmp", "sleep 30")
    # Test verification: returned id is non-empty and starts with '%'.
    assert worker
    assert str(worker).startswith("%")


@pytest.mark.live
def test_ensure_session_idempotent_on_existing_session(tmux_session):
    # Scenario: re-calling ensure_session on existing session+window is a no-op (Path 3).
    # Setup: create session once.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test action: call ensure_session a second time with same args.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    # Test verification: session still exists, not destroyed by second call.
    assert _tmux_has_session(tmux_session)


@pytest.mark.live
def test_ensure_session_adds_new_window_to_existing_session(tmux_session):
    # Scenario: ensure_session on existing session with new window name adds the window (Path 2).
    # Setup: create session with main window.
    tmux_ensureSession(tmux_session, "main", "/tmp", "sleep 30", "keepalive")
    second = f"secondwin-{os.getpid()}"
    # Test action: call ensure_session with a different window name.
    tmux_ensureSession(tmux_session, second, "/tmp", "sleep 30", "keepalive-2")
    # Test verification: new window now present in the session.
    assert _tmux_window_exists(tmux_session, second)
