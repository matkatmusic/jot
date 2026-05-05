---
name: debate_tmuxOrchestrator migration
description: Workspace migration of debate_tmux_orchestrator bash function; callees pending
type: project
---

debate_tmuxOrchestrator workspace written 2026-05-05. Bash source: jot-plugin-orchestrator.sh lines 3150-3165.

**Why:** Part of ongoing bash-to-Python migration (one function per TDD loop).

**How to apply:** When merging, promote DebateContext + debate_tmuxOrchestrator to jot_plugin_orchestrator.py. Remove workspace-fallback try/except once cleanup and daemon_main are also migrated.

Workspace-fallback imports needed for merging Claude:
- cleanup (bash line ~3008, [PENDING])
- daemon_main (bash lines 3055-3144, [PENDING])
