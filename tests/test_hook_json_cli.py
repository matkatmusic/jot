"""Parity tests for common/scripts/hook_json_cli.py and hook-json.sh shim."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_JSON_CLI = REPO_ROOT / "common" / "scripts" / "hook_json_cli.py"
HOOK_JSON_SH = REPO_ROOT / "common" / "scripts" / "hook-json.sh"


def py(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK_JSON_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def sh(snippet: str) -> subprocess.CompletedProcess:
    """Source hook-json.sh and run a bash snippet inside one shell."""
    return subprocess.run(
        ["bash", "-c", f'source "{HOOK_JSON_SH}"; {snippet}'],
        capture_output=True,
        text=True,
        check=False,
    )


# ── emit-block (Python CLI) ───────────────────────────────────────────


def test_emit_block_prints_block_json():
    out = py("emit-block", "hello")
    assert out.returncode == 0
    parsed = json.loads(out.stdout)
    assert parsed == {"decision": "block", "reason": "hello"}


def test_emit_block_handles_special_chars():
    reason = 'has "quotes" and a\\backslash'
    out = py("emit-block", reason)
    assert out.returncode == 0
    parsed = json.loads(out.stdout)
    assert parsed["reason"] == reason


# ── check-requirements (Python CLI) ───────────────────────────────────


def test_check_requirements_silent_when_all_present():
    out = py("check-requirements", "jot", "sh", "ls")
    assert out.returncode == 0
    assert out.stdout == ""


def test_check_requirements_silent_when_no_cmds_given():
    out = py("check-requirements", "jot")
    assert out.returncode == 0
    assert out.stdout == ""


def test_check_requirements_emits_block_for_missing():
    out = py("check-requirements", "jot", "definitely_missing_xyz")
    assert out.returncode == 0
    parsed = json.loads(out.stdout)
    assert parsed["decision"] == "block"
    assert "definitely_missing_xyz" in parsed["reason"]
    assert parsed["reason"].startswith("jot needs:")
    assert parsed["reason"].endswith("- install and retry.")


# ── bash shim parity ──────────────────────────────────────────────────


def test_shim_emit_block_matches_python():
    py_out = py("emit-block", "shim test")
    sh_out = sh('emit_block "shim test"')
    assert sh_out.returncode == py_out.returncode == 0
    assert sh_out.stdout == py_out.stdout


def test_shim_check_requirements_silent_when_all_present():
    out = sh("check_requirements jot sh ls; echo AFTER")
    assert out.returncode == 0
    # Function returned silently; the `echo AFTER` ran.
    assert out.stdout.strip().splitlines() == ["AFTER"]


def test_shim_check_requirements_halts_on_missing():
    # The shim must `exit 0` from inside the sourcing shell when a block
    # JSON is emitted, so the trailing `echo SHOULD_NOT_PRINT` must NOT
    # appear in stdout. This is the contract the 9 callers depend on.
    out = sh(
        "check_requirements jot definitely_missing_xyz; "
        "echo SHOULD_NOT_PRINT"
    )
    assert out.returncode == 0
    assert "SHOULD_NOT_PRINT" not in out.stdout
    parsed = json.loads(out.stdout.strip())
    assert parsed["decision"] == "block"
    assert "definitely_missing_xyz" in parsed["reason"]
