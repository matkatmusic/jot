"""GREEN implementation of todo_launcher — Python port of bash todo_launcher."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Standard temp file header: keep workspace importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from jot_plugin_orchestrator import (
    claude_seedPermissions,
    claude_buildCmd,
    FileLock,
    tmux_ensureSession,
    tmux_splitWorkerPane,
    tmux_setPaneTitle,
    tmux_retile,
    terminal_spawnIfNeeded,
)
from common.scripts.git_lib import (
    getGitBranchNameOrFail,
    getGitRecentCommitHashes,
    getGitUncommittedFilenames,
)
from _migration_workspace._tmp_todo_scanOpen import todo_scanOpen

def _hide_errors(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return "(unavailable)"

def todo_launcher(session_id: str, idea: str, pending_file_path: str) -> int:
    if not session_id:
        print("todo_launcher: session_id required", file=sys.stderr)
        return 1
    if not idea:
        print("todo_launcher: refined idea required", file=sys.stderr)
        return 1
    if not pending_file_path:
        print("todo_launcher: pending_file path required", file=sys.stderr)
        return 1

    pending_file = Path(pending_file_path)
    if not pending_file.is_file():
        print(f"todo-launcher: pending file not found at {pending_file}", file=sys.stderr)
        return 1

    scripts_dir = Path(__file__).resolve().parent.parent
    plugin_root = scripts_dir.parent
    
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    claude_plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA", str(Path.home() / ".claude" / "plugins" / "data" / "jot-matkatmusic-jot"))
    os.environ["CLAUDE_PLUGIN_DATA"] = claude_plugin_data
    
    Path(claude_plugin_data).mkdir(parents=True, exist_ok=True)
    
    log_file = os.environ.get("TODO_LOG_FILE", str(Path(claude_plugin_data) / "todo-log.txt"))
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
        
    try:
        with open(pending_file, "r") as f:
            pending_data = json.load(f)
    except Exception as e:
        print(f"todo-launcher: failed to read pending file: {e}", file=sys.stderr)
        return 1
        
    repo_root = pending_data.get("repo_root", "")
    cwd = pending_data.get("cwd", "")
    transcript_path = pending_data.get("transcript_path", "")
    timestamp = pending_data.get("timestamp", "")
    
    state_dir = Path(repo_root) / "Todos" / ".todo-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "audit.log").touch(exist_ok=True)
    
    # Phase 1
    target_dir = Path(repo_root) / "Todos"
    target_dir.mkdir(parents=True, exist_ok=True)
    input_file = target_dir / f"{timestamp}_input.txt"
    input_abs = str(input_file)
    
    branch = _hide_errors(getGitBranchNameOrFail, Path(cwd))
    commits_list = _hide_errors(getGitRecentCommitHashes, Path(cwd))
    commits = "\n".join(commits_list) if isinstance(commits_list, list) else commits_list
    uncommitted_list = _hide_errors(getGitUncommittedFilenames, Path(cwd))
    uncommitted = "\n".join(uncommitted_list) if isinstance(uncommitted_list, list) else uncommitted_list
    
    open_todos_list = _hide_errors(todo_scanOpen, repo_root)
    open_todos = "\n".join(open_todos_list) if isinstance(open_todos_list, list) else open_todos_list
    
    if transcript_path and Path(transcript_path).is_file():
        try:
            result = subprocess.run(
                ["python3", str(plugin_root / "skills" / "jot" / "scripts" / "capture-conversation.py"), transcript_path],
                capture_output=True, text=True, check=True
            )
            conversation = result.stdout.strip()
        except subprocess.CalledProcessError:
            conversation = "(unavailable)"
    else:
        conversation = "No conversation history available."
        
    try:
        env = os.environ.copy()
        env.update({
            "REPO_ROOT": repo_root,
            "TIMESTAMP": timestamp,
            "BRANCH": branch,
            "INPUT_ABS": input_abs
        })
        result = subprocess.run(
            ["python3", str(plugin_root / "common" / "scripts" / "jot" / "render_template.py"),
             str(scripts_dir / "assets" / "todo-instructions.md"),
             "REPO_ROOT", "TIMESTAMP", "BRANCH", "INPUT_ABS"],
            capture_output=True, text=True, check=True, env=env
        )
        instructions = result.stdout.strip()
    except Exception:
        instructions = "(unavailable)"
        
    input_content = f"""# Todo Task

## Instructions
{instructions}

## Idea
{idea}

## Working Directory
{cwd}

## Git State
- Branch: {branch}
- Commits: {commits}
- Uncommitted: {uncommitted}

## Open TODO Files
{open_todos}

## Transcript Path
{transcript_path or '(none)'}

## Recent Conversation
{conversation}
"""
    input_file.write_text(input_content)
    
    # Phase 2
    tmpdir_inv = Path(tempfile.mkdtemp(prefix="todo."))
    settings_file = tmpdir_inv / "settings.json"
    
    import shutil
    shutil.copy2(plugin_root / "scripts" / "jot-plugin-orchestrator.sh", tmpdir_inv / "jot-plugin-orchestrator.sh")
    
    permissions_file = Path(claude_plugin_data) / "todo-permissions.local.json"
    default_file = scripts_dir / "assets" / "permissions.default.json"
    default_sha_file = scripts_dir / "assets" / "permissions.default.json.sha256"
    prior_sha_file = Path(claude_plugin_data) / "todo-permissions.default.sha256"
    
    claude_seedPermissions(
        str(permissions_file), str(default_file), str(default_sha_file), str(prior_sha_file), log_file, "todo"
    )
    
    try:
        env = os.environ.copy()
        env.update({"CWD": cwd, "HOME": str(Path.home()), "REPO_ROOT": repo_root})
        result = subprocess.run(
            ["python3", str(plugin_root / "common" / "scripts" / "jot" / "expand_permissions.py"), str(permissions_file)],
            capture_output=True, text=True, check=True, env=env
        )
        allow_json = result.stdout.strip()
    except Exception:
        allow_json = "{}"
        
    hooks_json_file = tmpdir_inv / "hooks.json"
    hooks_data = {
        "SessionStart": [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-session-start '{input_file}' '{tmpdir_inv}'"}]}],
        "Stop":         [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-stop '{input_file}' '{tmpdir_inv}' '{state_dir}'"}]}],
        "SessionEnd":   [{"hooks": [{"type": "command", "command": f"bash {tmpdir_inv}/jot-plugin-orchestrator.sh todo-session-end '{tmpdir_inv}'"}]}]
    }
    hooks_json_file.write_text(json.dumps(hooks_data))
    
    claude_cmd = claude_buildCmd(str(settings_file), allow_json, str(hooks_json_file), cwd, repo_root)
    
    # Phase 3
    tmux_lock_file = Path(claude_plugin_data) / "todo-tmux-launch.lock"
    try:
        with FileLock(str(tmux_lock_file), timeout=10):
            counter_file = Path(claude_plugin_data) / "todo-pane-counter.txt"
            try:
                n = int(counter_file.read_text().strip())
            except Exception:
                n = 0
            n = (n % 20) + 1
            counter_file.write_text(f"{n}\n")
            pane_label = f"todo{n}"
            
            keepalive_cmd = 'exec sh -c \'trap "" INT HUP TERM; printf "[todo keepalive — do not kill]\\n"; exec tail -f /dev/null\''
            tmux_ensureSession("todo", "todos", cwd, keepalive_cmd, 'todo: keepalive')
            
            pane_id = tmux_splitWorkerPane("todo:todos", cwd, claude_cmd)
            if not pane_id:
                print("todo-launcher: tmux split-window returned empty pane id", file=sys.stderr)
                return 1
                
            (tmpdir_inv / "tmux_target.tmp").write_text(f"{pane_id}\n")
            (tmpdir_inv / "tmux_target.tmp").rename(tmpdir_inv / "tmux_target")
            
            tmux_setPaneTitle(pane_id, pane_label)
            tmux_retile("todo:todos")
            
    except Exception as e:
        # Fallback to catching all exceptions if LockTimeout not exported correctly
        print("todo-launcher: failed to acquire tmux-launch lock", file=sys.stderr)
        return 1
        
    terminal_spawnIfNeeded("todo", log_file, "todo")
    return 0
