#!/usr/bin/env python3
"""Tests for workspace `jot_main` migration.

RELAXED_COVERAGE: workspace draft pending merger.
One behavior per test; mocks subprocess + sys.stdin + env + fs (tmp_path).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure workspace and scripts dirs are importable.
WORKSPACE = Path(__file__).resolve().parent
SCRIPTS = WORKSPACE.parent
for p in (str(WORKSPACE), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _tmp_jot_main as mod  # noqa: E402


# --------- shared fixtures ---------

@pytest.fixture
def base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    # Setup: minimal valid plugin env + scratch log.
    plugin_root = tmp_path / "plugin"
    plugin_data = tmp_path / "data"
    plugin_root.mkdir()
    plugin_data.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    monkeypatch.setenv("JOT_LOG_FILE", str(tmp_path / "jot.log"))
    monkeypatch.delenv("JOT_SKIP_LAUNCH", raising=False)
    return {
        "plugin_root": str(plugin_root),
        "plugin_data": str(plugin_data),
        "tmp": str(tmp_path),
    }


def _stub_passing_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup: bypass real tool checks + tmux probe.
    monkeypatch.setattr(mod, "hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(mod, "tmux_requireVersion", lambda _m: 0)


def _stdin(monkeypatch: pytest.MonkeyPatch, payload: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))


# --------- tests ---------

def test_missing_plugin_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Scenario: harness env vars unset.
    # Setup: clear both vars, stdin irrelevant.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    _stdin(monkeypatch, "")
    # Test action + verification: jot_main raises RuntimeError.
    with pytest.raises(RuntimeError):
        mod.jot_main()


def test_non_jot_input_exits_zero_silently(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: stdin lacks the "/jot" substring; hook should no-op.
    # Setup: arbitrary non-jot payload.
    _stdin(monkeypatch, '{"prompt": "/other thing"}')
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0, no JSON emitted.
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_prompt_not_strict_jot_exits_zero(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: payload contains "/jot" substring but prompt is "/jotsomething" (not strict /jot).
    # Setup: stdin with substring-but-not-prefix.
    _stub_passing_deps(monkeypatch)
    _stdin(monkeypatch, json.dumps({"prompt": "/jotsomething"}))
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0 with no block emission (strict-prefix branch).
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_empty_idea_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: prompt is bare "/jot" with no idea.
    # Setup: stub deps, stdin with bare /jot.
    _stub_passing_deps(monkeypatch)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot"}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + block decision mentioning "no idea provided".
    assert rc == 0
    assert "no idea provided" in out


def test_missing_repo_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Scenario: cwd is not inside a git repo.
    # Setup: stub deps; force `git rev-parse` to fail.
    _stub_passing_deps(monkeypatch)
    non_repo = tmp_path / "norepo"
    non_repo.mkdir()
    _stdin(monkeypatch, json.dumps({"prompt": "/jot make thing", "cwd": str(non_repo)}))

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + git-required block.
    assert rc == 0
    assert "requires a git repository" in out


def test_tmux_too_old_emits_block(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: tmux_requireVersion("2.9") returns nonzero.
    # Setup: stub checkRequirements OK, tmux_requireVersion fail.
    monkeypatch.setattr(mod, "hookjson_checkRequirements", lambda *a, **k: None)
    monkeypatch.setattr(mod, "tmux_requireVersion", lambda _m: 1)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot something"}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: rc=0 + tmux block.
    assert rc == 0
    assert "tmux 2.9+" in out


def test_happy_path_writes_input_file_with_all_sections(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: full happy path produces a Todos/<ts>_input.txt with all sections.
    # Setup: stub deps + stub git_lib + stub launch + stub render/capture subprocess.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr(mod, "getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", lambda c: "abc123 init")
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", lambda c: "M file.py")
    monkeypatch.setattr(mod, "todo_scanOpen", lambda r: "todo1\ntodo2")
    launched = {"called": False}

    def fake_launch() -> int:
        launched["called"] = True
        return 0

    monkeypatch.setattr(mod, "jot_launchPhase2Window", fake_launch)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        # git rev-parse: return repo path; render_template: return canned text.
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        if "render_template.py" in " ".join(str(c) for c in cmd):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="RENDERED-INSTRUCTIONS", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot fix the bug", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0, exactly one input file with expected sections.
    assert rc == 0
    files = list((repo / "Todos").glob("*_input.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "## Instructions\nRENDERED-INSTRUCTIONS" in text
    assert "## Idea\nfix the bug" in text
    assert "Branch: main" in text
    assert "Commits: abc123 init" in text
    assert "Uncommitted: M file.py" in text
    assert "## Open TODO Files\ntodo1\ntodo2" in text
    assert "(no transcript available)" in text


def test_skip_launch_does_not_call_phase2(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: JOT_SKIP_LAUNCH=1 path emits "(launch skipped)" and skips phase2.
    # Setup: full happy stubs + skip flag.
    _stub_passing_deps(monkeypatch)
    monkeypatch.setenv("JOT_SKIP_LAUNCH", "1")
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr(mod, "getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", lambda c: "")
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", lambda c: "")
    monkeypatch.setattr(mod, "todo_scanOpen", lambda r: "")
    launched = {"called": False}
    monkeypatch.setattr(mod, "jot_launchPhase2Window", lambda: launched.__setitem__("called", True) or 0)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="X", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot do thing", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 NOT called, block-decision contains "(launch skipped)".
    assert rc == 0
    assert launched["called"] is False
    assert "launch skipped" in out


def test_phase2_called_on_happy_path(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Scenario: happy path without JOT_SKIP_LAUNCH calls jot_launchPhase2Window exactly once.
    # Setup: same as happy-path test but track call count.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)
    monkeypatch.setattr(mod, "getGitBranchNameOrFail", lambda c: "main")
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", lambda c: "")
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", lambda c: "")
    monkeypatch.setattr(mod, "todo_scanOpen", lambda r: "")
    calls = {"n": 0}

    def fake_launch() -> int:
        calls["n"] += 1
        return 0

    monkeypatch.setattr(mod, "jot_launchPhase2Window", fake_launch)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot launch me", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    out = capsys.readouterr().out
    # Test verification: phase2 called once, success block emitted.
    assert rc == 0
    assert calls["n"] == 1
    assert "Done! Jotted idea in" in out


def test_safe_wrapper_falls_back_to_unavailable(
    base_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Scenario: git_lib helpers raise; the input file should record "(unavailable)".
    # Setup: stub all git_lib funcs to raise; stub launch + render.
    _stub_passing_deps(monkeypatch)
    repo = tmp_path / "repo"
    (repo / "Todos").mkdir(parents=True)

    def boom(*_: object) -> str:
        raise RuntimeError("nope")

    monkeypatch.setattr(mod, "getGitBranchNameOrFail", boom)
    monkeypatch.setattr(mod, "getGitRecentCommitHashes", boom)
    monkeypatch.setattr(mod, "getGitUncommittedFilenames", boom)
    monkeypatch.setattr(mod, "todo_scanOpen", boom)
    monkeypatch.setattr(mod, "jot_launchPhase2Window", lambda: 0)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=str(repo) + "\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="INSTR", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    _stdin(monkeypatch, json.dumps({"prompt": "/jot recover", "cwd": str(repo)}))
    # Test action: invoke.
    rc = mod.jot_main()
    # Test verification: rc=0 + every safe-wrapped value rendered as "(unavailable)".
    assert rc == 0
    files = list((repo / "Todos").glob("*_input.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "Branch: (unavailable)" in text
    assert "Commits: (unavailable)" in text
    assert "Uncommitted: (unavailable)" in text
    assert "## Open TODO Files\n(unavailable)" in text
