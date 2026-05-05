---
name: debateRetry_main migration
description: /debate-retry hook entrypoint workspace pair written 2026-05-05; uses lex-max basename pick, ASCII '->' not Unicode arrow
type: project
---

debateRetry_main() ported from bash debate_retry_main (jot-plugin-orchestrator.sh L2636-2673).

**Why:** Part of the bash->Python monolith migration; one [PENDING] tag retired.

**How to apply:**
- Workspace files at `scripts/_migration_workspace/_tmp_debateRetry_main.py` and `_tmp_test_debateRetry_main.py`.
- Fallback imports: debate_initHookContext, debate_detectAvailableAgents, debate_anyLiveLock, debate_liveSession, debate_checkResumeFeasibility, debate_startOrResume from workspace; hookjson_emitBlock + hookjson_checkRequirements from monolith.
- Returns int 0 in all paths (caller decides exit). Bash had `exit 0` everywhere.
- Lex-max via `if ts > best_ts` matching bash `[[ "$ts" > "$best_ts" ]]`.
- ASCII '->' substituted for Unicode U+2192 in still-running message.
- Strips trailing newline when comparing invoking_transcript.txt content (bash `cat` preserves it; tests cover both forms).
