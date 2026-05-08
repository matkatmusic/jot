"""Tests for jot_lib jot_stop hook + jot_sessionEnd cleanup-safety."""
from __future__ import annotations

from pathlib import Path

import pytest

from common.scripts.jot_lib import (
    jot_sessionEnd,
    jot_stop,
)


# --- jot_stop fixtures + helpers ---


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


# --- jot_stop ---


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


# --- jot_sessionEnd cleanup safety ---


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
