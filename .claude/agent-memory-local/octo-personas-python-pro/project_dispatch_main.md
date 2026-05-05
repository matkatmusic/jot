---
name: dispatch_main migration
description: argv + stdin dispatcher (lines 4117-4177); workspace pair 2026-05-05; 8 callees workspace-fallback pending
type: project
---

dispatch_main = unified entrypoint replacing the bash argv case + stdin prompt-routing case at the bottom of jot-plugin-orchestrator.sh (lines 4117-4177). Workspace pair written 2026-05-05.

**Why:** Final piece of the monolith dispatcher; once all callees merge into `jot_plugin_orchestrator.py`, this becomes the `if __name__ == "__main__"` body and replaces the bash `case "${1:-}" in ... esac` blocks.

**How to apply:**
- Argv map: 12 subcommands -> functions; all assumed merged (no try/except).
- Prompt map: 7 prefixes; each callee imported with try/except ImportError fallback to `_tmp_<name>.py` workspace shim. PENDING merge: jot_main, plate_main, todo_main, todoList_main, debate_launch, debateRetry_main, debateAbort_main, debate_tmuxOrchestrator.
- Prefix matching sorted by descending length so `/todo-list` beats `/todo` and `/debate-retry`/`/debate-abort` beat `/debate`.
- Stdin piping done by replacing `sys.stdin` with `io.StringIO(rewritten_json)` before calling each prompt entrypoint.
- `/jot:<skill>` normalises to `/<skill>` AND rewrites the JSON `.prompt` field via `json.dumps`.
