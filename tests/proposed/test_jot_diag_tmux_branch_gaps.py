from __future__ import annotations

from pathlib import Path

import pytest

from common.scripts import jot_lib


# Replaces tests/test_jot_diag.py::TestSectionBanners::test_section_3_banner_present
def test_jot_collectDiagnostics_reports_tmux_details_when_jot_session_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: the jot tmux session exists while diagnostics are collected.
    # Setup: force the tmux-session branch and return deterministic output for
    # every tmux command used by section 3.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(jot_lib, "_tmux_session_exists", lambda session: session == "jot")

    tmux_outputs = {
        ("list-sessions",): "jot: 1 windows",
        ("list-windows", "-t", "jot"): "0: jots",
        (
            "list-panes",
            "-t",
            "jot:jots",
            "-F",
            "#{pane_id} pid=#{pane_pid} dead=#{pane_dead} deadstatus=#{pane_dead_status} cmd=#{pane_current_command}",
        ): "%1 pid=123 dead=0 deadstatus=0 cmd=claude",
        ("display-message", "-t", "jot:jots", "-p", "start: #{pane_start_command}"): "start: claude",
        ("list-clients", "-t", "jot"): "/dev/ttys001",
        ("capture-pane", "-p", "-t", "jot:jots", "-S", "-80"): "pane text",
    }
    observed_commands: list[tuple[str, ...]] = []

    def fakeTmuxRun(*args: str) -> str:
        observed_commands.append(tuple(args))
        return tmux_outputs[tuple(args)]

    monkeypatch.setattr(jot_lib, "_tmux_run", fakeTmuxRun)

    # Test action: collect the diagnostic report.
    out_path = jot_lib.jot_collectDiagnostics(str(tmp_path / "diag.log"))
    report = Path(out_path).read_text()

    # Test verification: each tmux subsection includes the command output.
    assert "jot: 1 windows" in report
    assert "0: jots" in report
    assert "%1 pid=123" in report
    assert "start: claude" in report
    assert "/dev/ttys001" in report
    assert "pane text" in report
    assert set(observed_commands) == set(tmux_outputs)
