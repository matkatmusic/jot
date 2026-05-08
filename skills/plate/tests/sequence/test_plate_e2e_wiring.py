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
_ORCHESTRATOR = _REPO_ROOT / "scripts" / "jot_plugin_orchestrator.py"


def _run_hook(prompt: str, repo_path: Path, session_id: str = "test-sess",
              transcript_path: str = "",
              plate_log_file: str = "/tmp/plate-e2e-test-data/plate-log.txt",
              ) -> tuple[str, str, int]:
    """Invoke the Python orchestrator with a synthesized hook JSON. Returns
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
        "PLATE_LOG_FILE": plate_log_file,
        "PLATE_SKIP_LAUNCH": "1",
    }
    Path(env["CLAUDE_PLUGIN_DATA"]).mkdir(parents=True, exist_ok=True)
    Path(plate_log_file).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["python3", str(_ORCHESTRATOR)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout, proc.stderr, proc.returncode


def _writeFakeTranscript(path: Path, entries: list[dict]) -> Path:
    """Write a minimal JSONL transcript carrying tool_use blocks (one per entry).

    Each `entries[i]` dict needs keys: timestamp, tool, input.
    """
    lines = []
    for e in entries:
        lines.append(json.dumps({
            "type": "assistant",
            "timestamp": e["timestamp"],
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": f"toolu_{e['timestamp']}",
                    "name": e["tool"],
                    "input": e["input"],
                }],
            },
        }))
    path.write_text("\n".join(lines) + "\n")
    return path


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


# ──────────────────────────────────────────────────────────────────────
# Bug-port verification: extraction-path captures Bash and subagent
# authored files, and logs silent no-ops (ports of fix-plate-bugs 9d21262).
# ──────────────────────────────────────────────────────────────────────


def _platePathOf(repo: Path) -> str:
    # Default branch is `main` or `master` depending on git's init.defaultBranch.
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return f"{head}-plate"


def _establishFirstPlateFromAgentA(empty_repo: Path, tmp_path: Path) -> str:
    # Setup helper: produce a main-plate at convo-id=UUID-A so the second-agent
    # push routes through the extraction path (use_extraction=True).
    uuid_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    transcript_A = tmp_path / f"{uuid_A}.jsonl"
    _writeFakeTranscript(transcript_A, [
        {"timestamp": "2099-01-01T00:00:00.000Z", "tool": "Edit",
         "input": {"file_path": str(empty_repo / "a.txt")}},
    ])
    (empty_repo / "a.txt").write_text("first-agent edit\n")
    out, err, rc = _run_hook("/plate", empty_repo,
                             session_id=uuid_A,
                             transcript_path=str(transcript_A))
    assert rc == 0, f"first-agent push crashed: stderr={err!r}"
    block = _parse_block(out)
    assert block["reason"].startswith("plate: pushed "), (
        f"first-agent push must succeed; got {block['reason']!r}"
    )
    return uuid_A


def test_push_captures_bash_created_file_via_transcript(
    empty_repo: Path, tmp_path: Path,
) -> None:
    # Scenario: file authored only via a Bash redirect (no Edit/Write tool_use)
    # must surface in the second-agent's plate commit. Without B5 wiring the
    # extracted tree equals parent_tree and the push is a silent no-op.
    # Setup: first plate from agent A.
    _establishFirstPlateFromAgentA(empty_repo, tmp_path)

    # Setup B: same observable WT state a real `printf 'x' > newfile.txt`
    # would leave behind, plus a transcript with ONLY a Bash record.
    (empty_repo / "newfile.txt").write_text("x\n")
    uuid_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    transcript_B = tmp_path / f"{uuid_B}.jsonl"
    _writeFakeTranscript(transcript_B, [
        {"timestamp": "2099-01-01T00:02:00.000Z", "tool": "Bash",
         "input": {"command": "printf 'x' > newfile.txt"}},
    ])

    # Test action: fire /plate via the hook chain.
    out, err, rc = _run_hook("/plate", empty_repo,
                             session_id=uuid_B,
                             transcript_path=str(transcript_B))
    assert rc == 0, f"second-agent push crashed: stderr={err!r}"
    block = _parse_block(out)
    assert block["reason"].startswith("plate: pushed "), (
        f"Bash-only push must promote to a plate commit; got {block['reason']!r}"
    )

    # Test verification: plate tip's tree contains newfile.txt.
    listing = subprocess.run(
        ["git", "-C", str(empty_repo), "ls-tree", "-r", "--name-only", _platePathOf(empty_repo)],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert "newfile.txt" in listing


def test_push_captures_subagent_authored_file_via_sidechain_transcript(
    empty_repo: Path, tmp_path: Path,
) -> None:
    # Scenario: file authored by a Task-spawned subagent (tool_use record lives
    # only in <parent_stem>/subagents/agent-001.jsonl) must surface in the
    # parent's plate commit. Without B2+B3+B5 the file is invisible.
    _establishFirstPlateFromAgentA(empty_repo, tmp_path)

    # Setup B: empty parent transcript, sidechain agent-001.jsonl with a Bash
    # touch record, file actually present in WT.
    uuid_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    transcript_B = tmp_path / f"{uuid_B}.jsonl"
    transcript_B.write_text("")
    sub_dir = tmp_path / uuid_B / "subagents"
    sub_dir.mkdir(parents=True)
    _writeFakeTranscript(sub_dir / "agent-001.jsonl", [
        {"timestamp": "2099-01-01T00:02:00.000Z", "tool": "Bash",
         "input": {"command": "touch child.txt"}},
    ])
    (empty_repo / "child.txt").write_text("x\n")

    # Test action.
    out, err, rc = _run_hook("/plate", empty_repo,
                             session_id=uuid_B,
                             transcript_path=str(transcript_B))
    assert rc == 0, f"second-agent push crashed: stderr={err!r}"
    block = _parse_block(out)
    assert block["reason"].startswith("plate: pushed "), (
        f"subagent-authored push must promote; got {block['reason']!r}"
    )

    listing = subprocess.run(
        ["git", "-C", str(empty_repo), "ls-tree", "-r", "--name-only", _platePathOf(empty_repo)],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert "child.txt" in listing


def test_push_logs_plate_extract_empty_when_wt_dirty_but_extract_matches_parent(
    empty_repo: Path, tmp_path: Path,
) -> None:
    # Scenario: dirty WT plus a transcript with NO tool_use records since the
    # parent tip → extract_tree == parent_tree but full WT differs. The
    # plate-extract-empty diagnostic must land in the log so silent no-op
    # pushes are auditable.
    _establishFirstPlateFromAgentA(empty_repo, tmp_path)

    # Setup B: empty parent transcript, no sidechain, but dirty WT.
    uuid_B = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    transcript_B = tmp_path / f"{uuid_B}.jsonl"
    transcript_B.write_text("")
    (empty_repo / "unrelated.txt").write_text("dirt\n")

    # Use a per-test log file so the assertion is robust against parallel runs.
    log_file = tmp_path / "plate-log.txt"

    out, err, rc = _run_hook("/plate", empty_repo,
                             session_id=uuid_B,
                             transcript_path=str(transcript_B),
                             plate_log_file=str(log_file))
    assert rc == 0, f"hook crashed: stderr={err!r}"
    block = _parse_block(out)
    # No commit; user-facing message is the "no changes" form.
    assert "no changes to stack" in block["reason"]

    # Test verification: log line landed with the canonical event marker.
    assert log_file.exists(), f"plate log was not created at {log_file}"
    contents = log_file.read_text()
    assert "plate-extract-empty" in contents, (
        f"diagnostic line missing from {log_file}; got:\n{contents!r}"
    )
    assert f"convo={uuid_B}" in contents
