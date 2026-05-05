"""RED tests for todo_launcher migration of bash todo_launcher."""
from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

# Standard temp file header: keep workspace importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from _migration_workspace import _tmp_todo_launcher

def test_todo_launcher_success(monkeypatch, tmp_path):
    # Scenario: standard execution successfully creates inputs, cmds, and tmux window
    # Setup: mock all external calls and dependencies
    session_id = "test-session"
    idea = "fix a bug"
    pending_file = tmp_path / "pending.json"
    repo_root = tmp_path / "repo"
    cwd = repo_root / "src"
    transcript_path = tmp_path / "transcript.txt"
    
    repo_root.mkdir(parents=True)
    cwd.mkdir(parents=True)
    transcript_path.write_text("transcript content")
    
    pending_data = {
        "repo_root": str(repo_root),
        "cwd": str(cwd),
        "transcript_path": str(transcript_path),
        "timestamp": "20260101-120000"
    }
    pending_file.write_text(json.dumps(pending_data))
    
    calls = []
    
    import common.scripts.git_lib as git_lib
    from _migration_workspace import _tmp_todo_scanOpen
    
    monkeypatch.setattr(git_lib, "getGitBranchNameOrFail", lambda p: "main-branch")
    monkeypatch.setattr(git_lib, "getGitRecentCommitHashes", lambda p: ["commit1", "commit2"])
    monkeypatch.setattr(git_lib, "getGitUncommittedFilenames", lambda p: ["file1.txt"])
    monkeypatch.setattr(_tmp_todo_scanOpen, "todo_scanOpen", lambda p: [str(repo_root / "Todos" / "todo1.md")])
    
    def mock_run(cmd, *args, **kwargs):
        calls.append(["run", cmd[0] if isinstance(cmd, list) else cmd])
        class MockResult:
            returncode = 0
            stdout = "mock stdout output\n"
        return MockResult()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(_tmp_todo_launcher.subprocess, "run", mock_run)
    
    monkeypatch.setattr(_tmp_todo_launcher, "claude_seedPermissions", lambda *args: calls.append(["claude_seedPermissions"]))
    monkeypatch.setattr(_tmp_todo_launcher, "claude_buildCmd", lambda *args: "mock claude cmd")
    
    class MockFileLock:
        def __init__(self, path, timeout):
            pass
        def __enter__(self):
            calls.append(["lock_acquire"])
            return self
        def __exit__(self, *args):
            calls.append(["lock_release"])
            
    monkeypatch.setattr(_tmp_todo_launcher, "FileLock", MockFileLock)
    
    monkeypatch.setattr(_tmp_todo_launcher, "tmux_ensureSession", lambda *args: calls.append(["tmux_ensureSession"]))
    monkeypatch.setattr(_tmp_todo_launcher, "tmux_splitWorkerPane", lambda *args: "%123")
    monkeypatch.setattr(_tmp_todo_launcher, "tmux_setPaneTitle", lambda *args: calls.append(["tmux_setPaneTitle"]))
    monkeypatch.setattr(_tmp_todo_launcher, "tmux_retile", lambda *args: calls.append(["tmux_retile"]))
    monkeypatch.setattr(_tmp_todo_launcher, "terminal_spawnIfNeeded", lambda *args: calls.append(["terminal_spawnIfNeeded"]))
    
    # Test action:
    result = _tmp_todo_launcher.todo_launcher(session_id, idea, str(pending_file))

    # Test verification:
    assert result == 0
    assert ["claude_seedPermissions"] in calls
    assert ["lock_acquire"] in calls
    assert ["tmux_ensureSession"] in calls
    assert ["tmux_setPaneTitle"] in calls
    assert ["tmux_retile"] in calls
    assert ["terminal_spawnIfNeeded"] in calls
