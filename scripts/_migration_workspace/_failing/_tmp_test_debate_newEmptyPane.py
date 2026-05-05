"""RED tests for debate_newEmptyPane (migration of bash `new_empty_pane`).

Bash intent (jot-plugin-orchestrator.sh:2848-2851):
    new_empty_pane() {
      hide_output tmux_retile "$WINDOW_TARGET"
      tmux_new_pane "$WINDOW_TARGET" -c "$CWD" -P -F '#{pane_id}'
    }

Tagged RELAXED_COVERAGE: no paired bash _tests; tests authored from intent.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure the migration workspace is importable so the temp module resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_newEmptyPane import debate_newEmptyPane  # noqa: E402


def test_returns_pane_id_from_split_window_stdout() -> None:
    # Scenario: happy path -- tmux split-window emits a pane id like "%42"
    #   on stdout. The function must return that id (stripped) so callers
    #   (e.g. retry_pane_with_next_model) can address the new pane.
    # Setup: mock subprocess.run to simulate tmux returning rc=0 and "%42\n".
    fake = MagicMock(returncode=0, stdout="%42\n", stderr="")
    with patch("_tmp_debate_newEmptyPane.subprocess.run", return_value=fake) as run, \
         patch("_tmp_debate_newEmptyPane.tmux_retile", return_value=0):
        # Test action: invoke with a window target and cwd.
        pane = debate_newEmptyPane("debate:0", "/tmp/work")
        # Test verification: returned pane id matches stdout, sans newline.
        assert pane == "%42"
        # And the split-window argv carried -c <cwd> -P -F '#{pane_id}'.
        argv = run.call_args[0][0]
        assert argv[:3] == ["tmux", "split-window"]
        assert "-t" in argv and "debate:0" in argv
        assert "-c" in argv and "/tmp/work" in argv
        assert "-P" in argv and "-F" in argv and "#{pane_id}" in argv


def test_calls_tmux_retile_before_split() -> None:
    # Scenario: bash `new_empty_pane` retiles BEFORE splitting so the new
    #   pane lands in a balanced layout. Order matters.
    # Setup: record call order on a shared parent mock.
    parent = MagicMock()
    fake_run = MagicMock(returncode=0, stdout="%9\n", stderr="")
    parent.run.return_value = fake_run
    parent.retile.return_value = 0
    with patch("_tmp_debate_newEmptyPane.subprocess.run", parent.run), \
         patch("_tmp_debate_newEmptyPane.tmux_retile", parent.retile):
        # Test action.
        debate_newEmptyPane("debate:0", "/tmp/x")
    # Test verification: retile was called before subprocess.run (split-window).
    call_names = [c[0] for c in parent.mock_calls if c[0] in ("retile", "run")]
    assert call_names.index("retile") < call_names.index("run")


def test_retiles_the_given_window_target() -> None:
    # Scenario: function must pass through its window_target arg to retile,
    #   not rely on a global WINDOW_TARGET (we are migrating off bash globals).
    # Setup.
    fake = MagicMock(returncode=0, stdout="%1\n", stderr="")
    with patch("_tmp_debate_newEmptyPane.subprocess.run", return_value=fake), \
         patch("_tmp_debate_newEmptyPane.tmux_retile", return_value=0) as retile:
        # Test action.
        debate_newEmptyPane("session-A:2", "/work")
        # Test verification: retile received the same window target.
        retile.assert_called_once_with("session-A:2")


def test_returns_none_when_split_window_fails() -> None:
    # Scenario: tmux split-window failure (rc != 0) must surface as None so
    #   callers can detect the failure. Bash returned non-zero rc; the
    #   Pythonic upgrade is None for "no pane id available".
    # Setup: rc=1, empty stdout, error on stderr.
    fake = MagicMock(returncode=1, stdout="", stderr="can't find session")
    with patch("_tmp_debate_newEmptyPane.subprocess.run", return_value=fake), \
         patch("_tmp_debate_newEmptyPane.tmux_retile", return_value=0):
        # Test action.
        pane = debate_newEmptyPane("nope:0", "/tmp")
        # Test verification.
        assert pane is None


def test_returns_none_when_split_window_emits_empty_pane_id() -> None:
    # Scenario: tmux returned rc=0 but no pane id (degenerate edge); treat
    #   as failure so callers don't proceed with an empty target.
    # Setup.
    fake = MagicMock(returncode=0, stdout="\n", stderr="")
    with patch("_tmp_debate_newEmptyPane.subprocess.run", return_value=fake), \
         patch("_tmp_debate_newEmptyPane.tmux_retile", return_value=0):
        # Test action.
        pane = debate_newEmptyPane("debate:0", "/tmp")
        # Test verification.
        assert pane is None
