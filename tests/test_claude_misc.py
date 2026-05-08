from __future__ import annotations

from common.scripts.debate_lib import (
    debate_agentErrorMarkers,
    debate_agentLaunchCmd,
    debate_agentReadyMarker,
    debate_initAgentModels,
)


def test_claude_marker():
    # Scenario: claude CLI prints its banner once ready.
    # Setup: agent name is the literal "claude".
    # Test action: query the ready marker.
    # Test verification: returns the banner prefix used by orchestrator grep.
    agent = "claude"
    result = debate_agentReadyMarker(agent)
    assert result == "Claude Code v"


def test_claude_returns_overload_markers():
    # Scenario: claude agent has 529/overloaded markers
    # Setup: agent name 'claude'
    # Test action: call debate_agentErrorMarkers('claude')
    # Test verification: returns exactly the two claude markers
    result = debate_agentErrorMarkers("claude")
    assert result == ["API Error: 529", "overloaded_error"]


# ──────────────────────────── claude ────────────────────────────

def test_claude_repo_root_equals_cwd_no_plans_dup() -> None:
    # Scenario: CWD == REPO_ROOT and home/.claude/plans differs.
    # Setup: CWD == REPO_ROOT == /repo; home /h => plans /h/.claude/plans (distinct).
    current_model: dict[str, str] = {}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model=current_model,
        debate_dir="/repo/Debates/X",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/tmp/settings.json",
    )
    # Test verification: only one --add-dir for cwd, plus plans dir; no duplicate repo_root.
    assert cmd == (
        "claude --settings '/tmp/settings.json' "
        "--add-dir '/repo' --add-dir '/h/.claude/plans'"
    )


def test_claude_repo_root_distinct_from_cwd() -> None:
    # Scenario: CWD differs from REPO_ROOT; both differ from plans.
    # Setup: cwd /sub, repo_root /repo, home /h.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model={},
        debate_dir="/repo/Debates/X",
        cwd="/sub",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: cwd, repo_root, then plans appended in order.
    assert cmd == (
        "claude --settings '/s.json' "
        "--add-dir '/sub' --add-dir '/repo' --add-dir '/h/.claude/plans'"
    )


def test_claude_plans_equals_cwd_skipped() -> None:
    # Scenario: CWD is exactly $HOME/.claude/plans.
    # Setup: cwd == /h/.claude/plans, repo_root == cwd.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model={},
        debate_dir="/x",
        cwd="/h/.claude/plans",
        repo_root="/h/.claude/plans",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: no duplicate plans --add-dir appended.
    assert cmd == "claude --settings '/s.json' --add-dir '/h/.claude/plans'"


def test_claude_repo_root_empty_string_skipped() -> None:
    # Scenario: not in a git repo => REPO_ROOT == "".
    # Setup: empty repo_root; cwd /tmp.
    cmd = debate_agentLaunchCmd(
        agent="claude",
        current_model={},
        debate_dir="/x",
        cwd="/tmp",
        repo_root="",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: empty repo_root contributes no --add-dir; plans still added.
    assert cmd == (
        "claude --settings '/s.json' "
        "--add-dir '/tmp' --add-dir '/h/.claude/plans'"
    )


def test_claude_has_empty_string_when_no_env():
    # Scenario: bash never stashes a CLAUDE_MODEL value, only zeroes it
    # Setup: empty env
    # Test action: call function
    # Test verification: claude entries default to ""
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["claude"] == ""
    assert result["TRIED_MODELS"]["claude"] == ""
