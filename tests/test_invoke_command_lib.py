"""Spec-based tests for common/scripts/invoke_command_lib.py.

Tests assert against the function's CONTRACT (combined stream capture,
caller-tagged error format, rc=127 on missing program), not against the
bash original's exact byte stream. The bash version's `$*` argv-render
in errors is a workaround we replace with shlex.join.
"""
from __future__ import annotations

import shlex

import pytest

from invoke_command_lib import invokeCommand


# ── Success path ──────────────────────────────────────────────────────


def test_success_with_output_prints_to_stdout(capsys: pytest.CaptureFixture):
    rc = invokeCommand("c", ["echo", "hello"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "hello\n"
    assert captured.err == ""


def test_success_with_no_output_is_silent(capsys: pytest.CaptureFixture):
    rc = invokeCommand("c", ["true"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""


def test_success_output_has_single_trailing_newline(capsys: pytest.CaptureFixture):
    """Even if the program emits no trailing newline, the wrapper adds one."""
    rc = invokeCommand("c", ["printf", "no-newline"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "no-newline\n"


# ── Failure path ──────────────────────────────────────────────────────


def test_failure_writes_caller_tagged_error_to_stderr(
    capsys: pytest.CaptureFixture,
):
    rc = invokeCommand("my_caller", ["false"])
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.out == ""
    assert captured.err.startswith("[my_caller] command ")
    assert " failed:" in captured.err


def test_failure_returns_underlying_exit_code(
    capsys: pytest.CaptureFixture,
):
    rc = invokeCommand("c", ["sh", "-c", "exit 42"])
    capsys.readouterr()  # discard
    assert rc == 42


# ── Stream combination ────────────────────────────────────────────────


def test_combined_stdout_and_stderr_capture_on_success(
    capsys: pytest.CaptureFixture,
):
    """A program writing to both streams is captured as one combined output."""
    rc = invokeCommand("c", ["sh", "-c", "echo OUT; echo ERR >&2; exit 0"])
    captured = capsys.readouterr()
    assert rc == 0
    # Combined output appears on stdout (since rc==0, success path prints
    # the captured combined stream). Order may not be strictly guaranteed
    # by the shell but both lines must be present.
    assert "OUT" in captured.out
    assert "ERR" in captured.out


def test_combined_streams_appear_in_failure_message(
    capsys: pytest.CaptureFixture,
):
    """On failure, both streams are combined and embedded in the error."""
    rc = invokeCommand(
        "c", ["sh", "-c", "echo OUT; echo ERR >&2; exit 7"]
    )
    captured = capsys.readouterr()
    assert rc == 7
    assert "OUT" in captured.err
    assert "ERR" in captured.err


# ── Missing program ───────────────────────────────────────────────────


def test_missing_program_returns_127(capsys: pytest.CaptureFixture):
    rc = invokeCommand("c", ["definitely_not_a_real_command_xyz"])
    capsys.readouterr()
    assert rc == 127


def test_missing_program_writes_caller_tagged_error(
    capsys: pytest.CaptureFixture,
):
    rc = invokeCommand("my_caller", ["definitely_not_a_real_command_xyz"])
    captured = capsys.readouterr()
    assert rc == 127
    assert captured.err.startswith("[my_caller] command ")
    assert "definitely_not_a_real_command_xyz" in captured.err


# ── Caller-name plumbing ──────────────────────────────────────────────


def test_caller_name_round_trips_into_error_prefix(
    capsys: pytest.CaptureFixture,
):
    invokeCommand("uniquename123", ["false"])
    captured = capsys.readouterr()
    assert "[uniquename123]" in captured.err


# ── Argv quoting in error message (improvement vs bash $*) ────────────


def test_argv_with_spaces_is_shell_quoted_in_error(
    capsys: pytest.CaptureFixture,
):
    """Bash original used $* (loses quoting); Python uses shlex.join (preserves)."""
    invokeCommand("c", ["sh", "-c", "exit 1", "_arg with spaces_"])
    captured = capsys.readouterr()
    # The argv should appear shell-quoted - shlex.join wraps the spaced arg.
    expected_quoted = shlex.join(
        ["sh", "-c", "exit 1", "_arg with spaces_"]
    )
    assert expected_quoted in captured.err


def test_argv_with_single_quote_is_shell_safe_in_error(
    capsys: pytest.CaptureFixture,
):
    """Round-trip the quoted argv string through shlex.split to recover argv."""
    weird = "has'apostrophe"
    invokeCommand("c", ["sh", "-c", "exit 1", weird])
    captured = capsys.readouterr()
    # Extract the quoted-command portion and verify it shlex-parses back.
    # Format: "[c] command <quoted> failed: ..."
    after_command = captured.err.split("command ", 1)[1]
    quoted = after_command.split(" failed:", 1)[0]
    assert shlex.split(quoted) == ["sh", "-c", "exit 1", weird]
