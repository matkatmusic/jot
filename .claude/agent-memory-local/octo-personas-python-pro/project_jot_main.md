---
name: jot_main migration
description: workspace migration of bash jot_main entrypoint to Python (lines 1904-2009 of jot-plugin-orchestrator.sh)
type: project
---

Workspace migration of bash `jot_main` entrypoint to Python written 2026-05-05.

**Why:** Part of monolith migration (see `MIGRATION_TO_PYTHON.md` and plan `it-is-time-to-jolly-blossom.md`); `jot_main` is the user-facing PreToolUse hook for `/jot`.

**How to apply:** Files at `scripts/_migration_workspace/_tmp_jot_main.py` and `_tmp_test_jot_main.py`. Pending merger into `scripts/jot_plugin_orchestrator.py`. Workspace fallback used for `todo_scanOpen` (in-flight); git_lib has subprocess fallback because canonical import path not yet wired into orchestrator. `jot_launchPhase2Window` reads via `os.environ` so the entrypoint sets REPO_ROOT/CWD/INPUT_FILE/LOG_FILE in env before calling. Bash `safe` wrapper replicated as local `_safe_call` returning "(unavailable)".
