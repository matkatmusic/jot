# Workspace temp tests for `jot_sessionEnd`.
# RELAXED_COVERAGE: derived from bash intent/docstring; no paired bash _tests.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_jot_sessionEnd import jot_sessionEnd  # noqa: E402


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
