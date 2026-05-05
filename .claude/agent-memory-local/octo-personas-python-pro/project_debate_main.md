---
name: debate_main migration
description: workspace pair written 2026-05-05; orchestrates full /debate hook flow; depends on 7 other workspace-fallback callees
type: project
---

debate_main migrated to scripts/_migration_workspace/_tmp_debate_main.py + _tmp_test_debate_main.py.

**Why:** Bash debate_main() at L2567-2632 of jot-plugin-orchestrator.sh is the /debate slash-command hook orchestrator. Migrated as part of monolith bash -> Python rewrite tracked in plan it-is-time-to-jolly-blossom.md.

**How to apply:** When merging into jot_plugin_orchestrator.py, drop try/except ImportError fallback block. Replaces shell globals (PROMPT/TOPIC/DEBATE_DIR/RESUMING/AVAILABLE_AGENTS/REPO_ROOT/etc.) with locals fed by ctx dict from debate_initHookContext() + DetectResult dict. ASCII substitutions: em-dash -> ' - ', '->' -> '->', '>=' -> '>='. All seven debate_* callees still workspace-only; merge them first or together.
