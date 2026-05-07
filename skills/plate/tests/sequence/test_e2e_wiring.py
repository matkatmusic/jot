"""End-to-end wiring tests for the /plate UserPromptSubmit hook.

Pipes a fabricated hook JSON into plate-orchestrator.sh, parses the
emitted block as JSON, and asserts (a) decision == "block" (so Claude
Code suppresses the literal /plate prompt and shows our reason instead)
and (b) reason contains the expected text.

Per feedback_verify_before_commit.md: this is the integration test that
proves the production wiring works. Per feedback_verify_work.md: each
test must fail if the wiring is broken — the most direct check is that
the bogus-prompt case produces no output (silent fast-path bail-out)
while a real /plate variant produces parseable JSON.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ORCHESTRATOR = _REPO_ROOT / "scripts" / "jot-plugin-orchestrator.sh"


def _run_hook(prompt: str, repo_path: Path, session_id: str = "test-sess",
              transcript_path: str = "") -> tuple[str, str, int]:
    """Invoke plate-orchestrator.sh with a synthesized hook JSON. Returns
    (stdout, stderr, exit_code)."""
    payload = json.dumps({
        "prompt": prompt,
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": str(repo_path),
    })
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(_REPO_ROOT),
        "CLAUDE_PLUGIN_DATA": "/tmp/plate-e2e-test-data",
        "PLATE_LOG_FILE": "/tmp/plate-e2e-test-data/plate-log.txt",
    }
    Path(env["CLAUDE_PLUGIN_DATA"]).mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["bash", str(_ORCHESTRATOR)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout, proc.stderr, proc.returncode


def _parse_block(stdout: str) -> dict:
    """Parse the emitted hook block as JSON. Asserts well-formedness."""
    assert stdout.strip(), "expected JSON block on stdout, got empty output"
    obj = json.loads(stdout)
    assert obj.get("decision") == "block", (
        f"expected decision=block (so /plate isn't forwarded to the model); got {obj!r}"
    )
    assert "reason" in obj, f"block missing 'reason' field: {obj!r}"
    return obj


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """Bare repo with one empty commit. Branch model needs at least one
    commit to anchor refs; nothing else needs to exist."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path),
         "-c", "user.email=t@t.t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    return tmp_path


# ──────────────────────────────────────────────────────────────────────
# Hook contract: every /plate variant must emit decision=block JSON.
# ──────────────────────────────────────────────────────────────────────

def test_next_list_mode_returns_empty_list_message(empty_repo: Path) -> None:
    """A repo with no plate refs → list mode returns the friendly empty message."""
    out, err, rc = _run_hook("/plate --next", empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"
    block = _parse_block(out)
    assert "No changes plated" in block["reason"]


def test_next_jump_non_numeric_returns_message(empty_repo: Path) -> None:
    """Non-numeric --next argument → user-facing PLATE_NEXT_NON_NUMERIC_MESSAGE
    surfaces all the way out through the hook contract."""
    out, err, rc = _run_hook("/plate --next abc", empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"
    block = _parse_block(out)
    assert "must be a number" in block["reason"]


def test_show_returns_todo_stub(empty_repo: Path) -> None:
    """--show is a stub for now — should reach Python and return literal 'TODO'."""
    out, err, rc = _run_hook("/plate --show", empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"
    block = _parse_block(out)
    assert block["reason"] == "TODO"


def test_drop_no_plate_returns_message(empty_repo: Path) -> None:
    """Drop with no plate ref → 'no plate to drop' message in the block reason."""
    out, err, rc = _run_hook("/plate --drop", empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"
    block = _parse_block(out)
    assert "no plate to drop" in block["reason"]


def test_push_on_empty_wt_returns_no_changes(empty_repo: Path) -> None:
    """A clean WT with no prior plate → push returns 'no changes to stack'."""
    out, err, rc = _run_hook("/plate", empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"
    block = _parse_block(out)
    assert "no changes to stack" in block["reason"]


def test_push_with_dirty_wt_creates_plate_branch(empty_repo: Path, tmp_path: Path) -> None:
    """Real push: create an untracked file, fire /plate, assert plate branch
    appears in the repo. End-to-end proof the hook → cli → plate_lib chain
    actually mutates git state."""
    (empty_repo / "wip.txt").write_text("uncommitted work\n")

    # Sanity: no plate branch yet.
    refs_before = subprocess.run(
        ["git", "-C", str(empty_repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "-plate" not in refs_before

    out, err, rc = _run_hook("/plate", empty_repo)
    assert rc == 0, f"hook crashed: stderr={err!r}"
    block = _parse_block(out)
    assert block["reason"].startswith("plate: pushed "), (
        f"expected push-success message, got: {block['reason']!r}"
    )

    refs_after = subprocess.run(
        ["git", "-C", str(empty_repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        capture_output=True, text=True, check=True,
    ).stdout
    # Default branch is "main" or "master" depending on git config; either
    # should produce <branch>-plate.
    assert "-plate" in refs_after, (
        f"expected a *-plate ref to exist after push; got refs:\n{refs_after}"
    )


# ──────────────────────────────────────────────────────────────────────
# Fast-path bail-out: non-/plate prompts must NOT spawn Python.
# ──────────────────────────────────────────────────────────────────────

def test_unrelated_prompt_exits_silently(empty_repo: Path) -> None:
    """The substring fast-path must let unrelated prompts through with no
    output. This is the same property /jot has — no interruption to the
    user's conversation when the hook isn't relevant."""
    out, err, rc = _run_hook("hello world", empty_repo)
    assert rc == 0, f"hook crashed on unrelated prompt: stderr={err!r}"
    assert out == "", f"expected silent bail-out, got stdout: {out!r}"


def test_typo_variant_exits_silently(empty_repo: Path) -> None:
    """Variant typo (e.g. /plate --dne) doesn't match the strict regex
    and exits silently — no Python spawn, no error block. User sees their
    prompt go to the model unchanged, which is the correct UX for a typo."""
    out, err, rc = _run_hook("/plate --dne", empty_repo)
    assert rc == 0, f"hook crashed on typo variant: stderr={err!r}"
    assert out == "", f"expected silent bail-out for typo, got stdout: {out!r}"
