# Agent Memory Index

- [debate_tmuxOrchestrator migration](project_debate_tmuxOrchestrator.md) — workspace files written 2026-05-05; callees cleanup/daemon_main are workspace-fallback pending
- [debate_daemonMain migration](project_debate_daemonMain.md) — workspace pair written 2026-05-05; bash globals -> kwargs; all deps workspace-fallback pending merger
- [debate_launch migration](project_debate_launch.md) — thin wrapper (path resolve + Darwin Terminal guard + delegate to debate_main); migrated 2026-05-05
- [todo_main migration](project_todo_main.md) — workspace pair 2026-05-05; mkstemp replaces noclobber loop; hookjson deps have fallback shims
- [debate_main migration](project_debate_main.md) — /debate hook orchestrator; 7 workspace-fallback callees pending merge
- [jot_main migration](project_jot_main.md) — /jot PreToolUse hook entrypoint; workspace pair 2026-05-05; jot_launchPhase2Window invoked via os.environ surface
- [debateAbort_main migration](project_debateAbort_main.md) - /debate-abort hook; workspace pair 2026-05-05; rmtree on happy path; lex-max tie-break
- [dispatch_main migration](project_dispatch_main.md) - argv + stdin dispatcher (4117-4177); workspace pair 2026-05-05; 8 callees workspace-fallback pending
- [debateRetry_main migration](project_debateRetry_main.md) - /debate-retry hook; workspace pair 2026-05-05; lex-max basename pick; ASCII '->' arrow
