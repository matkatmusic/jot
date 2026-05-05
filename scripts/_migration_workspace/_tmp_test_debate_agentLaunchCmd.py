#!/usr/bin/env python3
"""RED-YELLOW-GREEN tests for debate_agentLaunchCmd.

Author intent (from bash agent_launch_cmd in jot-plugin-orchestrator.sh ~L2740):
- Returns the per-agent launch command string for tmux send.
- gemini: "gemini --allowed-tools '...' [--model '<m>']"
- codex:  "codex -a never --add-dir '<DEBATE_DIR>' [--model '<m>']"
- claude: "claude --settings '<SETTINGS_FILE>' --add-dir '<CWD>'
           [--add-dir '<REPO_ROOT>'] [--add-dir '<HOME>/.claude/plans']"
- Model lookup goes through CURRENT_MODEL stash; empty string => no --model flag.
- Claude path inclusion deduplicates: REPO_ROOT only added if != CWD,
  ~/.claude/plans only added if != CWD and != REPO_ROOT.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Standard sys.path insert so the temp module is importable.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _tmp_debate_agentLaunchCmd import debate_agentLaunchCmd  # noqa: E402


# ──────────────────────────── gemini ────────────────────────────

def test_gemini_with_model() -> None:
    # Scenario: caller selected an explicit gemini model.
    # Setup: stash CURRENT_MODEL[gemini] = "gemini-2.5-pro".
    current_model = {"gemini": "gemini-2.5-pro"}
    # Test action: build launch cmd for gemini.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: --model flag appears with the chosen model, quoted.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)' "
        "--model 'gemini-2.5-pro'"
    )


def test_gemini_without_model() -> None:
    # Scenario: no model preselected for gemini.
    # Setup: stash CURRENT_MODEL[gemini] = "" (empty).
    current_model = {"gemini": ""}
    # Test action: build launch cmd.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: no --model segment present.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)'"
    )


# ──────────────────────────── codex ────────────────────────────

def test_codex_with_model() -> None:
    # Scenario: codex with explicit model.
    # Setup: model "gpt-5", debate_dir "/repo/Debates/T_slug".
    current_model = {"codex": "gpt-5"}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/T_slug",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: --add-dir uses debate_dir; --model uses provided.
    assert cmd == "codex -a never --add-dir '/repo/Debates/T_slug' --model 'gpt-5'"


def test_codex_without_model() -> None:
    # Scenario: codex without model.
    # Setup: empty model entry.
    current_model = {"codex": ""}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/X",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: no --model.
    assert cmd == "codex -a never --add-dir '/repo/Debates/X'"


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
