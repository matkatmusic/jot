"""End-to-end wiring tests for the /jot prompt route.

Pipes a fabricated UserPromptSubmit hook JSON into
`scripts/jot_plugin_orchestrator.py` and asserts the routed
`jot_lib.jot_main` entrypoint produces its documented stdout block.

Lives under `tests/` (not `skills/jot/tests/sequence/`) because the jot
skill does not yet have a dedicated test tree on this branch. Mirrors
the four-marker structure used in
`skills/plate/tests/sequence/test_plate_e2e_wiring.py`.
"""
from __future__ import annotations

from pathlib import Path

from tests._e2e_lib import (
    e2e_buildJotPromptFixture,
    e2e_parseHookDecision,
    e2e_runOrchestratorWithStdin,
)


def test_jotPrompt_e2e_routesTo_jot_main_emitsNoIdeaBlock(tmp_path: Path) -> None:
    # Scenario: a UserPromptSubmit payload with prompt "/jot" (no idea
    # supplied) must be routed by the orchestrator's _PROMPT_DISPATCH
    # to jot_lib.jot_main, which emits the documented "no idea provided"
    # block-decision JSON on stdout.
    # Setup: hermetic env (stub claude/tmux/jq on PATH, JOT_SKIP_LAUNCH=1
    # belt-and-braces, real tmp git repo for cwd) and the literal payload.
    env, payload = e2e_buildJotPromptFixture(tmp_path)

    # Test action: pipe payload through `python3 scripts/jot_plugin_orchestrator.py`.
    result = e2e_runOrchestratorWithStdin(env=env, stdin=payload)

    # Test verification: rc==0 and stdout's last line is the no-idea block.
    assert result.returncode == 0, (
        f"orchestrator crashed: stderr={result.stderr!r}"
    )
    decision = e2e_parseHookDecision(result.stdout)
    assert decision["decision"] == "block"
    assert decision["reason"] == "jot: no idea provided"
