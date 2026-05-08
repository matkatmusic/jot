# Python function audit

Authoritative list of top-level functions and classes (with one level of method nesting) for every Python file in this worktree. Used as input when deciding how to split large modules into smaller, area-focused files.

Last generated: 2026-05-08

Regenerate from the worktree root with:

```
python3 /tmp/audit_gen.py > MIGRATION_TO_PYTHON.md
```

Excluded: every `conftest.py` and `scripts/jot-plugin-orchestrator-historic.py`.

---

## common/scripts/plate/

### common/scripts/plate/_rebase_reword_summary.py

- _format_trailer_body
- _strip_summary_trailer
- _append_summary_trailer
- _parse_payload
- _replace_subject
- _is_tip_commit
- _do_sequence
- _do_message
- main

(9 functions, 0 classes)

### common/scripts/plate/append_plate_to_stack.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/build_settings_json.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/cascade_parent_chain.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/check_drift_alert.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/check_live_children.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/check_rolling_intent_refresh.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/clear_drift_alert.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/commit_message.py

- format_commit_message

(1 functions, 0 classes)

### common/scripts/plate/instance_rw.py

- load
- atomic_write
- mutate
- new_instance
- new_plate

(5 functions, 0 classes)

### common/scripts/plate/list_paused_plates.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/next_resume_point.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/plate_cli.py

- _cmd_push
- _cmd_done
- _cmd_drop
- _cmd_trash
- _cmd_recycle
- _cmd_next
- _cmd_show
- _cmd_set_plate_summary
- main

(9 functions, 0 classes)

### common/scripts/plate/plate_lib.py

- plate_createRandomBranchName
- plate_random_string
- plate_performRandomEdit
- plate_formatPlateAge
- plate_localTranscriptIsReadable
- plate_extractConvoNameFromTranscript
- plate_extractConvoCwdFromTranscript
- plate_extractFilesEditedSinceTimestamp
- _plate_writeFakeTranscriptWithToolUse
- _plate_parseRmTargets
- plate_listPlateBranches
- plate_findMyLastPlate
- _plate_resolveTargetPlate
- _plate_buildFullWtTree
- _plate_buildExtractedTree
- _plate_formatTrailerBody
- plate_push
- plate_done
- _plate_trashBranchDir
- _plate_writeTrashSession
- _plate_listTrashSessions
- plate_drop
- plate_trash
- plate_recycle_list
- plate_stripConvoSummaryFromCommit
- plate_regenerateTipSummary
- plate_recycle
- plate_next
- _plate_resolvePlateTitle
- _plate_next_list
- _plate_next_jump
- plate_simulate_derived_agent
- plate_extractFilesDeletedSinceTimestamp
- _plate_writeTranscriptFile
- _plate_buildTwoBranchPlateTopology
- plate_rewriteBranchTipSummary

(36 functions, 0 classes)

### common/scripts/plate/print_resume_pointer.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/register_parent.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/plate/render_tree.py

- load_instances
- build_children_map
- format_plate_line
- render_instance
- render_tree

(5 functions, 0 classes)

### common/scripts/plate/spawn_summary_agent.py

- _next_session_index
- spawn

(2 functions, 0 classes)

### common/scripts/plate/transcript_parse.py

- is_user_message
- deduped_user_turns
- extract_recent_turns
- extract_errors

(4 functions, 0 classes)

### common/scripts/plate/verify_stash_refs.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

## common/scripts/jot/

### common/scripts/jot/expand_permissions.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/jot/render_template.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### common/scripts/jot/strip_stdin.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

## common/scripts/

### common/scripts/claude_lib.py

- claude_buildCmd
- claude_permseedLog
- claude_seedPermissions

(3 functions, 0 classes)

### common/scripts/debate_lib.py

- debate_agentReadyMarker
- debate_agentErrorMarkers
- debate_agentLaunchCmd
- debate_archive
- debate_buildClaudeCmd
- debate_buildClaudePrompts
- _debate_build_r1
- _debate_build_r2
- _debate_build_synthesis
- class ResumeFeasibility
- debate_checkResumeFeasibility
- debate_claimSession
- debate_cleanStaleLocks
- debate_defaultModel
- class DetectResult
- debate_detectAvailableAgents
- debate_findMatching
- debate_initAgentModels
- debate_initHookContext
- debate_launch
- debate_launchAgent
- debate_liveSession
- debate_nextModel
- debate_paneHasCapacityError
- debate_probeCodex
- debate_retryPaneWithNextModel
- _debate_daemon_main_default
- class DebateContext
  - DebateContext.__init__
- debate_tmuxOrchestrator
- debate_waitForOutputs
- debate_writeFailed
- debate_cleanup
- debate_anyLiveLock
- debate_sendPromptToAgent
- _debate_launch_agent
- _debate_send_prompt
- debate_probeGemini
- debate_launchAgentsParallel
- debate_newEmptyPane
- debate_abortMain
- debate_startOrResume
- debate_main
- debate_retryMain
- debate_daemonMain

(42 functions, 3 classes)

### common/scripts/git_lib.py

- git_makeRepo
- git_isRepo
- git_setUserConfigValue
- git_getUserConfigValue
- git_writeGitignore
- git_createUserConfig
- git_getBranchList
- git_createBranch
- git_checkOutBranch
- git_createAndCheckoutBranch
- git_getCurrentBranchName
- git_getUntrackedFilesList
- git_getUnstagedFilesList
- git_getStagedFilesList
- git_getTrackedFilesList
- git_addFile
- git_stageAllChanges
- git_stashFiles
- git_unstashFiles
- git_addMultipleFiles
- git_createCommit
- git_checkIfBranchExists
- git_countCommitsReachableFromRef
- git_setIndexFileForEnv
- git_getSHAForRefViaRevParse
- git_readTreeAt
- git_writeTree
- git_getTreeRevOf
- git_getTreeSHA
- git_getStatus
- git_checkForCleanWorkTree
- git_getCommitSubject
- git_getCommitTrailers
- git_resetHardToHead
- git_cleanWorkTree
- git_deleteBranchByForce
- git_saveChangesToPatch
- git_makeTempIndexPath
- git_applyPatch
- class GitError
- git_getRepoRoot
- git_getBranchNameOrFail
- git_getRecentCommitHashes
- git_getUncommittedFilenames
- git_ensureGitignoreEntry
- _git_repoRoot
- _git_get_repo_root

(46 functions, 1 classes)

### common/scripts/git_test_funcs_lib.py

- git_test_makeEmptyRepo
- git_test_makeTestRepo
- git_test_makeRepoWithSingleCommit
- git_test_makeTestFile
- git_test_modifyTrackedFile
- git_test_modifyRandomlyChosenTrackedFile
- git_test_createUntrackedFile
- git_test_setup_plate_test_repo
- git_test_setup_repo
- git_test_currentTimestampUtcCompact

(10 functions, 0 classes)

### common/scripts/hookjson_lib.py

- hookjson_emitBlock
- hookjson_installHint
- hookjson_checkRequirements

(3 functions, 0 classes)

### common/scripts/jot_lib.py

- jot_initState
- jot_popFirstFromQueue
- jot_sendPrompt
- jot_rotateAudit
- jot_buildClaudeCmd
- _jot_defaultPermissionsSeed
- _jot_defaultExpandPermissions
- _jot_appendLog
- jot_launchPhase2Window
- _jot_readSidecar
- jot_diagSection
- jot_diagIndent
- jot_diagKv
- jot_collectDiagnostics
- jot_sessionEnd
- jot_sessionStart
- jot_stop
- jot_main

(18 functions, 0 classes)

### common/scripts/plate_dispatcher.py

- plate_summaryStop
- plate_summaryWatch
- plate_main

(3 functions, 0 classes)

### common/scripts/tmux_lib.py

- tmux_requireVersion
- tmux_setOption
- tmux_setOptionForTarget
- tmux_setOptionGlobally
- tmux_setOptionForWindow
- tmux_hasSession
- tmux_newSession
- tmux_killSession
- tmux_listClients
- tmux_newPane
- tmux_killPane
- tmux_capturePane
- tmux_listPanes
- tmux_selectPane
- tmux_setPaneTitle
- tmux_newWindow
- tmux_killWindow
- tmux_listWindows
- tmux_windowExists
- tmux_paneHasTitle
- tmux_splitWindow
- tmux_selectLayout
- tmux_retile
- tmux_sendKeys
- tmux_sendEnter
- tmux_sendCtrlC
- tmux_sendAndSubmit
- tmux_cancelAndSend
- tmux_splitWorkerPane
- tmux_waitForClaudeReadiness
- tmux_ensureKeepalivePane
- tmux_ensureSession
- _tmux_default_runner
- _tmux_run
- _tmux_session_exists
- _tmux_default_send
- _tmux_backgroundKill
- _tmux_live_pane_ids
- _tmux_kill_pane
- _tmux_paneCurrentCommand
- _tmux_listLivePaneIds

(41 functions, 0 classes)

### common/scripts/todo_lib.py

- jot_sendPrompt
- todo_listMain
- todo_main
- todo_sessionEnd
- todo_launcher
- todo_stop
- todo_sessionStart
- _todo_has_open_status
- todo_scanOpen

(9 functions, 0 classes)

### common/scripts/util_lib.py

- run
- currentTimestampMs
- _util_matches_prefix
- _util_slugify
- _util_resolvePluginRoot
- _util_safe_call
- _util_strip_stdin_text
- _util_append_log
- _util_hide_errors
- _util_appendAudit
- _readSidecar
- _util_isoTimestampLocal
- shell_waitForFile
- terminal_spawnIfNeeded
- _util_ls_latest_input_txt
- _util_tail_lines
- _terminal_launchBackground
- _terminal_running
- _terminal_listTmuxClients
- _terminal_buildOsascript
- _terminal_isoNow
- _terminal_appendAdvisory
- _terminal_appendNonDarwinAdvisory
- _terminal_maximizeBlock
- shell_runWithTimeout
- _util_readFirstToken
- _util_sha256File
- class LockTimeout
- class FileLock
  - FileLock.__init__
  - FileLock.path
  - FileLock.acquired
  - FileLock.acquire
  - FileLock.release
  - FileLock.__enter__
  - FileLock.__exit__
- _valid_kwargs

(35 functions, 2 classes)

## scripts/

### scripts/jot_plugin_orchestrator.py

- dispatch_main

(1 functions, 0 classes)

## skills/plate/tests/sequence/

### skills/plate/tests/sequence/test_helpers_convo.py

- test_localTranscriptIsReadable
- test_extractConvoNameFromTranscript_returns_latest_custom_title
- test_extractConvoNameFromTranscript_falls_back_to_session_id_when_no_title
- test_extractConvoNameFromTranscript_returns_none_when_file_missing
- test_extractConvoNameFromTranscript_skips_unparseable_lines
- test_extractConvoCwdFromTranscript_returns_first_cwd
- test_extractConvoCwdFromTranscript_returns_none_when_no_cwd
- test_extractConvoCwdFromTranscript_returns_none_when_file_missing
- test_extractFilesEditedSinceTimestamp_filters_by_tool_and_cutoff
- test_extractFilesDeletedSinceTimestamp

(10 functions, 0 classes)

### skills/plate/tests/sequence/test_helpers_git_test_funcs.py

- test_makeEmptyRepo
- test_makeTestRepoWithSingleCommit
- test_makeTestFile
- test_modifyTrackedFile
- test_modifyRandomlyChosenTrackedFile
- test_createUntrackedFile
- test_setup_repo
- test_performRandomEdit_modify_tracked
- test_performRandomEdit_create_untracked_when_tracked_exists
- test_performRandomEdit_no_tracked_forces_create_untracked
- test_performRandomEdit_seeded_is_deterministic_simple
- test_setup_repo_checks_out_non_main_branch
- test_setup_repo_branch_name_is_varied
- test_setup_repo_creates_three_commits
- test_setup_repo_main_has_one_commit
- test_setup_repo_starts_clean
- test_setup_repo_creates_expected_files
- test_setup_repo_has_expected_subjects
- test_setup_repo_diverges_from_main
- test_setup_repo_no_plate_branch_initially
- test_performRandomEdit_dirties_wt
- test_performRandomEdit_returns_action_record
- test_performRandomEdit_modify_tracked_appends_line
- test_performRandomEdit_create_untracked_makes_new_file
- test_performRandomEdit_seeded_is_deterministic
- test_performRandomEdit_unseeded_works

(26 functions, 0 classes)

### skills/plate/tests/sequence/test_helpers_plate.py

- test_formatPlateAge
- test_listPlateBranches
- test_listPlateBranches_excludes_non_plate_refs
- test_findMyLastPlate
- test_plate_push_1x
- test_plate_push_with_convo_id
- test_plate_push_convo_summary_preserves_section_labels_on_own_lines
- test_plate_push_extraction_uses_explicit_transcript_path_arg
- test_plate_push_shared_branch_two_agents_isolates_each_authors_changes
- test_plate_push_omits_convo_trailers_when_kwargs_unset
- test_plate_done
- test_plate_drop
- test_plate_trash
- test_plate_trash_hard
- test_plate_recycle
- test_simulate_derived_agent_first
- test_simulate_derived_agent_second
- test_plate_drop_no_branch
- test_plate_trash_no_branch
- test_plate_recycle_no_branch
- test_plate_done_resolves_content_conflict_in_plate_favor
- test_drop_patch_cross_repo_portability
- test_plate_done_leaves_sha_recoverable
- test_plate_done_aborts_when_no_plate_branch
- test_plate_done_aborts_when_wt_differs_from_plate_tip
- test_plate_next_list_shows_plates_sorted_with_current_marker
- test_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes
- test_plate_next_jump_lost_message_when_transcript_unreadable
- test_plate_next_jump_self_index_is_noop
- test_plate_next_jump_proceeds_when_head_on_branch_with_no_plate
- test_plate_next_jump_invalid_index_returns_message
- test_plate_next_list_empty_when_no_plates
- test_plate_next_list_no_marker_when_head_has_no_plate
- test_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary

(34 functions, 0 classes)

### skills/plate/tests/sequence/test_helpers_plate_sequence.py

- test_sequence_01_plate_push_first_time_preserves_user_workspace
- test_sequence_02_plate_push_second_time_extends_plate_stack
- test_sequence_03_plate_done_replays_stack_and_cleans_workspace
- test_sequence_04_plate_done_aborts_when_unpushed_work_exists
- test_sequence_05_plate_drop_removes_top_plate_only
- test_sequence_06_plate_drop_single_plate_deletes_stack
- test_sequence_07_applyGitPatch_recovers_dropped_plate_work
- test_sequence_08_plate_trash_deletes_stack_but_leaves_workspace_by_default
- test_sequence_09_plate_trash_clean_mode_resets_workspace
- test_sequence_10_plate_recycle_restores_latest_trashed_stack
- test_sequence_12_derived_agent_first_child_records_parent_trailers
- test_sequence_13_derived_agent_second_child_extends_linear_chain
- test_sequence_21_plate_next_list_shows_plates_sorted_with_current_marker
- test_sequence_15_plate_drop_with_no_plate_branch_warns_and_exits
- test_sequence_16_plate_trash_with_no_plate_branch_warns_and_exits
- test_sequence_17_plate_recycle_with_no_trashed_session_warns_and_exits
- test_sequence_18_plate_done_resolves_content_conflict_in_plate_favor
- test_sequence_19_drop_patch_is_portable_across_repos
- test_sequence_20_plate_done_leaves_sha_recoverable_after_branch_delete

(19 functions, 0 classes)

### skills/plate/tests/sequence/test_plate_cli.py

- _run
- test_routes_push_to_plate_push
- test_routes_done_to_plate_done
- test_routes_drop_to_plate_drop
- test_routes_drop_no_plate
- test_routes_trash_to_plate_trash
- test_routes_trash_with_clean_wt_flag
- test_routes_recycle_to_plate_recycle
- test_routes_recycle_list
- test_routes_recycle_named_session
- test_routes_next_list_mode
- test_routes_next_jump_mode_passes_raw_string
- test_routes_next_jump_mode_passes_non_numeric_string
- test_routes_show_returns_todo_stub
- test_set_plate_summary_cli_routing
- test_push_propagates_none_when_extract_returns_none
- test_push_with_empty_transcript_path_skips_extractors
- test_push_no_changes_returns_no_op_message
- test_no_argv_prints_usage_and_exits_zero
- test_unknown_variant_prints_message_and_exits_zero

(20 functions, 0 classes)

### skills/plate/tests/sequence/test_plate_e2e_wiring.py

- _run_hook
- _parse_block
- empty_repo
- test_next_list_mode_returns_empty_list_message
- test_next_jump_non_numeric_returns_message
- test_show_returns_todo_stub
- test_drop_no_plate_returns_message
- test_push_on_empty_wt_returns_no_changes
- test_push_with_dirty_wt_creates_plate_branch
- test_unrelated_prompt_exits_silently
- test_typo_variant_exits_silently

(11 functions, 0 classes)

### skills/plate/tests/sequence/test_plate_scenarios.py

- _check_plate_push_creates_branch_capturing_wip
- _check_plate_done_replays_stack
- _check_plate_drop_deletes_last_plate
- _check_plate_drop_then_applyGitPatch_round_trip
- _check_plate_trash_default_preserves_wt
- _check_plate_trash_clean_resets_wt
- _check_plate_recycle_restores_stack
- _check_first_derived_agent_records_trailers
- _check_second_derived_agent_extends_chain
- _check_plate_drop_no_branch_warns_and_exits
- _check_plate_trash_no_branch_warns_and_exits
- _check_plate_recycle_no_branch_warns_and_exits
- _check_plate_done_resolves_content_conflict_in_plate_favor
- _check_drop_patch_applies_in_fresh_repo
- _check_plate_done_aborts_when_no_plate_branch
- _check_plate_done_aborts_when_wt_differs_from_plate_tip
- _check_plate_done_leaves_sha_recoverable
- _check_plate_next_list_shows_plates_sorted_with_current_marker
- _check_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes
- _check_plate_next_jump_lost_message_when_transcript_unreadable
- _check_plate_next_jump_self_index_is_noop
- _check_plate_next_jump_proceeds_when_head_on_branch_with_no_plate
- _check_plate_next_jump_invalid_index_returns_message
- _check_plate_next_list_empty_when_no_plates
- _check_plate_next_list_no_marker_when_head_has_no_plate
- _check_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary

(26 functions, 0 classes)

### skills/plate/tests/sequence/test_session_end_hook.py

- _run_session_end
- empty_repo
- _plate_refs
- test_session_end_with_dirty_wt_creates_plate_ref
- test_session_end_with_clean_wt_creates_no_plate

(5 functions, 0 classes)

### skills/plate/tests/sequence/test_summary_pipeline.py

- test_strip_prior_then_regenerate_tip_summary
- test_regenerate_tip_summary_splits_subject_and_body

(2 functions, 0 classes)

## skills/

### skills/jot/scripts/capture-conversation.py

- is_pure_system_injection
- _slash_command_text
- extract_text
- load_entries
- find_start_index
- format_window
- main

(7 functions, 0 classes)

### skills/todo-list/scripts/format_open_todos.py

- parse_frontmatter
- format_created
- sort_key

(3 functions, 0 classes)

## tests/

### tests/_e2e_lib.py

- e2e_runOrchestratorWithStdin
- e2e_parseHookDecision
- _e2e_buildStubBin
- _e2e_baseEnv
- _e2e_initEmptyRepo
- e2e_buildJotPromptFixture
- e2e_buildDebatePromptFixture
- e2e_buildDebateRetryPromptFixture
- e2e_buildDebateAbortPromptFixture
- e2e_resolveDebateLogParent
- e2e_buildTodoPromptFixture
- e2e_buildTodoListPromptFixture
- e2e_resolveTodoRepoPath

(13 functions, 0 classes)

### tests/fixtures/__init__.py

*(no top-level functions or classes)*

(0 functions, 0 classes)

### tests/fixtures/fakes.py

- class FakeClock
  - FakeClock.__init__
  - FakeClock.__call__
- class FakeTmux
  - FakeTmux.__init__
  - FakeTmux.__call__

(4 functions, 2 classes)

### tests/test_claude_buildcmd.py

- test_claude_buildCmd_returns_command_string_with_trailing_newline
- test_claude_buildCmd_extra_dirs_appended_in_order
- test_claude_buildCmd_writes_settings_file_with_allow_and_hooks
- test_claude_buildCmd_no_extra_dirs_omits_additional_flags
- test_claude_buildCmd_missing_hooks_file_raises

(5 functions, 0 classes)

### tests/test_claude_misc.py

- test_claude_marker
- test_claude_returns_overload_markers
- test_claude_repo_root_equals_cwd_no_plans_dup
- test_claude_repo_root_distinct_from_cwd
- test_claude_plans_equals_cwd_skipped
- test_claude_repo_root_empty_string_skipped
- test_claude_has_empty_string_when_no_env

(7 functions, 0 classes)

### tests/test_claude_permissions.py

- test_claude_permseedLog_no_op_when_log_file_is_none
- test_claude_permseedLog_no_op_when_log_file_is_empty_string
- test_claude_permseedLog_writes_line_to_log_file
- test_claude_permseedLog_default_log_prefix_is_plugin
- test_claude_permseedLog_custom_log_prefix_is_used
- test_claude_permseedLog_line_starts_with_iso8601_timestamp
- test_claude_permseedLog_appends_rather_than_overwrites
- test_claude_permseedLog_swallows_write_errors_silently
- permissions_workspace
- test_claude_seedPermissions_missing_default_file_logs_and_returns
- test_claude_seedPermissions_missing_default_sha_file_logs_and_returns
- test_claude_seedPermissions_seeds_installed_when_missing
- test_claude_seedPermissions_no_op_when_installed_matches_default
- test_claude_seedPermissions_upgrades_unmodified_installed_to_new_default
- test_claude_seedPermissions_user_edited_installed_is_preserved_and_logged
- test_claude_seedPermissions_user_edited_no_default_change_does_not_rewrite_prior
- test_claude_seedPermissions_log_file_none_suppresses_logging
- test_claude_seedPermissions_default_sha_file_with_two_column_format_is_parsed

(18 functions, 0 classes)

### tests/test_debate_agents.py

- test_debate_agents_falls_back_to_env
- test_gemini_with_model
- test_gemini_without_model
- test_codex_with_model
- test_codex_without_model
- test_returns_empty_when_gemini_binary_missing
- test_returns_empty_when_binary_present_but_no_credentials
- test_returns_model_when_oauth_creds_file_present
- test_returns_model_when_gemini_api_key_env_set
- test_returns_model_when_google_api_key_env_set
- test_returns_present_sentinel_when_no_model_configured
- _make_plugin_root
- test_returns_first_claude_model
- test_returns_first_gemini_model
- test_returns_first_codex_model
- test_unknown_agent_returns_empty_string
- test_agent_with_empty_list_returns_empty_string
- test_missing_plugin_root_env_raises
- test_only_claude_when_both_probes_unavailable
- test_gemini_with_real_model_appended_and_model_recorded
- test_gemini_present_sentinel_marks_available_but_leaves_model_blank
- test_codex_with_real_model_appended_and_model_recorded
- test_codex_present_sentinel_marks_available_but_leaves_model_blank
- test_both_probes_available_preserves_order_claude_gemini_codex
- test_returns_dict_with_current_model_and_tried_models_keys
- test_all_three_agents_present_in_both_subdicts
- test_gemini_picks_up_GEMINI_MODEL_env
- test_codex_picks_up_CODEX_MODEL_env
- test_unset_gemini_env_yields_empty_string_not_missing_key
- test_unset_codex_env_yields_empty_string
- test_independent_calls_return_independent_dicts
- test_env_defaults_to_os_environ_when_omitted
- test_returns_empty_when_codex_binary_missing
- test_returns_empty_when_no_credentials_present
- test_returns_present_when_available_but_no_model_configured
- test_returns_model_name_when_configured
- test_openai_api_key_alone_satisfies_credentials_gate

(37 functions, 0 classes)

### tests/test_debate_archive_io.py

- test_creates_archive_subdirectory
- test_moves_context_md_into_archive
- test_moves_synthesis_instructions_txt
- test_moves_r1_instructions_glob
- test_moves_r1_output_md_glob
- test_moves_r2_instructions_and_outputs_glob
- test_moves_orchestrator_log_when_present
- test_does_not_move_synthesis_md
- test_does_not_move_topic_md
- test_idempotent_when_no_intermediate_files
- test_handles_preexisting_archive_dir
- test_returns_scripts_dir_under_plugin_root
- test_log_file_defaults_under_plugin_data_and_dir_created
- test_log_file_honours_debate_log_file_override
- test_parses_cwd_and_transcript_path_from_stdin_json
- test_cwd_falls_back_to_pwd_when_json_omits_it
- test_repo_root_resolved_for_git_cwd
- test_repo_root_empty_when_cwd_not_in_git
- test_input_field_preserves_raw_stdin
- _patch_all
- test_calls_write_failed_on_timeout
- test_no_write_failed_on_success
- _write
- test_partial_completion_returns_only_completed_agents
- test_empty_output_file_does_not_count_as_complete
- test_removes_tmp_debate_dir
- test_ignores_non_tmp_debate_dir
- test_ignores_tmp_non_debate_prefix
- test_noop_when_dir_already_gone
- test_accepts_str_path
- test_writes_failed_txt_at_debate_dir_root
- test_header_contains_stage_reason_and_iso_timestamp
- test_skips_agents_with_nonempty_output_files
- test_empty_output_file_counts_as_missing
- test_missing_lock_file_emits_placeholder_line
- test_lock_with_pane_id_invokes_capture_and_fences_output
- test_overwrites_existing_failed_txt
- test_no_temp_files_left_behind_on_success
- test_missing_agents_section_header_present
- test_pane_capture_callback_failure_yields_unavailable_marker
- test_returns_true_when_all_outputs_already_present
- test_returns_false_with_timeout_reason_when_outputs_never_appear

(42 functions, 0 classes)

### tests/test_debate_capacity.py

- test_gemini_marker
- test_codex_marker
- test_unknown_agent_returns_empty_string
- test_empty_string_agent_returns_empty_string
- test_codex_returns_capacity_and_overload_markers
- test_gemini_returns_quota_markers_in_order
- test_unknown_agent_returns_empty_list
- test_empty_string_agent_returns_empty_list
- test_result_is_list_type
- models_file
- test_returns_first_model_when_none_tried
- test_skips_already_tried_models
- test_returns_none_when_all_tried
- test_unknown_agent_returns_none
- test_partial_tried_with_leading_comma
- test_missing_models_file_returns_none
- test_codex_capacity_marker_present_returns_truthy
- test_codex_overloaded_marker_present_returns_truthy
- test_codex_no_marker_returns_falsy
- test_gemini_resource_exhausted_returns_truthy
- test_gemini_marker_for_other_agent_does_not_match
- test_claude_api_529_returns_truthy
- test_unknown_agent_returns_falsy_without_capturing
- test_ansi_escape_bytes_are_stripped_before_match
- test_empty_capture_returns_falsy
- test_no_next_model_returns_none
- test_updates_model_dicts_on_success
- test_kills_old_pane_returns_new_pane_id
- test_launch_agent_failure_returns_none
- test_send_prompt_failure_returns_none
- test_tried_models_created_when_agent_missing
- test_invokes_retry_when_pane_has_capacity_error_and_no_output

(32 functions, 0 classes)

### tests/test_debate_daemon.py

- _patch_all_daemon
- _base_kwargs_daemon
- class TestDaemonMainHappyPath
  - TestDaemonMainHappyPath.test_happy_path_two_agents_returns_zero
  - TestDaemonMainHappyPath.test_happy_path_calls_init_agent_models
- class TestDaemonMainDriftWipesFiles
  - TestDaemonMainDriftWipesFiles.test_drift_true_unlinks_r2_and_synthesis_instructions
  - TestDaemonMainDriftWipesFiles.test_drift_false_leaves_files_intact
- class TestDaemonMainMissingR2Instructions
  - TestDaemonMainMissingR2Instructions.test_missing_r2_instructions_triggers_build
  - TestDaemonMainMissingR2Instructions.test_present_r2_instructions_skips_build
- class TestDaemonMainSynthesisAlreadyComplete
  - TestDaemonMainSynthesisAlreadyComplete.test_nonempty_synthesis_md_skips_launch_and_returns_zero
  - TestDaemonMainSynthesisAlreadyComplete.test_empty_synthesis_md_does_not_short_circuit
- class TestDaemonMainLaunchFailure
  - TestDaemonMainLaunchFailure.test_r1_launch_failure_returns_one
  - TestDaemonMainLaunchFailure.test_r1_wait_failure_returns_one
  - TestDaemonMainLaunchFailure.test_r2_launch_failure_returns_one
  - TestDaemonMainLaunchFailure.test_synth_launch_failure_returns_one
  - TestDaemonMainLaunchFailure.test_synth_wait_failure_returns_one
  - TestDaemonMainLaunchFailure.test_send_prompt_failure_returns_one
- _patch_deps
- test_happy_path_two_agents_returns_zero
- test_skip_when_output_file_exists
- test_skip_when_lock_file_exists
- test_partial_failure_returns_one
- test_empty_agents_list_returns_zero
- test_launch_failure_returns_one
- test_empty_output_file_does_not_skip

(24 functions, 5 classes)

### tests/test_debate_e2e_wiring.py

- test_debatePrompt_emitsBlockDecisionWhenTopicMissing
- test_debateRetryPrompt_emitsBlockDecisionWhenTranscriptPathMissing
- test_debateAbortPrompt_emitsBlockDecisionWhenTranscriptPathMissing

(3 functions, 0 classes)

### tests/test_debate_locks.py

- _write_lock
- _write_lock_at_path
- _patch_all
- fake_tmux
- test_removes_lock_with_missing_pane_id
- test_removes_lock_when_pane_not_in_window
- test_removes_lock_when_pane_current_command_mismatches_agent
- test_preserves_lock_when_pane_alive_and_command_matches_agent
- test_only_touches_locks_for_requested_stage
- test_no_locks_present_is_a_noop
- test_writes_lock_file_before_launch
- test_returns_session_name_when_lock_resolves
- test_returns_empty_when_no_lock_files
- test_returns_empty_when_lock_has_no_pane_id
- test_returns_empty_when_tmux_fails
- test_returns_empty_when_tmux_returns_empty_session
- test_skips_missing_lock_file_gracefully
- test_returns_first_resolved_session_from_multiple_locks
- test_falls_through_to_second_lock_when_first_tmux_fails
- test_returns_false_when_no_lock_files
- test_returns_true_when_lock_pane_id_is_live
- test_returns_false_when_lock_pane_id_is_dead
- test_skips_lock_without_debate_marker
- test_returns_false_when_directory_missing
- test_returns_true_if_any_one_of_many_locks_is_live
- test_ignores_non_hidden_lock_files
- _write
- test_removes_lock_file_when_output_appears

(28 functions, 0 classes)

### tests/test_debate_main.py

- _make_subject_sor
- class TestDebateStartOrResumeFreshStart
  - TestDebateStartOrResumeFreshStart.test_all_r1_prompts_built_when_files_missing
  - TestDebateStartOrResumeFreshStart.test_r2_prompts_built_when_files_missing
  - TestDebateStartOrResumeFreshStart.test_synthesis_prompt_built_when_file_missing
  - TestDebateStartOrResumeFreshStart.test_daemon_launched_with_start_new_session
  - TestDebateStartOrResumeFreshStart.test_emit_block_says_spawned_on_fresh_start
- class TestDebateStartOrResumeNoDrift
  - TestDebateStartOrResumeNoDrift.test_composition_drifted_false_when_agents_match
  - TestDebateStartOrResumeNoDrift.test_prompts_skipped_when_all_files_exist
  - TestDebateStartOrResumeNoDrift.test_emit_block_says_resumed
- class TestDebateStartOrResumeWithDrift
  - TestDebateStartOrResumeWithDrift.test_composition_drifted_true_when_agents_differ
- class TestDebateStartOrResumeClaimFailure
  - TestDebateStartOrResumeClaimFailure.test_exits_zero_and_emits_error_on_claim_failure
- class TestDebateStartOrResumePromptBuildSkipped
  - TestDebateStartOrResumePromptBuildSkipped.test_only_missing_r1_is_built
  - TestDebateStartOrResumePromptBuildSkipped.test_synthesis_not_built_when_file_exists
- _ctx_dm
- _detect_dm
- test_debateMain_non_debate_input_returns_zero
- test_debateMain_missing_topic_emits_usage
- test_debateMain_missing_repo_emits_block
- test_debateMain_existing_with_synthesis_emits_already_complete
- test_debateMain_existing_with_live_lock_emits_already_running
- test_debateMain_existing_without_synthesis_or_lock_resumes
- test_debateMain_fresh_under_two_agents_emits_count_block
- test_debateMain_fresh_happy_path_creates_artifacts_and_dispatches
- test_debateMain_fresh_with_transcript_invokes_capture_subprocess
- test_debateMain_fresh_capture_failure_writes_failure_marker
- test_creates_tmpdir_and_settings_file_path
- test_writes_settings_json_with_allow_and_empty_hooks
- test_returns_claude_cmd_with_settings_and_add_dir
- test_invokes_permissions_seed_with_expected_paths
- test_creates_claude_plugin_data_dir_if_missing
- _noop
- _make_main_mock
- test_always_calls_debate_main
- test_skipTerminalCheck_envBypassesDarwinTerminalProbe
- test_plugin_root_exported_to_environment
- test_raises_when_session_empty
- test_raises_when_debate_agents_empty_and_no_env
- test_window_target_composed_from_session_and_window_name
- test_stage_timeout_is_900_seconds
- test_agents_parsed_from_space_separated_string
- test_daemon_main_called_once_with_context
- test_cleanup_called_even_when_daemon_raises
- test_returns_zero_on_success
- test_context_stores_all_positional_args
- test_missing_plugin_root_raises
- test_missing_plugin_data_raises

(46 functions, 5 classes)

### tests/test_debate_prompts.py

- test_r1_writes_instruction_file_for_each_agent
- test_r1_agent_filter_writes_only_matching_agent
- test_r1_reads_agents_from_agents_txt_when_agents_list_empty
- test_r2_writes_cross_critique_instruction_file_for_each_agent
- test_r2_agent_filter_writes_only_matching_agent
- test_r2_others_list_excludes_self
- test_synthesis_writes_single_instruction_file
- test_synthesis_references_all_r1_and_r2_paths
- test_synthesis_contains_required_structure_sections
- test_unknown_stage_raises_value_error

(10 functions, 0 classes)

### tests/test_debate_retry.py

- _install_stubs_dr
- test_debateRetry_missing_transcript_emits_message
- test_debateRetry_missing_repo_emits_message
- test_debateRetry_no_matching_debate_emits_message
- test_debateRetry_matched_with_synthesis_emits_already_complete
- test_debateRetry_matched_with_live_lock_emits_still_running
- test_debateRetry_happy_path_lex_max_wins_and_invokes_resume
- _seed_original
- _seed_outputs
- test_all_originals_still_available_returns_feasible
- test_appeared_agent_is_kept_in_updated_list
- test_disappeared_agent_with_complete_outputs_is_readded
- test_disappeared_agent_missing_r2_is_unusable
- test_disappeared_agent_with_empty_output_file_is_unusable
- test_unusable_reason_contains_block_message_and_agent_name
- test_no_original_instructions_returns_feasible
- test_caller_available_agents_list_is_not_mutated
- test_returns_resumefeasibility_dataclass_instance
- _make_topic_debate
- test_returns_none_when_no_debates_dir
- test_returns_none_when_no_topic_matches
- test_returns_dir_path_for_single_match
- test_skips_dirs_missing_topic_md
- test_most_recent_timestamp_wins_on_multiple_matches
- test_multiline_topic_byte_exact_match
- test_partial_substring_does_not_match
- _install_ctx
- _capture_emit
- _make_debate
- test_emits_when_transcript_path_missing
- test_emits_when_repo_root_missing
- test_emits_when_no_matching_debate_found
- test_emits_still_running_when_live_lock_present
- test_emits_still_running_with_unknown_when_session_lookup_empty
- test_happy_path_deletes_dir_and_emits_success
- test_lexicographic_tiebreak_picks_newest_basename

(36 functions, 0 classes)

### tests/test_debate_tmux.py

- test_claims_first_unused_when_all_free
- test_skips_collisions_until_free_slot
- test_passes_keepalive_cmd_and_geometry_to_tmux
- test_raises_when_all_slots_exhausted
- test_session_names_are_sequential_debate_n
- _patch_all
- test_sends_launch_cmd_via_tmux
- test_returns_true_when_ready_marker_found
- test_returns_false_on_timeout
- test_sleeps_between_capture_polls
- test_default_timeout_is_120
- test_newEmptyPane_returnsPaneId_onSuccess
- test_newEmptyPane_returnsNone_onTmuxFailure
- test_newEmptyPane_returnsNone_onEmptyPaneId
- test_newEmptyPane_callsRetile_beforeSplit
- test_newEmptyPane_passesCorrectCwdToSplit
- test_newEmptyPane_retileRcIgnored_doesNotPreventSplit
- test_newEmptyPane_addsPaneToWindow
- test_newEmptyPane_returnedIdInPaneList
- test_newEmptyPane_returnsNone_onBogusTarget
- tmux_session_newpane
- test_returns_zero_when_marker_seen_immediately
- test_timeout_returns_one_and_invokes_writeFailed
- test_ansi_escapes_are_stripped_before_match
- test_marker_is_basename_not_full_path

(25 functions, 0 classes)

### tests/test_dispatcher.py

- _set_stdin
- test_dispatch_empty_stdin_returns_zero
- test_dispatch_unmatched_prompt_returns_zero
- test_dispatch_routes_jot_prefix_to_jot_main
- test_dispatch_longest_prefix_wins_for_todo_list
- test_dispatch_rewrites_jot_colon_prefix
- test_dispatch_argv_mode_routes_to_known_subcommand
- test_dispatch_argv_unknown_head_falls_through_to_stdin
- test_dispatch_propagates_route_return_code

(9 functions, 0 classes)

### tests/test_git_lib.py

- test_run
- test_writeGitIgnore
- test_setGitUserConfigValue
- test_createGitUserConfig
- test_createGitBranch
- test_checkOutGitBranch
- test_createAndCheckoutGitBranch
- test_getCurrentGitBranchName
- test_gitStashFiles
- test_gitUnstashFiles
- test_addFileToGit
- test_stageFiles
- test_createGitCommit
- test_checkIfGitBranchExists
- test_countGitCommitsReachableFromRef
- test_getSHAForGitRefViaRevParse
- test_readWriteGitTree
- test_getGitTreeRevOf
- test_getGitStatus
- test_checkGitForCleanWorkTree
- test_getGitCommitSubject
- test_getGitCommitTrailers
- test_gitResetHardToHead
- test_gitCleanWorkTree
- test_deleteGitBranchByForce
- test_saveChangesToGitPatch
- test_applyGitPatch
- test_getGitRepoRoot_returns_absolute_repo_root
- test_getGitRepoRoot_works_from_subdirectory
- test_getGitRepoRoot_raises_outside_repo
- test_getGitBranchNameOrFail_returns_current_branch
- test_getGitBranchNameOrFail_raises_outside_repo
- test_getGitBranchNameOrFail_raises_on_detached_head
- test_getGitRecentCommitHashes_returns_one_hash_for_single_commit
- test_getGitRecentCommitHashes_caps_at_n
- test_getGitRecentCommitHashes_raises_outside_repo
- test_getGitRecentCommitHashes_raises_on_empty_repo
- test_getGitUncommittedFilenames_clean_repo_returns_empty
- test_getGitUncommittedFilenames_lists_modified
- test_getGitUncommittedFilenames_lists_untracked
- test_getGitUncommittedFilenames_raises_outside_repo
- test_ensureGitignoreEntry_creates_file
- test_ensureGitignoreEntry_appends_to_existing
- test_ensureGitignoreEntry_is_idempotent

(44 functions, 0 classes)

### tests/test_hookjson_lib.py

- test_hookjson_emitBlock_simple_reason_roundtrips_through_json
- test_hookjson_emitBlock_quotes_in_reason_are_preserved_after_roundtrip
- test_hookjson_emitBlock_backslashes_in_reason_are_preserved_after_roundtrip
- test_hookjson_emitBlock_unicode_in_reason_is_preserved_after_roundtrip
- test_hookjson_emitBlock_returns_a_string_type
- test_hookjson_emitBlock_empty_reason_still_produces_valid_block_json
- test_hookjson_installHint_returns_canonical_hint_for_each_known_dependency
- test_hookjson_installHint_returns_bare_command_name_for_unknown_dependency
- test_hookjson_installHint_handles_empty_string_input_without_crashing
- test_hookjson_checkRequirements_returns_None_silently_when_all_commands_are_present
- test_hookjson_checkRequirements_emits_block_JSON_and_exits_zero_when_one_command_is_missing
- test_hookjson_checkRequirements_comma_joins_multiple_missing_commands_in_block_reason
- test_hookjson_checkRequirements_prepends_the_supplied_prefix_to_the_block_reason
- test_hookjson_checkRequirements_lists_unknown_command_by_its_bare_name

(14 functions, 0 classes)

### tests/test_jot_argv_e2e.py

- orchestrator_recordLibCalls
- orchestrator_rebuildArgvDispatch
- orchestrator_driveArgvSubcmd
- test_jot_session_start_argv_invokes_jot_sessionStart_with_positional_args
- test_jot_session_end_argv_invokes_jot_sessionEnd_with_positional_args
- test_jot_stop_argv_invokes_jot_stop_with_positional_args
- test_jot_diag_collect_argv_invokes_jot_collectDiagnostics_with_positional_args
- test_scan_open_todos_argv_invokes_todo_scanOpen_with_positional_args
- test_todo_launcher_argv_invokes_todo_launcher_with_positional_args
- test_todo_stop_argv_invokes_todo_stop_with_positional_args
- test_todo_session_start_argv_invokes_todo_sessionStart_with_positional_args
- test_todo_session_end_argv_invokes_todo_sessionEnd_with_positional_args
- test_plate_summary_stop_argv_invokes_plate_summaryStop_with_positional_args
- test_plate_summary_watch_argv_invokes_plate_summaryWatch_with_positional_args
- test_debate_tmux_orchestrator_argv_invokes_debate_tmuxOrchestrator_with_positional_args

(15 functions, 0 classes)

### tests/test_jot_audit.py

- test_jot_rotateAudit_silent_noop_when_file_missing
- test_jot_rotateAudit_leaves_short_file_untouched
- test_jot_rotateAudit_truncates_to_last_max_lines_when_oversized
- test_jot_rotateAudit_respects_custom_max_lines
- test_jot_rotateAudit_no_trim_sidecar_left_behind

(5 functions, 0 classes)

### tests/test_jot_buildcmd.py

- plugin_layout
- _invoke_jot_build
- test_jot_buildClaudeCmd_returns_tmpdir_inv_from_factory
- test_jot_buildClaudeCmd_settings_file_lives_under_tmpdir
- test_jot_buildClaudeCmd_permissions_file_under_plugin_data
- test_jot_buildClaudeCmd_orchestrator_script_copied_into_tmpdir
- test_jot_buildClaudeCmd_plugin_data_dir_is_created
- test_jot_buildClaudeCmd_permissions_seed_invoked_with_expected_args
- test_jot_buildClaudeCmd_expand_permissions_receives_cwd_home_repo_root
- test_jot_buildClaudeCmd_hooks_json_file_is_written_and_valid_json
- test_jot_buildClaudeCmd_hooks_json_session_start_command_includes_input_file_and_tmpdir
- test_jot_buildClaudeCmd_hooks_json_stop_command_includes_state_dir
- test_jot_buildClaudeCmd_claude_cmd_contains_settings_and_cwd
- test_jot_buildClaudeCmd_settings_file_written_with_expanded_allow_json

(14 functions, 0 classes)

### tests/test_jot_diag.py

- test_jot_diagSection_starts_with_leading_newline
- test_jot_diagSection_embeds_title_between_rules
- test_jot_diagSection_rule_is_59_box_chars
- test_jot_diagSection_ends_with_trailing_newline
- test_jot_diagSection_preserves_empty_title
- test_jot_diagIndent_single_line_no_trailing_newline
- test_jot_diagIndent_multiline_preserves_trailing_newline
- test_jot_diagIndent_multiline_no_trailing_newline
- test_jot_diagIndent_blank_line_still_prefixed
- test_jot_diagIndent_empty_string_returns_empty
- test_jot_diagIndent_only_newline
- test_jot_diagKv_short_key_left_padded_to_28
- test_jot_diagKv_value_starts_at_column_29
- test_jot_diagKv_long_key_not_truncated
- test_jot_diagKv_ends_with_single_trailing_newline
- test_jot_diagKv_empty_value_still_emits_padded_key
- test_jot_diagKv_value_with_spaces_preserved_verbatim
- _read
- class TestReportHeader
  - TestReportHeader.test_report_file_created_at_default_path
  - TestReportHeader.test_report_contains_header_line
  - TestReportHeader.test_report_contains_generated_timestamp
  - TestReportHeader.test_report_contains_cwd_line
  - TestReportHeader.test_report_contains_project_line
- class TestSectionBanners
  - TestSectionBanners.test_section_1_banner_present
  - TestSectionBanners.test_section_2_banner_present
  - TestSectionBanners.test_section_3_banner_present
  - TestSectionBanners.test_section_4_banner_present
  - TestSectionBanners.test_section_5_banner_present
  - TestSectionBanners.test_section_6_banner_present
  - TestSectionBanners.test_section_7_banner_present
  - TestSectionBanners.test_section_8_banner_present
  - TestSectionBanners.test_end_of_report_banner_present
  - TestSectionBanners.test_section_banners_use_box_drawing_rule
- class TestTodosInputSection
  - TestTodosInputSection.test_no_input_txt_shows_not_found_message
  - TestTodosInputSection.test_input_txt_present_shows_kv_path
  - TestTodosInputSection.test_input_txt_pending_status
  - TestTodosInputSection.test_input_txt_processed_status
- class TestStateDirSection
  - TestStateDirSection.test_missing_state_dir_shows_message
  - TestStateDirSection.test_queue_txt_empty_shows_empty_message
  - TestStateDirSection.test_queue_txt_missing_shows_missing
  - TestStateDirSection.test_queue_lock_held_shows_lock_message
  - TestStateDirSection.test_queue_lock_free_shows_free_message
- class TestDependencySection
  - TestDependencySection.test_dependency_section_lists_known_cmds
  - TestDependencySection.test_dependency_found_cmd_shows_path
- class TestReturnValue
  - TestReturnValue.test_returns_out_path_string
  - TestReturnValue.test_default_out_path_is_in_tmp

(46 functions, 6 classes)

### tests/test_jot_dispatch.py

- _stub_prompt_disp
- test_dispatchMain_leading_whitespace_in_prompt_tolerated
- test_dispatchMain_jot_namespace_normalises_to_bare_skill
- test_dispatchMain_default_prompt_exits_zero
- test_dispatchMain_unknown_argv_falls_through_to_stdin_mode
- base_env
- _stub_passing_deps
- _stdin
- test_missing_plugin_env_raises
- test_non_jot_input_exits_zero_silently
- test_prompt_not_strict_jot_exits_zero
- test_empty_idea_emits_block
- test_missing_repo_emits_block
- test_happy_path_writes_input_file_with_all_sections
- _record_calls
- _rebuild_argv_dispatch
- test_argv_dispatch_unpacks_args_positionally
- test_promptDispatch_routesPrefixToMatchingMain
- test_promptDispatch_rewritesJotNamespaceToBareSkill
- test_promptDispatch_unknownPrefixInvokesNothing

(20 functions, 0 classes)

### tests/test_jot_e2e_wiring.py

- test_jotPrompt_e2e_routesTo_jot_main_emitsNoIdeaBlock

(1 functions, 0 classes)

### tests/test_jot_phase2.py

- test_jot_sendPrompt_delegates_to_tmux_sendAndSubmit_with_target_and_prompt
- test_jot_sendPrompt_returns_nonzero_when_tmux_helper_fails
- test_jot_sendPrompt_input_path_interpolated_verbatim
- phase2_env
- _phase2_patches
- _enter_phase2_patches
- _exit_phase2_patches
- test_jot_launchPhase2Window_initializes_state_dir_under_repo_root_todos
- test_jot_launchPhase2Window_acquires_global_tmux_lock_with_10s_timeout
- test_jot_launchPhase2Window_returns_1_if_lock_acquire_times_out
- test_jot_launchPhase2Window_pane_counter_increments_modulo_20
- test_jot_launchPhase2Window_pane_counter_wraps_from_20_to_1
- test_jot_launchPhase2Window_split_failure_releases_lock_and_returns_1
- test_jot_launchPhase2Window_writes_pane_id_atomically_via_tmp_then_rename
- test_jot_launchPhase2Window_calls_tmux_helpers_in_required_order
- test_jot_launchPhase2Window_ensure_session_called_with_jot_jots_session_window
- test_jot_launchPhase2Window_split_worker_called_with_built_claude_cmd
- test_jot_launchPhase2Window_spawn_terminal_called_after_lock_released
- test_missing_input_file_returns_0_and_warns
- test_missing_tmpdir_inv_returns_0_and_warns
- test_sidecar_empty_after_retries_returns_0
- test_sidecar_zero_byte_file_treated_as_empty
- test_readiness_timeout_returns_1
- test_happy_path_sends_read_prompt_to_resolved_pane
- test_sidecar_first_line_only_used
- test_readiness_called_with_resolved_pane_id
- base_env
- _stub_passing_deps
- _stdin
- test_skip_launch_does_not_call_phase2
- test_phase2_called_on_happy_path

(31 functions, 0 classes)

### tests/test_jot_state.py

- test_jot_initState_creates_state_directory_when_missing
- test_jot_initState_creates_three_tracked_files
- test_jot_initState_preserves_existing_queue_contents
- test_jot_initState_preserves_existing_audit_log
- test_jot_initState_idempotent_on_second_call
- test_jot_initState_creates_parent_directories
- test_jot_initState_accepts_string_path
- test_jot_initState_touch_refreshes_mtime_on_existing_file
- _seed_jot_state
- test_jot_popFirstFromQueue_returns_first_line
- test_jot_popFirstFromQueue_removes_first_line_from_queue_file
- test_jot_popFirstFromQueue_writes_popped_line_to_active_job_file
- test_jot_popFirstFromQueue_returns_none_on_empty_queue
- test_jot_popFirstFromQueue_empty_queue_does_not_modify_active_job
- test_jot_popFirstFromQueue_single_entry_queue_becomes_empty

(15 functions, 0 classes)

### tests/test_jot_stop.py

- _writeSidecar
- kill_calls
- jot_dirs
- test_jot_stop_missingArgsReturnsZeroAndLogsToStderr
- test_jot_stop_emptySidecarRetriesThenReturnsZero
- test_jot_stop_writesSuccessAuditLineWhenInputHasProcessedMarker
- test_jot_stop_writesFailAuditLineWhenInputHasNoProcessedMarker
- test_jot_stop_writesFailAuditLineWhenInputFileMissing
- test_jot_stop_killsPaneAndRetilesAfterAuditWrite
- test_jot_stop_initializesStateDirArtifacts
- test_jot_stop_rotatesAuditLogToOneThousandLines
- test_removes_tmp_jot_directory_recursively
- test_refuses_path_outside_safelist
- test_refuses_empty_argument
- test_accepts_private_tmp_jot_prefix
- test_missing_directory_is_silent_success
- test_refuses_lookalike_prefix

(17 functions, 0 classes)

### tests/test_legacy_archive_treesRemoved.py

- legacy_archiveTreeRoots
- legacy_grepArchiveTreeReferences
- test_legacyArchiveTrees_areRemoved
- test_noLiveReferencesToDeletedArchiveTrees

(4 functions, 0 classes)

### tests/test_legacy_shimsRemoved.py

- test_gitTestFuncsLibShim_isRemovedFromPlateLib
- test_runAndCurrentTimestampMsShim_isRemovedFromGitLib
- test_gitTestFuncsLibSymbols_resolveFromCanonical
- test_runAndCurrentTimestampMs_resolveFromCanonical

(4 functions, 0 classes)

### tests/test_migrationAudit_isClean.py

- audit_regenerateMigrationDocument
- test_migrationAuditDocument_hasNoNeedsMarkers

(2 functions, 0 classes)

### tests/test_plate_main.py

- _stub_argv
- _stub_prompt_disp
- _base_env_pm
- _make_payload_pm
- _make_deps_pm
- _expected_repo_root_pm
- test_plateMain_missing_plugin_root_raises
- test_plateMain_missing_plugin_data_raises
- test_plateMain_non_plate_input_exits_0_silently
- test_plateMain_bad_json_after_fast_path_exits_0
- test_plateMain_typo_prompt_exits_0_silently
- test_plateMain_prompt_with_leading_whitespace_is_accepted
- test_plateMain_missing_repo_root_emits_friendly_message
- _get_cli_args_pm
- test_plateMain_dispatch_bare_plate_is_push
- test_plateMain_dispatch_done
- test_plateMain_dispatch_drop
- test_plateMain_dispatch_trash
- test_plateMain_dispatch_recycle
- test_plateMain_dispatch_recycle_list
- test_plateMain_dispatch_recycle_named
- test_plateMain_dispatch_show
- test_plateMain_dispatch_next
- test_plateMain_dispatch_next_named
- test_plateMain_unrecognized_variant_emits_message
- test_plateMain_cli_output_forwarded_via_emit_block
- test_plateMain_cli_stderr_included_in_emit_block
- test_plateMain_log_file_promoted_to_per_repo_path_when_no_override
- test_plateMain_log_file_override_respected
- test_dispatchMain_newline_after_slashcommand_tolerated

(30 functions, 0 classes)

### tests/test_plate_module_layout.py

- _repoRoot
- plate_collectAllPlateLibModuleFiles
- plate_resolveDispatcherPlateMainFile
- test_plate_lib_singleSourceOfTruth
- test_plate_dispatcherImportPath_resolvesToRenamedModule

(5 functions, 0 classes)

### tests/test_plate_set_summary_cli.py

- test_missing_repo_arg_is_noop
- test_missing_branch_arg_is_noop
- test_missing_output_file_arg_is_noop
- test_nonexistent_output_file_is_noop
- test_invokes_cli_set_plate_summary_with_args
- test_writes_audit_log_line
- test_cli_failure_is_swallowed

(7 functions, 0 classes)

### tests/test_plate_summary_watch.py

- test_returns_zero_when_output_file_already_non_empty
- test_sends_exit_then_enter_when_file_becomes_non_empty
- test_returns_one_on_timeout_without_sending
- test_empty_file_is_treated_as_not_ready
- test_swallows_tmux_send_errors_and_still_returns_zero
- test_env_overrides_supply_default_timeout_and_interval

(6 functions, 0 classes)

### tests/test_tmux_communicate.py

- _make_fake_run
- test_tmux_sendKeys_invokes_tmux_send_keys_with_dash_t_target_then_text
- test_tmux_sendKeys_returns_zero_on_success
- test_tmux_sendKeys_returns_nonzero_and_logs_caller_when_target_missing
- test_tmux_sendKeys_passes_text_with_special_chars_unchanged
- test_tmux_sendEnter_invokes_tmux_send_keys_with_dash_t_target_and_literal_Enter_token
- test_tmux_sendEnter_returns_zero_on_success
- test_tmux_sendEnter_returns_nonzero_and_logs_caller_when_target_missing
- test_tmux_sendCtrlC_invokes_tmux_send_keys_with_dash_t_target_and_literal_C_dash_c_token
- test_tmux_sendCtrlC_returns_zero_on_success
- test_tmux_sendCtrlC_returns_nonzero_and_logs_caller_when_target_missing
- test_tmux_sendAndSubmit_calls_sendKeys_then_sendEnter_with_same_target
- test_tmux_sendAndSubmit_returns_zero_when_both_sends_succeed
- test_tmux_sendAndSubmit_short_circuits_when_sendKeys_fails
- test_tmux_sendAndSubmit_returns_sendEnter_rc_when_only_sendEnter_fails
- test_tmux_sendAndSubmit_sleeps_between_sendKeys_and_sendEnter
- test_tmux_cancelAndSend_stops_retrying_once_marker_seen
- test_tmux_cancelAndSend_caps_at_five_attempts_and_still_submits
- test_tmux_cancelAndSend_returns_rc_from_final_send
- test_tmux_cancelAndSend_logs_label_when_retry_needed
- test_tmux_cancelAndSend_omits_log_when_first_attempt_succeeds
- live_tmux_session
- test_sendKeys_returnsZero_onLiveSession
- test_sendKeys_textVisible_inPaneCapture
- test_sendCtrlC_returnsZero_onLiveSession
- test_sendEnter_returnsZero_onLiveSession
- test_sendAndSubmit_returnsZero_onLiveSession
- test_sendAndSubmit_outputVisible_inPaneCapture
- test_sendKeys_returnsNonzero_onNonexistentTarget
- test_sendEnter_returnsNonzero_onNonexistentTarget

(30 functions, 0 classes)

### tests/test_tmux_configure.py

- class _FakeCompleted
  - _FakeCompleted.__init__
- test_tmux_setOption_invokes_tmux_set_option_with_passed_args_and_returns_zero_on_success
- test_tmux_setOption_emits_no_output_when_tmux_succeeds_with_empty_stdout
- test_tmux_setOption_logs_caller_name_and_combined_output_to_stderr_when_tmux_fails
- test_tmux_setOption_passes_variadic_args_through_to_tmux_in_order
- test_tmux_setOptionForTarget_passes_target_flag_then_target_then_name_then_value_to_tmux_setOption
- test_tmux_setOptionForTarget_returns_the_exit_code_from_tmux_setOption
- test_tmux_setOptionGlobally_passes_dash_g_flag_then_name_then_value_to_tmux_setOption
- test_tmux_setOptionGlobally_returns_the_exit_code_from_tmux_setOption
- test_tmux_setOptionForWindow_passes_dash_w_then_dash_t_then_target_then_name_then_value_to_tmux_setOption
- test_tmux_setOptionForWindow_returns_the_exit_code_from_tmux_setOption
- _make_fake_run
- test_tmux_selectPane_invokes_tmux_select_pane_with_dash_t_target
- test_tmux_selectPane_returns_zero_on_success
- test_tmux_selectPane_returns_nonzero_and_logs_caller_when_select_fails
- test_tmux_setPaneTitle_invokes_tmux_select_pane_with_dash_t_target_and_dash_T_title
- test_tmux_setPaneTitle_returns_zero_on_success
- test_tmux_setPaneTitle_returns_nonzero_and_logs_caller_when_target_missing
- test_tmux_selectLayout_invokes_tmux_select_layout_with_dash_t_target_then_layout_name
- test_tmux_selectLayout_returns_zero_on_success
- test_tmux_selectLayout_returns_nonzero_and_logs_caller_when_layout_invalid
- test_tmux_retile_invokes_tmux_selectLayout_with_tiled_for_the_given_target
- test_tmux_retile_returns_the_exit_code_from_tmux_selectLayout
- tmux_session_opts
- test_setOptionForWindow_rejects_nonexistent_window
- test_setOptionForWindow_accepts_valid_window_option
- test_setOptionGlobally_rejects_invalid_option
- test_setOptionGlobally_accepts_valid_global_option
- test_setOptionForTarget_rejects_nonexistent_target
- test_setOptionForTarget_rejects_invalid_option
- test_setOptionForTarget_accepts_valid_session_option
- tmux_session_panes
- _first_pane_id
- test_selectPane_byKnownPaneId_succeeds
- test_setPaneTitle_succeeds
- test_setPaneTitle_roundTripsThroughListPanes
- test_selectPane_failsOnNonexistentTarget
- layout_session
- test_selectLayout_tiled_succeeds
- test_selectLayout_evenHorizontal_succeeds
- test_selectLayout_invalidName_fails
- test_retile_succeeds
- test_retile_nonexistentTarget_fails

(43 functions, 1 classes)

### tests/test_tmux_create.py

- _make_fake_run
- test_tmux_newSession_invokes_tmux_new_session_with_dash_d_dash_s_and_session_name
- test_tmux_newSession_returns_zero_on_success
- test_tmux_newSession_returns_nonzero_and_logs_caller_when_creation_fails
- test_tmux_newSession_passes_extra_args_through_to_tmux_after_session_name
- test_tmux_newPane_invokes_tmux_split_window_with_dash_t_target
- test_tmux_newPane_returns_zero_on_success
- test_tmux_newPane_returns_nonzero_and_logs_caller_when_split_fails
- test_tmux_newPane_passes_extra_args_through_after_target
- test_tmux_newPane_prints_stdout_to_caller_on_success
- test_tmux_newWindow_invokes_tmux_new_window_with_dash_t_session_and_dash_n_window
- test_tmux_newWindow_returns_zero_on_success
- test_tmux_newWindow_returns_nonzero_and_logs_caller_when_creation_fails
- test_tmux_newWindow_passes_extra_args_through_after_window_name
- test_tmux_splitWindow_invokes_tmux_split_window_with_dash_h_for_horizontal
- test_tmux_splitWindow_invokes_tmux_split_window_with_dash_v_for_vertical
- test_tmux_splitWindow_returns_zero_on_success
- test_tmux_splitWindow_returns_nonzero_and_logs_caller_when_split_fails
- test_tmux_splitWindow_raises_ValueError_for_invalid_direction
- class _FakeCompleted
  - _FakeCompleted.__init__
- test_tmux_splitWorkerPane_returns_pane_id_on_success
- test_tmux_splitWorkerPane_returns_None_when_tmux_fails
- test_tmux_splitWorkerPane_returns_None_when_pane_id_blank
- test_tmux_splitWorkerPane_logs_caller_attributed_stderr_on_failure
- test_tmux_ensureKeepalivePane_returns_early_when_pane_with_title_exists
- test_tmux_ensureKeepalivePane_creates_pane_sets_title_and_retiles_when_absent
- test_tmux_ensureKeepalivePane_skips_set_title_when_split_returns_none
- test_tmux_ensureSession_creates_session_when_absent
- test_tmux_ensureSession_creates_window_when_session_exists_but_window_absent
- test_tmux_ensureSession_delegates_to_keepalive_pane_when_both_exist
- session_name
- test_newSession_createsSession
- test_newSession_rejectsDuplicate
- tmux_session_panes
- test_newPane_addsPaneToSession
- test_newPane_failsOnNonexistentSession
- _tmux_has_session
- _tmux_window_exists
- _tmux_pane_has_title
- _tmux_show_option
- _kill
- tmux_session_clean
- test_ensure_session_creates_new_session
- test_ensure_session_sets_keepalive_pane_title
- test_ensure_session_applies_pane_border_status_top
- test_split_worker_pane_returns_pane_id
- test_ensure_session_idempotent_on_existing_session
- test_ensure_session_adds_new_window_to_existing_session
- _writeSidecar
- kill_calls
- fake_tmux
- _make_tmpdir

(52 functions, 1 classes)

### tests/test_tmux_destroy.py

- _make_fake_run
- test_tmux_killSession_invokes_tmux_kill_session_with_dash_t_target
- test_tmux_killSession_returns_zero_on_success
- test_tmux_killSession_returns_nonzero_and_logs_caller_when_kill_fails
- test_tmux_killPane_invokes_tmux_kill_pane_with_dash_t_target
- test_tmux_killPane_returns_zero_on_success
- test_tmux_killPane_returns_nonzero_and_logs_caller_when_kill_fails
- test_tmux_killWindow_invokes_tmux_kill_window_with_dash_t_target
- test_tmux_killWindow_returns_zero_on_success
- test_tmux_killWindow_returns_nonzero_and_logs_caller_when_window_missing
- session_name
- test_killSession_fails_onNonexistentSession
- test_killSession_succeeds_onExistingSession
- tmux_session_panes
- test_killPane_removesLivePane
- test_killPane_failsOnNonexistentTarget

(16 functions, 0 classes)

### tests/test_tmux_monitor.py

- test_tmux_waitForClaudeReadiness_returns_zero_when_glyph_present_immediately
- test_tmux_waitForClaudeReadiness_returns_one_on_timeout_and_logs_stderr
- test_tmux_waitForClaudeReadiness_polls_until_ready
- test_tmux_waitForClaudeReadiness_swallows_capture_errors
- test_tmux_waitForClaudeReadiness_default_timeout_is_ten_seconds
- test_tmux_waitForClaudeReadiness_passes_pane_id_and_five_line_window

(6 functions, 0 classes)

### tests/test_tmux_read.py

- _stdin
- class _FakeProc
  - _FakeProc.__init__
- test_tmux_requireVersion_returns_1_and_logs_when_tmux_binary_is_missing
- test_tmux_requireVersion_returns_0_when_installed_version_exactly_matches_required
- test_tmux_requireVersion_returns_0_when_installed_version_exceeds_required
- test_tmux_requireVersion_returns_1_and_logs_when_installed_version_is_below_required
- test_tmux_requireVersion_returns_1_when_tmux_version_output_is_unparseable
- _make_fake_run
- test_tmux_hasSession_returns_zero_when_session_exists
- test_tmux_hasSession_returns_one_when_session_does_not_exist
- test_tmux_hasSession_invokes_tmux_has_session_with_dash_t_target
- test_tmux_hasSession_does_not_log_to_stderr_when_session_is_simply_absent
- test_tmux_hasSession_logs_caller_name_to_stderr_on_unexpected_nonzero_rc
- test_tmux_listClients_invokes_tmux_list_clients_with_dash_t_session_name
- test_tmux_listClients_returns_empty_list_when_no_clients_attached
- test_tmux_listClients_returns_one_string_per_client_line_on_stdout
- test_tmux_listClients_returns_empty_list_and_logs_caller_when_session_not_found
- test_tmux_capturePane_invokes_tmux_capture_pane_with_dash_p_dash_t_target_when_no_scrollback_requested
- test_tmux_capturePane_returns_pane_stdout_text_on_success
- test_tmux_capturePane_includes_dash_S_negative_offset_when_scrollback_lines_given
- test_tmux_capturePane_returns_empty_string_and_logs_caller_when_target_missing
- test_tmux_listPanes_uses_default_pane_id_and_title_format_when_no_extras_given
- test_tmux_listPanes_passes_extra_args_through_when_extras_given_and_omits_default_format
- test_tmux_listPanes_returns_one_string_per_pane_line
- test_tmux_listPanes_returns_empty_list_when_no_panes_in_stdout
- test_tmux_listPanes_returns_empty_list_and_logs_caller_when_target_missing
- test_tmux_listWindows_uses_default_window_index_and_name_format_when_no_extras_given
- test_tmux_listWindows_passes_extra_args_through_when_extras_given_and_omits_default_format
- test_tmux_listWindows_returns_one_string_per_window_line
- test_tmux_listWindows_returns_empty_list_when_no_windows_in_stdout
- test_tmux_listWindows_returns_empty_list_and_logs_caller_when_session_missing
- test_tmux_windowExists_returns_zero_when_window_name_appears_in_listed_windows
- test_tmux_windowExists_returns_one_when_window_name_not_in_listed_windows
- test_tmux_windowExists_uses_exact_match_not_substring
- test_tmux_windowExists_invokes_tmux_listWindows_with_F_window_name_format
- test_tmux_paneHasTitle_returns_zero_when_title_appears_in_listed_panes
- test_tmux_paneHasTitle_returns_one_when_title_not_in_listed_panes
- test_tmux_paneHasTitle_uses_exact_match_not_substring
- test_tmux_paneHasTitle_invokes_tmux_listPanes_with_F_pane_title_format
- test_tmux_too_old_emits_block
- session_name
- test_hasSession_returnsFalse_afterKill
- test_hasSession_returnsFalse_forNonexistentSession
- test_hasSession_returnsTrue_forExistingSession
- tmux_session_panes
- _first_pane_id
- test_listPanes_newSession_hasOnePane
- test_listPanes_afterNewPane_hasTwoPanes
- test_capturePane_returnsContent
- test_listPanes_afterKillPane_hasOnePane

(50 functions, 1 classes)

### tests/test_todo_capture.py

- _set_stdin
- _base_env
- _patch_repo_root
- test_missing_plugin_data_raises
- test_non_todo_input_exits_zero_silently
- test_bad_prompt_format_exits_zero
- test_missing_git_repo_emits_block
- test_happy_path_writes_valid_pending_json
- test_idea_with_quotes_and_newlines_round_trips
- test_bare_todo_yields_empty_idea

(10 functions, 0 classes)

### tests/test_todo_e2e_wiring.py

- test_todoPrompt_e2e_routesTo_todo_main_writesPendingClaimFile
- test_todoListPrompt_e2e_routesTo_todoList_main_emitsNoTodosFolderBlock

(2 functions, 0 classes)

### tests/test_todo_list.py

- _setStdin
- test_non_todoList_prompt_exits_silently
- test_bad_prompt_after_fast_path_exits_silently
- test_missing_repo_emits_not_a_git_repo
- test_missing_todos_folder_emits_message
- test_empty_formatter_output_emits_no_open_todos
- test_non_empty_formatter_output_is_forwarded
- test_returns_empty_list_when_todos_dir_missing
- _write
- test_returns_empty_list_when_todos_dir_has_no_markdown
- test_returns_only_files_with_status_open_in_frontmatter
- test_results_are_sorted_alphabetically_like_bash_glob
- test_status_open_must_anchor_at_line_start
- test_only_first_ten_lines_are_inspected
- test_returns_absolute_paths
- test_accepts_string_path_argument

(16 functions, 0 classes)

### tests/test_todo_send.py

- test_todo_launcher_success
- test_missing_input_file_returns_0
- test_missing_tmpdir_inv_returns_0
- test_missing_sidecar_returns_0
- test_empty_sidecar_returns_0
- test_claude_not_ready_returns_1
- test_happy_path_sends_prompt
- test_happy_path_propagates_send_rc
- test_sidecar_read_strips_whitespace

(9 functions, 0 classes)

### tests/test_todo_stop.py

- base_env
- _stub_passing_deps
- _stdin
- test_safe_wrapper_falls_back_to_unavailable
- test_empty_string_is_rejected
- test_nonexistent_valid_path_is_silently_ignored
- test_valid_tmp_prefix_calls_rmtree
- test_valid_tmp_prefix_suffix_variation
- test_valid_private_tmp_prefix_calls_rmtree
- test_invalid_prefix_prints_stderr_and_skips_rmtree
- test_invalid_prefix_leaves_directory_intact
- test_missing_args_returns_early
- _make_tmpdir
- test_missing_state_dir_returns_early
- test_empty_sidecar_logs_and_returns
- test_missing_sidecar_file_logs_and_returns
- test_processed_marker_writes_success_to_audit
- test_processed_marker_removes_input_file
- test_no_processed_marker_writes_fail_to_audit
- test_no_processed_marker_does_not_remove_input_file
- test_missing_input_file_writes_fail_missing_to_audit
- test_audit_rotated_when_over_1000_lines
- test_kill_pane_called_with_correct_target
- test_retile_called_with_todo_todos_window
- test_state_dir_created_if_absent

(25 functions, 0 classes)

### tests/test_util_filelock.py

- _hold_lock_worker
- _try_acquire_worker
- test_FileLock_acquire_succeeds_on_fresh_path
- test_FileLock_release_clears_acquired_state
- test_FileLock_reacquire_after_release
- test_FileLock_release_is_idempotent_when_not_held
- test_FileLock_competing_process_blocks_until_holder_releases
- test_FileLock_timeout_elapses_when_lock_is_held
- test_FileLock_auto_released_when_holder_process_dies
- _write_lock
- _write_lock_at_path
- _make_lock
- _write

(13 functions, 0 classes)

### tests/test_util_shell.py

- test_shell_runWithTimeout_returns_zero_for_successful_fast_command
- test_shell_runWithTimeout_returns_nonzero_for_failing_fast_command
- test_shell_runWithTimeout_kills_command_that_exceeds_timeout
- test_shell_runWithTimeout_returns_promptly_when_command_finishes_early
- test_shell_runWithTimeout_kills_process_that_ignores_sigterm
- test_returns_true_when_file_already_nonempty
- test_returns_false_when_file_never_appears
- test_returns_false_when_file_exists_but_empty
- test_returns_true_when_file_appears_during_polling
- _read
- _write

(11 functions, 0 classes)

### tests/test_util_terminal.py

- test_terminal_spawnIfNeeded_empty_session_raises_value_error
- test_terminal_spawnIfNeeded_skips_spawn_when_clients_attached
- test_terminal_spawnIfNeeded_darwin_spawns_osascript_with_attach_command
- test_terminal_spawnIfNeeded_darwin_maximize_yes_includes_full_desktop_block
- test_terminal_spawnIfNeeded_darwin_maximize_compact_includes_centred_1000x700_block
- test_terminal_spawnIfNeeded_darwin_missing_osascript_writes_advisory_and_returns_zero
- test_terminal_spawnIfNeeded_non_darwin_writes_advisory_and_does_not_spawn
- test_terminal_spawnIfNeeded_dev_null_log_does_not_create_file
- test_terminal_spawnIfNeeded_advisory_write_failure_is_swallowed
- test_darwin_terminal_not_running_launches_terminal
- test_darwin_terminal_already_running_skips_launch
- test_non_darwin_never_launches_terminal
- _noop
- _make_main_mock
- test_terminal_launch_before_debate_main

(15 functions, 0 classes)

## (other)

### audit_gen.py

- list_definitions
- section_for
- main

(3 functions, 0 classes)

### plans/rename_funcs.py

- loadConfig
- buildSubstitutionPlan
- renameOneFile
- main

(4 functions, 0 classes)

---

**Totals:** 96 files, 1369 functions, 27 classes.

