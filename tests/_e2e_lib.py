"""Shared end-to-end helpers for prompt-route wiring tests.

These helpers drive `python3 scripts/jot_plugin_orchestrator.py` as a real
subprocess with a fabricated hook JSON on stdin and let callers assert on
the documented hook-block side effect emitted on stdout.

Naming convention: `e2e_<verbPhrase>` per RED_GREEN_TDD.md.

Each `e2e_build<Route>PromptFixture(tmp_path)` factory must produce a
hermetic environment that short-circuits any tmux/Claude/Terminal.app
spawn so the test never leaks panes or windows. It returns
`(env_dict, json_payload_str)` so a single subprocess call suffices.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# Repo root is two parents up from this file (tests/_e2e_lib.py).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ORCHESTRATOR_PATH = _REPO_ROOT / "scripts" / "jot_plugin_orchestrator.py"


def e2e_runOrchestratorWithStdin(
    env: dict[str, str],
    stdin: str,
) -> subprocess.CompletedProcess[str]:
    """Invoke the orchestrator as a real subprocess.

    Args:
        env: Full environment passed to the child process (caller must
            include PATH and any plugin-required vars; this helper does
            not merge with os.environ to keep tests hermetic).
        stdin: Raw JSON string piped into the orchestrator's stdin.

    Returns:
        CompletedProcess with .stdout/.stderr/.returncode.
    """
    return subprocess.run(
        ["python3", str(_ORCHESTRATOR_PATH)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )


def e2e_parseHookDecision(stdout: str) -> dict:
    """Parse the last non-empty line of stdout as a hook block-decision.

    Mirrors how Claude Code reads the orchestrator's reply: the JSON
    block is the final substantive line on stdout. Empty stdout indicates
    silent passthrough; callers should assert on that separately.
    """
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        raise AssertionError(
            f"expected hook decision JSON on stdout; got empty output: {stdout!r}"
        )
    return json.loads(lines[-1])


def _e2e_buildStubBin(tmp_path: Path) -> Path:
    """Create executable shims for `claude`, `tmux`, `jq` so that
    hookjson_checkRequirements does not short-circuit with a missing-deps
    block. Each stub is a no-op that exits 0 and prints a known version
    when probed (tmux's `tmux -V` is parsed by tmux_requireVersion).

    Returns the bin dir to be prepended to PATH.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # tmux: must report a version >= 2.9 so tmux_requireVersion accepts it.
    (bin_dir / "tmux").write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  -V) echo 'tmux 3.4' ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    # claude / jq stubs (jq is also probed by todo-list).
    (bin_dir / "claude").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "jq").write_text("#!/bin/sh\nexit 0\n")

    for name in ("tmux", "claude", "jq"):
        (bin_dir / name).chmod(0o755)
    return bin_dir


def _e2e_baseEnv(tmp_path: Path) -> dict[str, str]:
    """Common env shared by every prompt-route fixture: stub bins on PATH,
    plugin-root/data wired, HOME isolated, plus the system PATH preserved
    so git / python3 still resolve."""
    plugin_root = _REPO_ROOT
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir(parents=True, exist_ok=True)

    bin_dir = _e2e_buildStubBin(tmp_path)
    # Prepend stub bin to existing PATH so git/python3/sh still resolve.
    path_value = f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"

    return {
        "PATH": path_value,
        "HOME": str(tmp_path / "home"),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PLUGIN_DATA": str(plugin_data),
    }


def _e2e_initEmptyRepo(tmp_path: Path, name: str = "repo") -> Path:
    """Create a tmp git repo with one empty commit. Used by routes that
    require `git rev-parse --show-toplevel` to succeed."""
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.email=t@t.t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    return repo


# ---------------------------------------------------------------------
# Per-route fixture factories.
# ---------------------------------------------------------------------

def e2e_buildJotPromptFixture(tmp_path: Path) -> tuple[dict[str, str], str]:
    """`/jot` with no idea -> jot_main emits 'jot: no idea provided' block.
    Hermetic: JOT_SKIP_LAUNCH=1 guards launch (defence-in-depth; the
    no-idea branch already short-circuits before the launch gate)."""
    env = _e2e_baseEnv(tmp_path)
    env["JOT_LOG_FILE"] = str(tmp_path / "jot.log")
    env["JOT_SKIP_LAUNCH"] = "1"
    repo = _e2e_initEmptyRepo(tmp_path, "jot-repo")
    payload = json.dumps({
        "prompt": "/jot",
        "session_id": "e2e-jot",
        "transcript_path": "",
        "cwd": str(repo),
    })
    return env, payload


def e2e_buildDebatePromptFixture(tmp_path: Path) -> tuple[dict[str, str], str]:
    """`/debate` with no topic -> debate_main emits 'debate: no topic provided'.
    Hermetic: DEBATE_SKIP_TERMINAL_CHECK=1 bypasses the macOS Terminal.app
    probe in debate_launch."""
    env = _e2e_baseEnv(tmp_path)
    env["DEBATE_LOG_FILE"] = str(tmp_path / "debate.log")
    env["DEBATE_SKIP_TERMINAL_CHECK"] = "1"
    repo = _e2e_initEmptyRepo(tmp_path, "debate-repo")
    payload = json.dumps({
        "prompt": "/debate",
        "session_id": "e2e-debate",
        "transcript_path": "",
        "cwd": str(repo),
    })
    return env, payload


def e2e_buildDebateRetryPromptFixture(tmp_path: Path) -> tuple[dict[str, str], str]:
    """`/debate-retry` with empty transcript_path -> debateRetry_main bails
    out via the early-transcript-empty branch. Observable: debate_initHookContext
    creates the parent dir of DEBATE_LOG_FILE; we point that file at a nested
    path that does NOT exist beforehand, so the dir's existence proves the
    routed entrypoint ran. No skip switch needed; debateRetry_main does not
    spawn Terminal.app or claude before the early return."""
    env = _e2e_baseEnv(tmp_path)
    nested = tmp_path / "debate-retry-logs" / "nested"
    env["DEBATE_LOG_FILE"] = str(nested / "debate.log")
    repo = _e2e_initEmptyRepo(tmp_path, "debate-retry-repo")
    payload = json.dumps({
        "prompt": "/debate-retry",
        "session_id": "e2e-debate-retry",
        "transcript_path": "",
        "cwd": str(repo),
    })
    return env, payload


def e2e_buildDebateAbortPromptFixture(tmp_path: Path) -> tuple[dict[str, str], str]:
    """`/debate-abort` with empty transcript_path -> debateAbort_main bails
    via the empty-transcript_path early branch. Same observable strategy as
    debate-retry: nested DEBATE_LOG_FILE parent dir is created by
    debate_initHookContext, proving the routed entrypoint ran."""
    env = _e2e_baseEnv(tmp_path)
    nested = tmp_path / "debate-abort-logs" / "nested"
    env["DEBATE_LOG_FILE"] = str(nested / "debate.log")
    repo = _e2e_initEmptyRepo(tmp_path, "debate-abort-repo")
    payload = json.dumps({
        "prompt": "/debate-abort",
        "session_id": "e2e-debate-abort",
        "transcript_path": "",
        "cwd": str(repo),
    })
    return env, payload


def e2e_resolveDebateLogParent(env: dict[str, str]) -> Path:
    """Helper: parent dir of DEBATE_LOG_FILE (created by debate_initHookContext)."""
    return Path(env["DEBATE_LOG_FILE"]).parent


def e2e_buildTodoPromptFixture(tmp_path: Path) -> tuple[dict[str, str], str]:
    """`/todo <idea>` -> todo_main writes Todos/.todo-state/pending-*.json
    in the cwd repo. todo_main never spawns a subprocess (silent return);
    no skip switch required. Returns (env, payload, repo_path)."""
    env = _e2e_baseEnv(tmp_path)
    env["TODO_LOG_FILE"] = str(tmp_path / "todo.log")
    repo = _e2e_initEmptyRepo(tmp_path, "todo-repo")
    payload = json.dumps({
        "prompt": "/todo park this idea",
        "session_id": "e2e-todo",
        "transcript_path": "",
        "cwd": str(repo),
    })
    return env, payload


def e2e_buildTodoListPromptFixture(tmp_path: Path) -> tuple[dict[str, str], str]:
    """`/todo-list` against a repo with no Todos/ dir -> todoList_main
    emits 'No Todos/ folder found in this project.' block. No skip
    switch needed."""
    env = _e2e_baseEnv(tmp_path)
    repo = _e2e_initEmptyRepo(tmp_path, "todo-list-repo")
    payload = json.dumps({
        "prompt": "/todo-list",
        "session_id": "e2e-todo-list",
        "transcript_path": "",
        "cwd": str(repo),
    })
    return env, payload


def e2e_resolveTodoRepoPath(env: dict[str, str], stdin: str) -> Path:
    """Helper: extract cwd from the JSON payload so tests can probe the
    Todos/.todo-state/ directory after invocation."""
    return Path(json.loads(stdin)["cwd"])
