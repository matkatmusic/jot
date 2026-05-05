# Agent Memory Index

- [debate_tmuxOrchestrator migration](project_debate_tmuxOrchestrator.md) — workspace files written 2026-05-05; callees cleanup/daemon_main are workspace-fallback pending
- [debate_daemonMain migration](project_debate_daemonMain.md) — workspace pair written 2026-05-05; bash globals -> kwargs; all deps workspace-fallback pending merger
- [debate_launch migration](project_debate_launch.md) — thin wrapper (path resolve + Darwin Terminal guard + delegate to debate_main); migrated 2026-05-05
- [todo_main migration](project_todo_main.md) — workspace pair 2026-05-05; mkstemp replaces noclobber loop; hookjson deps have fallback shims
- [debate_main migration](project_debate_main.md) — /debate hook orchestrator; 7 workspace-fallback callees pending merge
