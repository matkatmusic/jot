"""End-to-end tests for the SessionEnd auto-`/plate` hook wiring.

The hook entry in hooks/hooks.json synthesizes a `/plate` prompt by
piping the SessionEnd JSON payload through `jq` (which inserts
`prompt:"/plate"`) and into `scripts/orchestrator.sh`. These tests
exercise that exact pipeline via subprocess.run with shell=True.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ORCHESTRATOR = _REPO_ROOT / "scripts" / "jot-plugin-orchestrator.sh"


def _run_session_end(payload: dict, repo_path: Path) -> tuple[str, str, int]:
    """Replicate the hooks.json SessionEnd command exactly:
        jq '. + {prompt: "/plate"}' | bash <orchestrator.sh>
    Returns (stdout, stderr, exit_code).
    """
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(_REPO_ROOT),
        "CLAUDE_PLUGIN_DATA": "/tmp/plate-session-end-test-data",
        "PLATE_LOG_FILE": "/tmp/plate-session-end-test-data/plate-log.txt",
    }
    Path(env["CLAUDE_PLUGIN_DATA"]).mkdir(parents=True, exist_ok=True)
    cmd = (
        f"jq '. + {{prompt: \"/plate\"}}' | bash {shlex.quote(str(_ORCHESTRATOR))}"
    )
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        shell=True,
        env=env,
    )
    return proc.stdout, proc.stderr, proc.returncode


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """Bare git repo with one initial commit."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path),
         "-c", "user.email=t@t.t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    return tmp_path


def _plate_refs(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)",
         "refs/heads/"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [r for r in out.splitlines() if r.endswith("-plate")]


def test_session_end_with_dirty_wt_creates_plate_ref(empty_repo: Path) -> None:
    """End-to-end proof of the SessionEnd hook contract: dirty WT plus a
    SessionEnd payload (no `prompt` field) goes through the
    `jq → orchestrator.sh` pipe and produces a <branch>-plate ref."""
    (empty_repo / "wip.txt").write_text("uncommitted work\n")
    assert _plate_refs(empty_repo) == [], "precondition: no plate refs yet"

    payload = {
        "session_id": "test-sess",
        "transcript_path": "",
        "cwd": str(empty_repo),
    }
    out, err, rc = _run_session_end(payload, empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"

    refs = _plate_refs(empty_repo)
    assert len(refs) == 1, f"expected exactly one *-plate ref; got {refs}"

    # Trailers must include convo-id (the synthesized session_id).
    trailers = subprocess.run(
        ["git", "-C", str(empty_repo), "log", "-1",
         "--format=%(trailers:key=convo-id,valueonly,unfold=true)", refs[0]],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert trailers == "test-sess", f"convo-id trailer mismatch: {trailers!r}"


def test_session_end_with_clean_wt_creates_no_plate(empty_repo: Path) -> None:
    """Clean WT → cli.py push returns 'no changes to stack'; no commit, no ref."""
    assert _plate_refs(empty_repo) == [], "precondition: no plate refs yet"

    payload = {
        "session_id": "test-sess",
        "transcript_path": "",
        "cwd": str(empty_repo),
    }
    out, err, rc = _run_session_end(payload, empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"
    assert _plate_refs(empty_repo) == [], (
        f"expected no plate ref on clean WT; got {_plate_refs(empty_repo)}"
    )
