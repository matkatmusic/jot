# Migration Name Map

Audit trail for the bash-to-Python migration of `scripts/jot-plugin-orchestrator.sh` -> `scripts/jot-plugin-orchestrator.py`. See `/Users/matkatmusicllc/.claude/plans/it-is-time-to-jolly-blossom.md` for the full plan.

## Naming Convention (binding)

`domain_behaviorUsingCamelCase`

- `domain` is a lowercase subsystem prefix: `tmux`, `git`, `jot`, `plate`, `debate`, `todo`, `todoList`, `hookjson`, `claude`, `terminal`, `shell`, etc.
- An underscore separates domain from behavior.
- `behaviorUsingCamelCase` is camelCase starting lowercase, expressing the action as a verb phrase.
- Entrypoint `*_main` functions keep `_main` (e.g. `jot_main`, `plate_main`).

## Tag Legend

- `MIGRATE` - translated to a real Python function via Red-Yellow-Green TDD.
- `ABSORBED` - bash-only idiom; not translated as a function; replaced inline at each call site.
- `IMPORT_FROM_GIT_LIB` - already exists in `common/scripts/git_lib.py`; orchestrator imports from there.
- `COVERED_BY_GIT_LIB_TESTS` - bash test already covered in `tests/test_git_lib.py`; not ported.
- `TEST` - pytest function in `scripts/test_monolith.py`; not in production surface; not in this map.
- `RELAXED_COVERAGE` - notes-column flag indicating the pytest test was authored from spec/docstring rather than ported from an existing bash `_tests` function (because none existed for that function).

## Map

| python_name | bash_name | signature | notes | date |
|---|---|---|---|---|
| ABSORBED | hide_output | `hide_output cmd...` | Replace each call with `subprocess.run(..., stdout=subprocess.DEVNULL)` | 2026-05-04 |
| ABSORBED | hide_errors | `hide_errors cmd...` | Replace each call with `subprocess.run(..., stderr=subprocess.DEVNULL)` or try/except | 2026-05-04 |
| ABSORBED | invoke_command | `invoke_command cmd...` | Replace each call with `subprocess.run(..., check=True, capture_output=True, text=True)` + try/except logging caller via `sys._getframe(1).f_code.co_name` | 2026-05-04 |
| hookjson_emitBlock | emit_block | `(reason: str) -> str` | RELAXED_COVERAGE; idiomatic json.dumps replaces jq+hand-roll fallback | 2026-05-04 |
| hookjson_installHint | _hookjson_install_hint | `(cmd: str) -> str` | RELAXED_COVERAGE; dict.get replaces bash case | 2026-05-04 |
| hookjson_checkRequirements | check_requirements | `(prefix: str, *cmds: str) -> None` | RELAXED_COVERAGE; uses shutil.which, sys.exit(0) on missing | 2026-05-04 |
| tmux_requireVersion | tmux_require_version | `(minimum: str) -> int` | RELAXED_COVERAGE; tuple compare on M.m parts | 2026-05-04 |
| tmux_setOption | tmux_set_option | `(*args: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom (subprocess + caller logging) | 2026-05-04 |
| tmux_setOptionForTarget | tmux_set_option_t | `(target: str, name: str, value: str) -> int` | RELAXED_COVERAGE; thin wrapper passes -t flag | 2026-05-04 |
| tmux_setOptionGlobally | tmux_set_option_g | `(name: str, value: str) -> int` | RELAXED_COVERAGE; thin wrapper passes -g flag | 2026-05-04 |
| tmux_setOptionForWindow | tmux_set_option_w | `(window_target: str, name: str, value: str) -> int` | RELAXED_COVERAGE; thin wrapper passes -w -t flags | 2026-05-04 |
| tmux_hasSession | tmux_has_session | `(session_name: str) -> int` | RELAXED_COVERAGE; suppresses stderr log on rc=1 (normal absent) | 2026-05-04 |
| tmux_newSession | tmux_new_session | `(session_name: str, *extra_args: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_killSession | tmux_kill_session | `(session_name: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_listClients | tmux_list_clients | `(session_name: str) -> list[str]` | RELAXED_COVERAGE; signature change: returns list[str] instead of printing+rc; empty list on failure | 2026-05-04 |
| tmux_newPane | tmux_new_pane | `(target: str, *extra_args: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom; preserves stdout-passthrough so -P flow works | 2026-05-04 |
| tmux_killPane | tmux_kill_pane | `(pane_target: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_capturePane | tmux_capture_pane | `(pane_target: str, scrollback_lines: int \| None = None) -> str` | RELAXED_COVERAGE; signature change: returns captured text instead of printing+rc; "" on failure | 2026-05-04 |
| tmux_listPanes | tmux_list_panes | `(target: str, *extra_args: str) -> list[str]` | RELAXED_COVERAGE; signature change: returns list[str]; default -F when no extras | 2026-05-04 |
| tmux_selectPane | tmux_select_pane | `(pane_target: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_setPaneTitle | tmux_set_pane_title | `(pane_target: str, title: str) -> int` | RELAXED_COVERAGE; uses select-pane -T (bash convention) | 2026-05-04 |
| tmux_newWindow | tmux_new_window | `(session_name: str, window_name: str, *extra_args: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_killWindow | tmux_kill_window | `(window_target: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_listWindows | tmux_list_windows | `(session_name: str, *extra_args: str) -> list[str]` | RELAXED_COVERAGE; signature change: returns list[str]; default -F when no extras | 2026-05-04 |
| tmux_windowExists | tmux_window_exists | `(session_name: str, window_name: str) -> int` | RELAXED_COVERAGE; uses tmux_listWindows + exact-match in-list check (replaces grep -qx) | 2026-05-04 |
| tmux_paneHasTitle | tmux_pane_has_title | `(target: str, title: str) -> int` | RELAXED_COVERAGE; uses tmux_listPanes + exact-match check (replaces grep -qx) | 2026-05-04 |
| tmux_splitWindow | tmux_split_window | `(target: str, direction: str) -> int` | RELAXED_COVERAGE; validates direction (h/v) with ValueError on invalid; inlines invoke_command idiom | 2026-05-04 |
| tmux_selectLayout | tmux_select_layout | `(target: str, layout: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_retile | tmux_retile | `(target: str) -> int` | RELAXED_COVERAGE; thin wrapper passes "tiled" to tmux_selectLayout | 2026-05-04 |
| tmux_sendKeys | tmux_send_keys | `(pane_target: str, text: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_sendEnter | tmux_send_enter | `(pane_target: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom | 2026-05-04 |
| tmux_sendCtrlC | tmux_send_Ctrl_c | `(pane_target: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom; sends literal "C-c" token | 2026-05-04 |
| tmux_sendAndSubmit | tmux_send_and_submit | `(pane_target: str, text: str) -> int` | RELAXED_COVERAGE; calls tmux_sendKeys + time.sleep(0.5) + tmux_sendEnter; short-circuits on first failure | 2026-05-04 |
| claude_buildCmd | build_claude_cmd | `(settings_out: str, allow_json: str, hooks_json_file: str, cwd: str, *extra_dirs: str) -> str` | RELAXED_COVERAGE; writes settings JSON with raw allow_json + hooks block; returns `claude --settings ... --add-dir ...` cmd string with trailing newline | 2026-05-04 |
| tmux_cancelAndSend | tmux_cancel_and_send | `(pane_target: str, text: str, label: str \| None = None) -> int` | RELAXED_COVERAGE; up to 5 Ctrl-C retries; logs label + Ctrl-C count when retry needed; deviates from bash off-by-one in count display (Python prints actual count, bash printed count+1 due to attempt++ placement) | 2026-05-04 |
| tmux_ensureKeepalivePane | tmux_ensure_keepalive_pane | `(target: str, cwd: str, keepalive_cmd: str, title: str) -> None` | RELAXED_COVERAGE; uses migrated `tmux_splitWorkerPane` to get pane id because `tmux_newPane` returns rc in Python | 2026-05-04 |
| tmux_ensureSession | tmux_ensure_session | `(session: str, window: str, cwd: str, keepalive_cmd: str, keepalive_title: str) -> int` | RELAXED_COVERAGE; uses explicit tmux rc checks (`0` exists/success, nonzero absent/failure) | 2026-05-04 |
| tmux_splitWorkerPane | tmux_split_worker_pane | `(target: str, cwd: str, cmd: str) -> str \| None` | RELAXED_COVERAGE; signature change: returns pane id string (or None) instead of bash printf+rc; inlines subprocess.run because tmux_newPane returns rc not stdout | 2026-05-04 |
| tmux_waitForClaudeReadiness | tmux_wait_for_claude_readiness | `(pane_id: str, timeout: int = 10) -> int` | RELAXED_COVERAGE; polls tmux_capturePane every 0.5s up to timeout*2 attempts; ready glyph ❯; returns 0 on detect, 1 on timeout; capture errors swallowed | 2026-05-04 |
| jot_initState | jot_state_init | `(state_dir: str \| Path) -> None` | RELAXED_COVERAGE; mkdir parents=True exist_ok=True + touch three tracked files; idempotent | 2026-05-04 |
| jot_popFirstFromQueue | jot_queue_pop_first | `(state_dir: str \| Path) -> str \| None` | RELAXED_COVERAGE; signature change: returns popped line (or None) instead of bash printed line + rc; caller must hold queue lock | 2026-05-04 |
| jot_sendPrompt | jot_send_prompt | `(pane_target: str, input_file_path: str) -> int` | RELAXED_COVERAGE; thin delegate to tmux_sendAndSubmit with composed "Read X and follow..." prompt | 2026-05-04 |
| jot_rotateAudit | jot_audit_rotate | `(audit_log: str \| Path, max_lines: int = 1000) -> None` | RELAXED_COVERAGE; missing-file no-op; bounded-deque tail trim + atomic os.replace; no .trim sidecar persists | 2026-05-04 |
| shell_runWithTimeout | _run_with_timeout | `(secs: float, argv: Sequence[str]) -> int` | RELAXED_COVERAGE; subprocess.Popen + start_new_session; SIGTERM->1s grace->SIGKILL via os.killpg; `_run_with_timeout` lifted from debate cluster to shell domain per plan | 2026-05-04 |
| claude_permseedLog | _permseed_log | `(message: str, log_file: str \| None, log_prefix: str = "plugin") -> None` | RELAXED_COVERAGE; bash dynamic-scoping ($log_file/$log_prefix from caller) replaced with explicit params (Risk #4); ISO-8601 timestamp; write errors swallowed | 2026-05-04 |
| claude_seedPermissions | permissions_seed | `(installed: str, default: str, default_sha_file: str, prior_sha_file: str, log_file: str \| None = None, log_prefix: str = "plugin") -> None` | RELAXED_COVERAGE; SHA-driven seed/upgrade logic; preserves user-edited installed permissions and records prior default SHA | 2026-05-04 |
| git_lib.isGitRepo | git_is_repo | `(directory)` | IMPORT_FROM_GIT_LIB; existing implementation in `common/scripts/git_lib.py` | 2026-05-04 |
| git_lib.getGitRepoRoot | git_get_repo_root | `(directory = ".")` | IMPORT_FROM_GIT_LIB; existing implementation in `common/scripts/git_lib.py` | 2026-05-04 |
| git_lib.getGitBranchNameOrFail | git_get_branch_name | `(directory)` | IMPORT_FROM_GIT_LIB; existing implementation in `common/scripts/git_lib.py` | 2026-05-04 |
| git_lib.getGitRecentCommitHashes | git_get_recent_commits | `(directory)` | IMPORT_FROM_GIT_LIB; existing implementation in `common/scripts/git_lib.py` | 2026-05-04 |
| git_lib.getGitUncommittedFilenames | git_get_uncommitted | `(directory)` | IMPORT_FROM_GIT_LIB; existing implementation in `common/scripts/git_lib.py` | 2026-05-04 |
| git_lib.ensureGitignoreEntry | git_ensure_gitignore_entry | `(repo_root, pattern)` | IMPORT_FROM_GIT_LIB; existing implementation in `common/scripts/git_lib.py` | 2026-05-04 |
| terminal_spawnIfNeeded | spawn_terminal_if_needed | `(session: str, log_file: str = "/dev/null", log_prefix: str = "tmux", maximize: str = "") -> int` | RELAXED_COVERAGE; uses sys.platform for Darwin detection; spawns osascript only when no tmux clients are attached; advisory writes are best-effort | 2026-05-04 |
| ABSORBED | lock_acquire | `lock_acquire lock_dir [timeout_seconds] [stale_after_seconds]` | Replaced by `with FileLock(path, timeout=...)`; fcntl lock auto-release subsumes stale-lock sweep | 2026-05-04 |
| ABSORBED | lock_release | `lock_release lock_dir` | Replaced by `FileLock.release()` / context-manager exit | 2026-05-04 |
| ABSORBED | jot_lock_acquire | `jot_lock_acquire ...` | Thin alias absorbed into the same `with FileLock(path, timeout=...)` idiom | 2026-05-04 |
| ABSORBED | jot_lock_release | `jot_lock_release ...` | Thin alias absorbed into `FileLock.release()` / context-manager exit | 2026-05-04 |
| ABSORBED | safe | `safe command [args...]` | Replaced by local try/except or subprocess fallback returning `"(unavailable)"` where needed | 2026-05-04 |
| jot_buildClaudeCmd | jot_build_claude_cmd | `(*, claude_plugin_root: str, claude_plugin_data: str, cwd: str, repo_root: str, home: str, input_file: str, state_dir: str, log_file: str, permissions_seed: Callable[..., object] \| None = None, expand_permissions: Callable[[str, dict[str, str]], str] \| None = None, tmpdir_factory: Callable[[], str] \| None = None) -> dict[str, str]` | RELAXED_COVERAGE; signature change replaces bash globals with explicit return dict; default seeding calls migrated `claude_seedPermissions` | 2026-05-04 |
| jot_launchPhase2Window | phase2_launch_window | `() -> int` | RELAXED_COVERAGE; uses migrated `FileLock` context manager instead of jot_lock_acquire/release; reads launch context from environment like bash globals | 2026-05-04 |
| jot_diagSection | section | `(title: str) -> str` | RELAXED_COVERAGE; de-nested helper; pure string formatter; 59-char ═ rule | 2026-05-05 |
| jot_diagIndent | indent | `(text: str) -> str` | RELAXED_COVERAGE; de-nested helper; argument-taking replacement for sed-stdin filter; preserves trailing newline | 2026-05-05 |
| jot_diagKv | kv | `(key: str, value: object) -> str` | RELAXED_COVERAGE; de-nested helper; printf %-28s parity; long keys not truncated | 2026-05-05 |
| debate_agentReadyMarker | agent_ready_marker | debate_agentReadyMarker(agent: str) | RELAXED_COVERAGE | 2026-05-05 |
| debate_agentErrorMarkers | agent_error_markers | debate_agentErrorMarkers(agent: str) | RELAXED_COVERAGE | 2026-05-05 |
| debate_agentLaunchCmd | agent_launch_cmd | debate_agentLaunchCmd(*,
    agent: str,
    current_model: dict[str, str],
    debate_dir: str,
    cwd: str,
    repo_root: str,
    home: str,
    settings_file: str,) |  | 2026-05-05 |
| debate_archive | archive_debate | debate_archive(debate_dir: Path | str) | RELAXED_COVERAGE | 2026-05-05 |
| debate_buildClaudeCmd | debate_build_claude_cmd | debate_buildClaudeCmd(cwd: str,
    repo_root: str,
    log_file: str,
    permissions_seed_fn,
    expand_permissions_fn,) | RELAXED_COVERAGE | 2026-05-05 |
| debate_buildClaudePrompts | debate_build_prompts | debate_buildClaudePrompts(stage: str,
    debate_dir: Path,
    plugin_root: Path,
    agents: list[str],
    agent_filter: str = "",) |  | 2026-05-05 |
| debate_checkResumeFeasibility | check_resume_feasibility | debate_checkResumeFeasibility(debate_dir: Path,
    available_agents: list[str],) | RELAXED_COVERAGE | 2026-05-05 |
| debate_claimSession | debate_claim_session | debate_claimSession(keepalive_cmd: str,
    *,
    tmux_runner: Callable[[List[str]], int] = _default_tmux_runner,) |  | 2026-05-05 |
| debate_cleanStaleLocks | clean_stale_locks | debate_cleanStaleLocks(debate_dir: Path,
    stage: str,
    window_target: str = "",) | RELAXED_COVERAGE | 2026-05-05 |
| debate_defaultModel | _default_model | debate_defaultModel(agent: str) | RELAXED_COVERAGE | 2026-05-05 |
| debate_detectAvailableAgents | detect_available_agents | debate_detectAvailableAgents() | RELAXED_COVERAGE | 2026-05-05 |
| debate_findMatching | find_matching_debate | debate_findMatching(repo_root: str, topic: str) | RELAXED_COVERAGE | 2026-05-05 |
| debate_initAgentModels | init_agent_models | debate_initAgentModels(env: Mapping[str, str] | None = None) |  | 2026-05-05 |
| debate_initHookContext | init_hook_context | debate_initHookContext(stdin: IO[str] | None = None) | RELAXED_COVERAGE | 2026-05-05 |
| debate_launch | debate_launch | debate_launch(*,
    scripts_dir: Path | None = None,
    plugin_root: Path | None = None,
    _debate_main_fn: object = None,
    _is_darwin: bool | None = None,
    _terminal_running_fn: object = None,
    _launch_terminal_fn: object = None,) | RELAXED_COVERAGE | 2026-05-05 |
| debate_launchAgent | launch_agent | debate_launchAgent(*,
    pane_id: str,
    stage: str,
    agent: str,
    launch_cmd: str,
    ready_marker: str,
    debate_dir: str,
    timeout: int = 120,) | RELAXED_COVERAGE | 2026-05-05 |
| debate_liveSession | live_debate_session | debate_liveSession(debate_dir: str) | RELAXED_COVERAGE | 2026-05-05 |
| debate_nextModel | _next_model | debate_nextModel(agent: str,
    tried_models: dict[str, str],
    models_json_path: str,) | RELAXED_COVERAGE | 2026-05-05 |
| debate_paneHasCapacityError | pane_has_capacity_error | debate_paneHasCapacityError(pane_id: str, agent: str) | RELAXED_COVERAGE | 2026-05-05 |
| debate_probeCodex | _probe_codex | debate_probeCodex() | RELAXED_COVERAGE | 2026-05-05 |
| debate_retryPaneWithNextModel | retry_pane_with_next_model | debate_retryPaneWithNextModel(*,
    pane_index: int,
    agent: str,
    stage: str,
    current_pane_id: str,
    current_model: dict[str, str],
    tried_models: dict[str, str],
    window_target: str,
    cwd: str,
    repo_root: str,
    home: str,
    settings_file: str,
    debate_dir: str,
    models_json_path: str,) | RELAXED_COVERAGE | 2026-05-05 |
| debate_tmuxOrchestrator | debate_tmux_orchestrator | debate_tmuxOrchestrator(debate_dir: str,
    session: str,
    window_name: str,
    settings_file: str,
    cwd: str,
    repo_root: str,
    plugin_root: str,
    *,
    debate_agents: str = "",
    cleanup_fn: object = None,
    daemon_main_fn: object = None,) |  | 2026-05-05 |
| debate_waitForOutputs | wait_for_outputs | debate_waitForOutputs(*,
    prefix: str,
    timeout: int,
    panes: Mapping[int, str],
    agents: Sequence[str],
    debate_dir: Path,
    pane_capacity_error: Callable[[str, str], bool],
    retry_pane: Callable[..., object],
    sleep_fn: Callable[[float], None],
    poll_interval: int = 5,) | RELAXED_COVERAGE | 2026-05-05 |
| debate_writeFailed | write_failed | debate_writeFailed(debate_dir: Path,
    stage: str,
    reason: str,
    agents: Iterable[str],
    *,
    pane_capture: Callable[[str], str] | None = None,
    now: Callable[[], datetime] | None = None,) | RELAXED_COVERAGE | 2026-05-05 |
| jot_collectDiagnostics | jot_diag_collect | jot_collectDiagnostics(out_path: str | None = None) | RELAXED_COVERAGE | 2026-05-05 |
| plate_summaryStop | plate_summary_stop | plate_summaryStop(repo: str, branch: str, output_file: str) | RELAXED_COVERAGE | 2026-05-05 |
| plate_summaryWatch | plate_summary_watch | plate_summaryWatch(pane: str,
    output_file: str,
    timeout: Optional[int] = None,
    interval: Optional[int] = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    tmux_send: Callable[[str, str], None] = _default_tmux_send,) | RELAXED_COVERAGE | 2026-05-05 |
| shell_waitForFile | wait_for_file | shell_waitForFile(path: str, timeout: float, poll_interval: float = 5.0) | RELAXED_COVERAGE | 2026-05-05 |
| todo_scanOpen | scan_open_todos | todo_scanOpen(target_dir: str | Path = ".") | RELAXED_COVERAGE | 2026-05-05 |
| todo_sessionStart | todo_session_start | todo_sessionStart(input_file: str, tmpdir_inv: str) | RELAXED_COVERAGE | 2026-05-05 |
| todo_stop | todo_stop | todo_stop(input_file: str,
    tmpdir_inv: str,
    state_dir: str,) |  | 2026-05-05 |
| debate_cleanup | cleanup | debate_cleanup(settings_file: str | Path) |  | 2026-05-05 |
| jot_sessionEnd | jot_session_end | jot_sessionEnd(tmpdir_inv: str | None) | RELAXED_COVERAGE | 2026-05-05 |
| jot_sessionStart | jot_session_start | jot_sessionStart(input_file: str | None, tmpdir_inv: str | None) | RELAXED_COVERAGE | 2026-05-05 |
| debate_anyLiveLock | any_live_lock | debate_anyLiveLock(debate_dir: str | os.PathLike[str]) | RELAXED_COVERAGE | 2026-05-05 |
| debate_sendPromptToAgent | send_prompt | debate_sendPromptToAgent(pane_id: str,
    stage: str,
    agent: str,
    instructions: str,) | RELAXED_COVERAGE | 2026-05-05 |
| todo_launcher | todo_launcher | todo_launcher(session_id: str, idea: str, pending_file_path: str) |  | 2026-05-05 |
| jot_stop | jot_stop | jot_stop(input_file: str,
    tmpdir_inv: str,
    state_dir: str,
    *,
    background_kill: Callable[[str, str], None] | None = None,) | RELAXED_COVERAGE | 2026-05-05 |
| debate_probeGemini | _probe_gemini | debate_probeGemini() | RELAXED_COVERAGE | 2026-05-05 |
| todo_sessionEnd | todo_session_end | todo_sessionEnd(tmpdir_inv: str) |  | 2026-05-05 |
| debate_launchAgentsParallel | launch_agents_parallel | debate_launchAgentsParallel(stage: str,
    panes: list[str],
    agents: list[str],
    debate_dir: str | Path,) |  | 2026-05-05 |
| debate_newEmptyPane | new_empty_pane | debate_newEmptyPane(window_target: str, cwd: str) | RELAXED_COVERAGE | 2026-05-05 |
| debateAbort_main | debate_abort_main | debateAbort_main() |  | 2026-05-05 |
| jot_main | jot_main | jot_main() | RELAXED_COVERAGE | 2026-05-05 |
| todo_main | todo_main | todo_main() |  | 2026-05-05 |
| todoList_main | todo_list_main | todoList_main() |  | 2026-05-05 |
