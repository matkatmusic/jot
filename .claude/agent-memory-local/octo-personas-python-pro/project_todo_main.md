---
name: todo_main migration
description: Workspace migration of bash todo_main entrypoint to Python; pending-file claim via tempfile.mkstemp
type: project
---

todo_main workspace pair written 2026-05-05 under scripts/_migration_workspace/.

Why: PreToolUse `/todo` hook entrypoint; bash mktemp -u + set -C noclobber loop replaced with `tempfile.mkstemp(prefix='pending-', suffix='.json', dir=state_dir)` for atomic claim.

How to apply: hookjson_emitBlock + hookjson_checkRequirements remain workspace-fallback (referenced via raising=False monkeypatches in tests) pending merge into jot_plugin_orchestrator.py. No emit_block on success path - fg claude dispatches the skill from the pending file.
