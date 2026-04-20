# Changelog

All notable changes to the jot plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-04-20

First public release. Ships two focus-preserving skills (`/jot` and `/plate`) under one plugin, with a unified orchestrator dispatcher, per-invocation tmux workers, and lifecycle-safe permission seeding.

### Added
- `/plate` skill — stack-of-plates WIP tracker with `/plate` / `--show` / `--next` / `--drop` / `--done` subcommands; snapshots uncommitted work as named git refs (`refs/plates/<convo>/<plate-N>`) without mutating branches
- Multi-pane tmux architecture for `/jot` — one dedicated pane per invocation inside a shared `jot:jots` window; multiple `/jot` calls can run concurrently without sharing state
- `scripts/orchestrator.sh` base dispatcher — single `UserPromptSubmit` hook entry point routes `/jot` and `/plate` to their per-skill orchestrators
- `common/scripts/` shared library tree — `tmux.sh`, `tmux-launcher.sh`, `invoke_command.sh`, `silencers.sh`, `git.sh`, `lock.sh`, `platform.sh`, `hook-json.sh`, `claude-launcher.sh`, `permissions-seed.sh`
- Namespaced python helpers — `common/scripts/jot/*.py`, `common/scripts/plate/*.py`
- `permissions_seed()` — three-state `permissions.default.json` seeding with SHA256 drift detection, shared by jot and plate
- Lifecycle-safe hooks — per-invocation tmpdir that copies SessionStart/Stop/SessionEnd scripts so `claude plugin update` can't yank them mid-run
- Binary-plate regression test in `tests/test-done-smoke.sh` — guards against the command-substitution corruption pattern (byte truncation + NUL intolerance)

### Changed
- Directory layout — skills moved under `skills/<skill>/scripts/`; shared libs moved under `common/scripts/`; legacy flat `scripts/` and `python/` retired
- `invoke_command.sh` split — `silencers.sh` now owns `hide_errors` / `hide_output`; `invoke_command.sh` keeps the command wrapper
- `/jot` worker launch — `build_claude_cmd` generalized into `common/scripts/claude-launcher.sh` so `/plate`'s background worker reuses the same launcher
- Orchestrator entry-point pattern — each skill has a thin `<skill>-orchestrator.sh` that sources `<skill>.sh` function definitions and calls `<skill>_main`

### Fixed
- `/plate --done` now applies binary plates correctly — uses a temp patch file instead of `$(git diff --binary)` command substitution, which was stripping trailing newlines and truncating on embedded NULs ("corrupt binary patch at line N")
- `/plate --done` now exits 0 cleanly — removed a broken `hide_errors FOO=bar python3 …` pattern in the resume-pointer tail; env-var prefixes don't survive `"$@"` expansion through a function wrapper, so that invocation was silently returning rc=127
- `/plate` push completes its user-visible `[plate] pushed` signal even when tmux can't attach in headless environments — nonfatal envelope moved into `push.sh` around the tmux-launch section only, so pre-durable failures (snapshot, stack-append, settings) still abort correctly
- `TMUX_LOCK` leak in `push.sh` — combined `trap … EXIT` now guarantees both `.push.lock` and `tmux-launch.lock` release even if tmux launch aborts (previously tests had to scrub stale locks manually)
- Eliminated `|| true` from `skills/plate/scripts/done.sh` and the `/plate` orchestrator path; suppression now explicit via `hide_output` / `hide_errors` or explicit `if !` guards
- `tmux send-keys` always splits text and Enter into separate calls (prevents partial-send timing bugs)
- Cross-invocation state contamination in `/jot` — each worker gets its own tmpdir and settings.json
- `permissions.default.json` patterns — relative paths now resolve under `~/.claude/projects/` correctly

### Known issues
- Raw `2>/dev/null` remains in a handful of spots (`plate_log_stack_trace` in `skills/plate/scripts/plate.sh`, a couple of `tests/test-done-smoke.sh` grep guards). These are outside the `common/scripts/` scope that `CODING_RULES.md` governs; follow-up in a future release.

[1.0.0]: https://github.com/matkatmusic/jot/releases/tag/v1.0.0
