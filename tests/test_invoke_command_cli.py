"""Parity tests for invoke_command_cli.py and the invoke_command.sh shim.

CLI tests assert the spec end-to-end via subprocess. Shim tests verify
that the bash shim's ${FUNCNAME[1]} capture round-trips into the
caller-name prefix that errors carry.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INVOKE_CMD_CLI = REPO_ROOT / "common" / "scripts" / "invoke_command_cli.py"
INVOKE_CMD_SH = REPO_ROOT / "common" / "scripts" / "invoke_command.sh"


def py(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INVOKE_CMD_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def sh(snippet: str) -> subprocess.CompletedProcess:
    """Run snippet inside a bash that has invoke_command.sh sourced."""
    return subprocess.run(
        ["bash", "-c", f'source "{INVOKE_CMD_SH}"; {snippet}'],
        capture_output=True,
        text=True,
        check=False,
    )


# ── CLI direct ────────────────────────────────────────────────────────


def test_cli_success_with_output():
    out = py("run", "--caller", "c", "--", "echo", "hello")
    assert out.returncode == 0
    assert out.stdout == "hello\n"
    assert out.stderr == ""


def test_cli_success_no_output_is_silent():
    out = py("run", "--caller", "c", "--", "true")
    assert out.returncode == 0
    assert out.stdout == ""
    assert out.stderr == ""


def test_cli_failure_writes_caller_tagged_error():
    out = py("run", "--caller", "my_caller", "--", "false")
    assert out.returncode != 0
    assert out.stderr.startswith("[my_caller] command ")
    assert " failed:" in out.stderr


def test_cli_failure_returns_underlying_exit_code():
    out = py("run", "--caller", "c", "--", "sh", "-c", "exit 42")
    assert out.returncode == 42


def test_cli_missing_program_returns_127():
    out = py("run", "--caller", "c", "--", "definitely_not_a_real_xyz")
    assert out.returncode == 127


def test_cli_missing_caller_flag_errors():
    out = py("run", "--", "true")
    assert out.returncode != 0


def test_cli_run_without_command_errors():
    out = py("run", "--caller", "c")
    assert out.returncode != 0


# ── Bash-shim parity ──────────────────────────────────────────────────


def test_shim_captures_caller_name_in_error():
    """${FUNCNAME[1]} from inside the shim must yield the bash caller name."""
    out = sh(
        'my_outer_func() { invoke_command false; }; my_outer_func'
    )
    assert out.returncode != 0
    assert "[my_outer_func]" in out.stderr


def test_shim_top_level_call_uses_unknown_fallback():
    """When called from top-level (no enclosing function), use 'unknown'."""
    out = sh('invoke_command false')
    assert out.returncode != 0
    assert "[unknown]" in out.stderr


def test_shim_success_with_output_passes_through():
    out = sh('my_caller() { invoke_command echo hi; }; my_caller')
    assert out.returncode == 0
    assert out.stdout == "hi\n"


def test_shim_success_no_output_is_silent():
    out = sh('my_caller() { invoke_command true; }; my_caller')
    assert out.returncode == 0
    assert out.stdout == ""
    assert out.stderr == ""


def test_shim_propagates_underlying_exit_code():
    out = sh(
        'my_caller() { invoke_command sh -c "exit 7"; }; my_caller'
    )
    assert out.returncode == 7


def test_shim_argv_with_spaces_quoted_in_error():
    out = sh(
        'my_caller() { invoke_command sh -c "exit 1" "arg with spaces"; }; '
        'my_caller'
    )
    assert out.returncode != 0
    # The shlex-quoted form of the spaced arg must appear.
    assert "'arg with spaces'" in out.stderr
