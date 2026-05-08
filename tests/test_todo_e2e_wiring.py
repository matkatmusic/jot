"""End-to-end wiring tests for the /todo and /todo-list prompt routes.

`/todo` writes a pending-claim JSON file under
`<repo>/Todos/.todo-state/`; `/todo-list` emits a stdout block-decision
when no Todos/ folder exists. Both run through
`scripts/jot_plugin_orchestrator.py` via the _PROMPT_DISPATCH map.

Lives under `tests/` because the todo and todo-list skills do not have
dedicated `tests/sequence/` dirs on this branch.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests._e2e_lib import (
    e2e_buildTodoListPromptFixture,
    e2e_buildTodoPromptFixture,
    e2e_parseHookDecision,
    e2e_resolveTodoRepoPath,
    e2e_runOrchestratorWithStdin,
)


def test_todoPrompt_e2e_routesTo_todo_main_writesPendingClaimFile(tmp_path: Path) -> None:
    # Scenario: a UserPromptSubmit payload with prompt "/todo park this idea"
    # must be routed via _PROMPT_DISPATCH to todo_lib.todo_main, which
    # writes a "pending-*.json" claim file under <repo>/Todos/.todo-state/.
    # The claim file is the documented side effect of todo_main; no stdout.
    # Setup: hermetic env with stub claude/tmux/jq; tmp git repo as cwd.
    env, payload = e2e_buildTodoPromptFixture(tmp_path)
    repo = e2e_resolveTodoRepoPath(env, payload)
    state_dir = repo / "Todos" / ".todo-state"
    assert not state_dir.exists(), "precondition: state dir must not pre-exist"

    # Test action: pipe payload through the orchestrator.
    result = e2e_runOrchestratorWithStdin(env=env, stdin=payload)

    # Test verification: rc==0 and exactly one pending claim file exists,
    # whose JSON body carries our idea string.
    assert result.returncode == 0, (
        f"orchestrator crashed: stderr={result.stderr!r}"
    )
    pending_files = sorted(state_dir.glob("pending-*.json"))
    assert len(pending_files) == 1, (
        f"expected exactly one pending claim file, got: {pending_files}"
    )
    claim = json.loads(pending_files[0].read_text(encoding="utf-8"))
    assert claim.get("idea") == "park this idea"


def test_todoListPrompt_e2e_routesTo_todoList_main_emitsNoTodosFolderBlock(
    tmp_path: Path,
) -> None:
    # Scenario: a UserPromptSubmit payload with prompt "/todo-list" against
    # a repo that has no Todos/ folder must be routed via _PROMPT_DISPATCH
    # to todo_lib.todo_listMain, which prints the documented
    # "No Todos/ folder found in this project." block on stdout.
    # Setup: hermetic env; cwd is a fresh tmp repo without a Todos/ dir.
    env, payload = e2e_buildTodoListPromptFixture(tmp_path)

    # Test action: pipe payload through the orchestrator.
    result = e2e_runOrchestratorWithStdin(env=env, stdin=payload)

    # Test verification: rc==0 and stdout's last line is the expected block.
    assert result.returncode == 0, (
        f"orchestrator crashed: stderr={result.stderr!r}"
    )
    decision = e2e_parseHookDecision(result.stdout)
    assert decision["decision"] == "block"
    assert decision["reason"] == "No Todos/ folder found in this project."
