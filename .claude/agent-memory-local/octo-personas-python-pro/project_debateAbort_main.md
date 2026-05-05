---
name: debateAbort_main migration
description: /debate-abort hook entrypoint; workspace pair 2026-05-05; mirrors bash debate_abort_main with rmtree happy-path
type: project
---

debateAbort_main workspace pair written 2026-05-05.

**Why:** Python migration of bash `debate_abort_main` (jot-plugin-orchestrator.sh:2677-2702) per migration plan it-is-time-to-jolly-blossom.

**How to apply:**
- Files: `scripts/_migration_workspace/_tmp_debateAbort_main.py` + `_tmp_test_debateAbort_main.py`.
- Deps: try monolith `jot_plugin_orchestrator` first; fall back to `_tmp_debate_initHookContext`, `_tmp_debate_anyLiveLock`, `_tmp_debate_liveSession`. Last-ditch shims for hookjson_* prevent collection-time ImportError.
- Bash `[[ "$ts" > "$best_ts" ]]` ported as Python `str > str` (Unicode codepoint order; OK for ASCII timestamp basenames).
- Returns int (0 on every branch) instead of `exit 0`.
- All branches covered by 7 tests; tmux/git side-effects mocked.
