import sys
from pathlib import Path

repo_root = Path('/Users/matkatmusicllc/Programming/jot-worktrees/python-migration')
scripts_dir = repo_root / 'scripts'
workspace_dir = scripts_dir / '_migration_workspace'

# 1. Update jot_plugin_orchestrator.py
jot_py = scripts_dir / 'jot_plugin_orchestrator.py'
content = jot_py.read_text()

if 'from common.scripts.git_lib import' not in content:
    # insert after from typing import ...
    import_statement = "from common.scripts.git_lib import getGitBranchNameOrFail, getGitRecentCommitHashes, getGitUncommittedFilenames\n"
    content = content.replace("from typing import Callable, Optional, Sequence, Type\n", "from typing import Callable, Optional, Sequence, Type\n" + import_statement)

# Append functions
scanOpen_content = workspace_dir / '_tmp_todo_scanOpen.py'
launcher_content = workspace_dir / '_tmp_todo_launcher.py'

def extract_funcs(filepath):
    lines = filepath.read_text().splitlines()
    func_lines = []
    in_func = False
    for line in lines:
        if line.startswith('def ') or line.startswith('# Scan ') or line.startswith('# Mirrors ') or line.startswith('def _hide_errors'):
            in_func = True
        if in_func:
            func_lines.append(line)
    return '\n'.join(func_lines)

scan_funcs = extract_funcs(scanOpen_content)
launcher_funcs = extract_funcs(launcher_content)

content += "\n\n" + scan_funcs + "\n\n" + launcher_funcs + "\n"
jot_py.write_text(content)

# 2. Update test_monolith.py
test_py = scripts_dir / 'test_monolith.py'
test_content = test_py.read_text()

# Append imports to test_monolith if needed
# We need to make sure the imports in _tmp_test_todo_scanOpen.py and _tmp_test_todo_launcher.py are handled.
# Since we merge them into test_monolith.py, the calls to todo_scanOpen and todo_launcher should be imported from jot_plugin_orchestrator.

if 'todo_scanOpen' not in test_content:
    test_content = test_content.replace('from jot_plugin_orchestrator import (', 'from jot_plugin_orchestrator import (\n    todo_scanOpen,\n    todo_launcher,\n    _hide_errors,')

def extract_tests(filepath):
    lines = filepath.read_text().splitlines()
    test_lines = []
    in_test = False
    for line in lines:
        if line.startswith('def test_') or line.startswith('def _write('):
            in_test = True
        if in_test:
            # Fix imports / module refs
            if 'from _tmp_todo_scanOpen import todo_scanOpen' in line or 'from _migration_workspace import' in line:
                continue
            line = line.replace('_tmp_todo_scanOpen.', 'jot_plugin_orchestrator.')
            line = line.replace('_tmp_todo_launcher.', 'jot_plugin_orchestrator.')
            line = line.replace('from _migration_workspace._tmp_todo_launcher import todo_launcher', '')
            line = line.replace('from _migration_workspace._tmp_todo_scanOpen import todo_scanOpen', '')
            test_lines.append(line)
    return '\n'.join(test_lines)

scan_tests = extract_tests(workspace_dir / '_tmp_test_todo_scanOpen.py')
launcher_tests = extract_tests(workspace_dir / '_tmp_test_todo_launcher.py')

test_content += "\n\n" + scan_tests + "\n\n" + launcher_tests + "\n"
test_py.write_text(test_content)
