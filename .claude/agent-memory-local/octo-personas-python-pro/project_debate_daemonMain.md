---
name: debate_daemonMain migration
description: workspace files written 2026-05-05; bash globals replaced with explicit kwargs; all deps workspace-fallback pending merger
type: project
---

debate_daemonMain migrated 2026-05-05 as workspace pair.

**Why:** daemon_main was the last callee of debate_tmuxOrchestrator still in bash; all its own deps are also workspace-fallback.

**How to apply:** when merging, swap all _tmp_ imports for their package paths; remove try/except ImportError blocks. Synthesis short-circuit uses Path.stat().st_size > 0. Drift wipe uses Path.unlink(missing_ok=True).
