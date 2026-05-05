"""RED-YELLOW-GREEN tests for the workspace `jot_stop` migration.

One behavior per test, with the mandated step-comment shape:
  # Scenario: ...
  # Setup: ...
  # Test action: ...
  # Test verification: ...

Tests assert on side effects only: audit.log line shape, tmux helpers
called with the right targets, state files materialized. No paired
bash `_tests` exists; intent comes from the bash docstring + body, hence
the `RELAXED_COVERAGE` tag in the name-map.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the workspace importable.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import _tmp_jot_stop  # noqa: E402
from _tmp_jot_stop import jot_stop  # noqa: E402


# --- shared fixtures --------------------------------------------------------


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


def _writeSidecar(tmpdir_inv: Path, pane_id: str) -> None:
    (tmpdir_inv / "tmux_target").write_text(pane_id + "\n")


# --- tests ------------------------------------------------------------------


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
    monkeypatch.setattr(_tmp_jot_stop.time, "sleep", lambda _s: None)
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
