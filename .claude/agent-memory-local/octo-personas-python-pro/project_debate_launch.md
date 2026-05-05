---
name: debate_launch migration
description: debate_launch migrated 2026-05-05; thin wrapper calling debate_main with Darwin Terminal.app guard
type: project
---

debate_launch (bash lines 3171-3190, jot-plugin-orchestrator.sh) migrated to Python 2026-05-05.

Function is a 3-step thin wrapper: resolve paths, optional Darwin Terminal.app launch via osascript (fire-and-forget), delegate to debate_main().

Workspace files:
- _tmp_debate_launch.py
- _tmp_test_debate_launch.py (6 tests, RELAXED_COVERAGE)

Workspace-fallback import: `debate_main` (from jot_plugin_orchestrator, stub if unavailable).

**Why:** No real logic -- just environment setup + OS guard + delegate. Tests cover delegation, Darwin/non-Darwin branching, ordering, env export.

**How to apply:** When merging, replace workspace-fallback import of debate_main with direct monolith import. PLUGIN_ROOT setdefault may conflict if monolith already sets it -- review before merge.
