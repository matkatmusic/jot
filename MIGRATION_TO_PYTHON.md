# Python function audit

Authoritative list of top-level functions and classes (with one level of method nesting) for every Python file in this worktree. Used as input when deciding how to split large modules into smaller, area-focused files.

Last generated: 2026-05-07

Regenerate from the worktree root with:

```
python3 audit_gen.py > MIGRATION_TO_PYTHON.md
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

### common/scripts/plate/cli.py

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

### common/scripts/plate/plate_lib.py

- createRandomBranchName
- makeEmptyRepo — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- makeTestRepo — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- makeTestRepoWithSingleCommit — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- makeTestFile — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- random_string
- modifyTrackedFile — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- modifyRandomlyChosenTrackedFile — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- createUntrackedFile — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- setup_git_plate_test_repo — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- performRandomEdit
- setup_repo — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- formatPlateAge
- localTranscriptIsReadable
- extractConvoNameFromTranscript
- extractConvoCwdFromTranscript
- extractFilesEditedSinceTimestamp
- _writeFakeTranscriptWithToolUse
- _parseRmTargets
- listPlateBranches
- findMyLastPlate
- _resolveTargetPlate
- _buildFullWtTree
- _buildExtractedTree
- _formatTrailerBody
- plate_push
- plate_done
- currentTimestampUtcCompact — NEEDS_MIGRATION_TO: git_test_funcs_lib.py
- _trashBranchDir
- _writeTrashSession
- _listTrashSessions
- plate_drop
- plate_trash
- plate_recycle_list
- stripConvoSummaryFromCommit
- regenerateTipSummary
- plate_recycle
- plate_next
- _resolvePlateTitle
- _plate_next_list
- _plate_next_jump
- simulate_derived_agent
- extractFilesDeletedSinceTimestamp
- _writeTranscriptFile
- _buildTwoBranchPlateTopology
- rewriteBranchTipSummary

(46 functions, 0 classes)

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
- _build_r1
- _build_r2
- _build_synthesis
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
- _launch_agent
- _send_prompt
- debate_probeGemini
- debate_launchAgentsParallel
- debate_newEmptyPane
- debateAbort_main
- debate_startOrResume
- debate_main
- debateRetry_main
- debate_daemonMain

(42 functions, 3 classes)

### common/scripts/git_lib.py

- run [MOVE_TO: util_lib.py]
- currentTimestampMs [MOVE_TO: util_lib.py]
- makeGitRepo [Creator]
- isGitRepo [Checker]
- setGitUserConfigValue [Modifier]
- getGitUserConfigValue [Reader]
- writeGitIgnore [Modifier]
- createGitUserConfig [Creator]
- getGitBranchList [Reader]
- createGitBranch [Creator]
- checkOutGitBranch [Modifier]
- createAndCheckoutGitBranch [Creator]
- getCurrentGitBranchName [Reader]
- getGitUntrackedFilesList [Reader]
- getGitUnstagedFilesList [Reader]
- getGitStagedFilesList [Reader]
- getGitTrackedFilesList [Reader]
- addFileToGit [Modifier]
- stageAllGitChanges [Modifier]
- gitStashFiles [Modifier]
- gitUnstashFiles [Modifier]
- addMultipleFilesToGit [Modifier]
- createGitCommit [Creator]
- checkIfGitBranchExists [Checker]
- countGitCommitsReachableFromRef [Reader]
- setGitIndexFileForEnv [Modifier]
- getSHAForGitRefViaRevParse [Reader]
- readGitTreeAt [Reader]
- writeGitTree [Creator]
- getGitTreeRevOf [Reader]
- getGitTreeSHA [Reader]
- getGitStatus [Reader]
- checkGitForCleanWorkTree [Checker]
- getGitCommitSubject [Reader]
- getGitCommitTrailers [Reader]
- gitResetHardToHead [Destroyer]
- gitCleanWorkTree [Destroyer]
- deleteGitBranchByForce [Destroyer]
- saveChangesToGitPatch [Creator]
- makeTempGitIndexPath [Creator]
- applyGitPatch [Modifier]
- class GitError [Exception type]
- getGitRepoRoot [Reader]
- getGitBranchNameOrFail [Reader]
- getGitRecentCommitHashes [Reader]
- getGitUncommittedFilenames [Reader]
- ensureGitignoreEntry [Modifier]
- _gitRepoRoot [Reader]
- _git_get_repo_root [Reader]

(48 functions, 1 classes)

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
- _jotDefaultPermissionsSeed
- _jotDefaultExpandPermissions
- _jotAppendLog
- jot_launchPhase2Window
- _readSidecar
- jot_diagSection
- jot_diagIndent
- jot_diagKv
- jot_collectDiagnostics
- jot_sessionEnd
- jot_sessionStart
- jot_stop
- jot_main

(18 functions, 0 classes)

### common/scripts/plate_lib.py

- plate_summaryStop
- plate_summaryWatch
- plate_main

(3 functions, 0 classes)

### common/scripts/tmux_lib.py

- tmux_requireVersion [Read]
- tmux_setOption [Configure]
- tmux_setOptionForTarget [Configure]
- tmux_setOptionGlobally [Configure]
- tmux_setOptionForWindow [Configure]
- tmux_hasSession [Read]
- tmux_newSession [Create]
- tmux_killSession [Destroy]
- tmux_listClients [Read]
- tmux_newPane [Create]
- tmux_killPane [Destroy]
- tmux_capturePane [Monitor]
- tmux_listPanes [Read]
- tmux_selectPane [Configure]
- tmux_setPaneTitle [Configure]
- tmux_newWindow [Create]
- tmux_killWindow [Destroy]
- tmux_listWindows [Read]
- tmux_windowExists [Read]
- tmux_paneHasTitle [Read]
- tmux_splitWindow [Create]
- tmux_selectLayout [Configure]
- tmux_retile [Configure]
- tmux_sendKeys [Communicate]
- tmux_sendEnter [Communicate]
- tmux_sendCtrlC [Communicate]
- tmux_sendAndSubmit [Communicate]
- tmux_cancelAndSend [Communicate]
- tmux_splitWorkerPane [Create]
- tmux_waitForClaudeReadiness [Monitor]
- tmux_ensureKeepalivePane [Create]
- tmux_ensureSession [Create]
- _default_tmux_runner [Internal helper]
- _run_tmux [Internal helper]
- _tmux_session_exists [Read]
- _default_tmux_send [Internal helper]
- _backgroundKill [Destroy]
- _live_pane_ids [Read]
- _kill_pane [Destroy]
- _paneCurrentCommand [Read]
- _listLivePaneIds [Read]

(41 functions, 0 classes)

### common/scripts/todo_lib.py

- jot_sendPrompt
- todoList_main
- todo_main
- todo_sessionEnd
- todo_launcher
- todo_stop
- todo_sessionStart
- _has_open_status
- todo_scanOpen

(9 functions, 0 classes)

### common/scripts/util_lib.py

- _matches_prefix [Util]
- _slugify [Util]
- _resolvePluginRoot [Util]
- _safe_call [Util]
- _strip_stdin_text [Util]
- _append_log [Util]
- _hide_errors [Util]
- _appendAudit [Util]
- _readSidecar [Util]
- _isoTimestampLocal [Util]
- shell_waitForFile [Util]
- terminal_spawnIfNeeded [Terminal]
- _ls_latest_input_txt [Util]
- _tail_lines [Util]
- _launch_terminal_background [Terminal]
- _terminal_running [Terminal]
- _terminalListTmuxClients [Terminal]
- _terminalBuildOsascript [Terminal]
- _terminalIsoNow [Terminal]
- _terminalAppendAdvisory [Terminal]
- _terminalAppendNonDarwinAdvisory [Terminal]
- _terminalMaximizeBlock [Terminal]
- shell_runWithTimeout [Util]
- _readFirstToken [Util]
- _sha256File [Util]
- class LockTimeout [FileLock]
- class FileLock [FileLock]
  - FileLock.__init__ [FileLock]
  - FileLock.path [FileLock]
  - FileLock.acquired [FileLock]
  - FileLock.acquire [FileLock]
  - FileLock.release [FileLock]
  - FileLock.__enter__ [FileLock]
  - FileLock.__exit__ [FileLock]
- _valid_kwargs [Util]

(33 functions, 2 classes)

## scripts/

### scripts/jot_plugin_orchestrator.py

- dispatch_main

(1 functions, 0 classes)

## skills/plate/tests/sequence/

### skills/plate/tests/sequence/test_cli.py — NEEDS_RENAME_TO: test_plate_cli.py (all tests are plate-specific)

- _run [test harness — wraps cli.main(argv) + captures stdout; NOT a duplicate of git_lib.run]
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

### skills/plate/tests/sequence/test_e2e_wiring.py — NEEDS_RENAME_TO: test_plate_e2e_wiring.py (all tests run plate-orchestrator.sh)

- _run_hook [Plate test harness — invokes plate-orchestrator.sh]
- _parse_block [Plate test harness — parses plate hook block JSON]
- empty_repo [Plate fixture]
- test_next_list_mode_returns_empty_list_message [Plate]
- test_next_jump_non_numeric_returns_message [Plate]
- test_show_returns_todo_stub [Plate — name is misleading; tests `/plate --show` which currently returns the literal string "TODO" as a stub. NOT a TODO-skill test.]
- test_drop_no_plate_returns_message [Plate]
- test_push_on_empty_wt_returns_no_changes [Plate]
- test_push_with_dirty_wt_creates_plate_branch [Plate]
- test_unrelated_prompt_exits_silently [Plate — tests plate hook fast-path bailout]
- test_typo_variant_exits_silently [Plate — tests plate hook bailout on typo'd variant]

(11 functions, 0 classes)

### skills/plate/tests/sequence/test_helpers.py — NEEDS_SPLIT: 4 groups (git / git_test_funcs / convo / plate / plate sequences). Many [git] entries are DUPLICATES of tests/test_git_lib.py and should be deleted, not moved.

- test_run [git — DUPLICATE_OF: tests/test_git_lib.py::test_run]
- test_makeEmptyRepo [git_test_funcs]
- test_writeGitIgnore [git — DUPLICATE_OF: tests/test_git_lib.py::test_writeGitIgnore]
- test_makeTestRepoWithSingleCommit [git_test_funcs]
- test_setGitUserConfigValue [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_createGitUserConfig [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_createGitBranch [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_checkOutGitBranch [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_createAndCheckoutGitBranch [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_getCurrentGitBranchName [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_makeTestFile [git_test_funcs]
- test_stashFiles [git — DUPLICATE_OF: tests/test_git_lib.py::test_gitStashFiles (renamed)]
- test_unstashFiles [git — DUPLICATE_OF: tests/test_git_lib.py::test_gitUnstashFiles (renamed)]
- test_addFileToGit [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_stageFiles [git — DUPLICATE_OF: tests/test_git_lib.py::test_stageFiles]
- test_createCommit [git — DUPLICATE_OF: tests/test_git_lib.py::test_createGitCommit (renamed)]
- test_modifyTrackedFile [git_test_funcs]
- test_modifyRandomlyChosenTrackedFile [git_test_funcs]
- test_createUntrackedFile [git_test_funcs]
- test_setup_repo [git_test_funcs]
- test_performRandomEdit_modify_tracked [git_test_funcs]
- test_performRandomEdit_create_untracked_when_tracked_exists [git_test_funcs]
- test_performRandomEdit_no_tracked_forces_create_untracked [git_test_funcs]
- test_performRandomEdit_seeded_is_deterministic [git_test_funcs — also appears below; INTERNAL_DUPLICATE]
- test_performRandomEdit_seeded_is_deterministic_simple [git_test_funcs]
- test_branchExists [git — DUPLICATE_OF: tests/test_git_lib.py::test_checkIfGitBranchExists (renamed)]
- test_countGitCommitsReachableFromRef [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_getSHAForRefViaRevParse [git — DUPLICATE_OF: tests/test_git_lib.py::test_getSHAForGitRefViaRevParse (renamed)]
- test_readWriteGitTree [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_getTreeRevOf [git — DUPLICATE_OF: tests/test_git_lib.py::test_getGitTreeRevOf (renamed)]
- test_getGitStatus [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_checkForCleanWorkTree [git — DUPLICATE_OF: tests/test_git_lib.py::test_checkGitForCleanWorkTree (renamed)]
- test_getCommitSubject [git — DUPLICATE_OF: tests/test_git_lib.py::test_getGitCommitSubject (renamed)]
- test_getGitCommitTrailers [git — DUPLICATE_OF: tests/test_git_lib.py]
- test_resetHardToHead [git — DUPLICATE_OF: tests/test_git_lib.py::test_gitResetHardToHead (renamed)]
- test_cleanWorkTree [git — DUPLICATE_OF: tests/test_git_lib.py::test_gitCleanWorkTree (renamed)]
- test_deleteBranchForce [git — DUPLICATE_OF: tests/test_git_lib.py::test_deleteGitBranchByForce (renamed)]
- test_formatPlateAge [plate]
- test_localTranscriptIsReadable [convo]
- test_extractConvoNameFromTranscript_returns_latest_custom_title [convo]
- test_extractConvoNameFromTranscript_falls_back_to_session_id_when_no_title [convo]
- test_extractConvoNameFromTranscript_returns_none_when_file_missing [convo]
- test_extractConvoNameFromTranscript_skips_unparseable_lines [convo]
- test_extractConvoCwdFromTranscript_returns_first_cwd [convo]
- test_extractConvoCwdFromTranscript_returns_none_when_no_cwd [convo]
- test_extractConvoCwdFromTranscript_returns_none_when_file_missing [convo]
- test_extractFilesEditedSinceTimestamp_filters_by_tool_and_cutoff [convo]
- test_extractFilesDeletedSinceTimestamp [convo]
- test_listPlateBranches [plate]
- test_listPlateBranches_excludes_non_plate_refs [plate]
- test_saveChangesToPatch [git — DUPLICATE_OF: tests/test_git_lib.py::test_saveChangesToGitPatch (renamed)]
- test_findMyLastPlate [plate]
- test_plate_push_1x [plate]
- test_plate_push_with_convo_id [plate]
- test_plate_push_convo_summary_preserves_section_labels_on_own_lines [plate]
- test_plate_push_extraction_uses_explicit_transcript_path_arg [plate]
- test_plate_push_shared_branch_two_agents_isolates_each_authors_changes [plate]
- test_plate_push_omits_convo_trailers_when_kwargs_unset [plate]
- test_plate_done [plate]
- test_plate_drop [plate]
- test_plate_trash [plate]
- test_plate_trash_hard [plate]
- test_plate_recycle [plate]
- test_simulate_derived_agent_first [plate]
- test_simulate_derived_agent_second [plate]
- test_applyGitPatch [git — DUPLICATE_OF: tests/test_git_lib.py::test_applyGitPatch]
- test_plate_drop_no_branch [plate]
- test_plate_trash_no_branch [plate]
- test_plate_recycle_no_branch [plate]
- test_plate_done_resolves_content_conflict_in_plate_favor [plate]
- test_drop_patch_cross_repo_portability [plate]
- test_plate_done_leaves_sha_recoverable [plate]
- test_plate_done_aborts_when_no_plate_branch [plate]
- test_plate_done_aborts_when_wt_differs_from_plate_tip [plate]
- test_plate_next_list_shows_plates_sorted_with_current_marker [plate]
- test_plate_next_jump_restores_plate_tree_without_post_plate_branch_changes [plate]
- test_plate_next_jump_lost_message_when_transcript_unreadable [plate]
- test_plate_next_jump_self_index_is_noop [plate]
- test_plate_next_jump_proceeds_when_head_on_branch_with_no_plate [plate]
- test_plate_next_jump_invalid_index_returns_message [plate]
- test_plate_next_list_empty_when_no_plates [plate]
- test_plate_next_list_no_marker_when_head_has_no_plate [plate]
- test_rewriteBranchTipSummary_strips_old_tip_and_adds_new_tip_summary [plate]
- test_setup_repo_checks_out_non_main_branch [git_test_funcs]
- test_setup_repo_branch_name_is_varied [git_test_funcs]
- test_setup_repo_creates_three_commits [git_test_funcs]
- test_setup_repo_main_has_one_commit [git_test_funcs]
- test_setup_repo_starts_clean [git_test_funcs]
- test_setup_repo_creates_expected_files [git_test_funcs]
- test_setup_repo_has_expected_subjects [git_test_funcs]
- test_setup_repo_diverges_from_main [git_test_funcs]
- test_setup_repo_no_plate_branch_initially [git_test_funcs]
- test_performRandomEdit_dirties_wt [git_test_funcs]
- test_performRandomEdit_returns_action_record [git_test_funcs]
- test_performRandomEdit_modify_tracked_appends_line [git_test_funcs]
- test_performRandomEdit_create_untracked_makes_new_file [git_test_funcs]
- test_performRandomEdit_seeded_is_deterministic [git_test_funcs — INTERNAL_DUPLICATE of earlier entry]
- test_performRandomEdit_unseeded_works [git_test_funcs]
- test_sequence_01_plate_push_first_time_preserves_user_workspace [plate sequence]
- test_sequence_02_plate_push_second_time_extends_plate_stack [plate sequence]
- test_sequence_03_plate_done_replays_stack_and_cleans_workspace [plate sequence]
- test_sequence_04_plate_done_aborts_when_unpushed_work_exists [plate sequence]
- test_sequence_05_plate_drop_removes_top_plate_only [plate sequence]
- test_sequence_06_plate_drop_single_plate_deletes_stack [plate sequence]
- test_sequence_07_applyGitPatch_recovers_dropped_plate_work [plate sequence]
- test_sequence_08_plate_trash_deletes_stack_but_leaves_workspace_by_default [plate sequence]
- test_sequence_09_plate_trash_clean_mode_resets_workspace [plate sequence]
- test_sequence_10_plate_recycle_restores_latest_trashed_stack [plate sequence]
- test_sequence_12_derived_agent_first_child_records_parent_trailers [plate sequence]
- test_sequence_13_derived_agent_second_child_extends_linear_chain [plate sequence]
- test_sequence_21_plate_next_list_shows_plates_sorted_with_current_marker [plate sequence]
- test_sequence_15_plate_drop_with_no_plate_branch_warns_and_exits [plate sequence]
- test_sequence_16_plate_trash_with_no_plate_branch_warns_and_exits [plate sequence]
- test_sequence_17_plate_recycle_with_no_trashed_session_warns_and_exits [plate sequence]
- test_sequence_18_plate_done_resolves_content_conflict_in_plate_favor [plate sequence]
- test_sequence_19_drop_patch_is_portable_across_repos [plate sequence]
- test_sequence_20_plate_done_leaves_sha_recoverable_after_branch_delete [plate sequence]

(117 functions, 0 classes)

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

### tests/test_claude_lib.py — NEEDS_SPLIT: 3 files (buildcmd / permissions / misc)

- test_claude_buildCmd_returns_command_string_with_trailing_newline [buildcmd]
- test_claude_buildCmd_extra_dirs_appended_in_order [buildcmd]
- test_claude_buildCmd_writes_settings_file_with_allow_and_hooks [buildcmd]
- test_claude_buildCmd_no_extra_dirs_omits_additional_flags [buildcmd]
- test_claude_buildCmd_missing_hooks_file_raises [buildcmd]
- test_claude_permseedLog_no_op_when_log_file_is_none [permissions]
- test_claude_permseedLog_no_op_when_log_file_is_empty_string [permissions]
- test_claude_permseedLog_writes_line_to_log_file [permissions]
- test_claude_permseedLog_default_log_prefix_is_plugin [permissions]
- test_claude_permseedLog_custom_log_prefix_is_used [permissions]
- test_claude_permseedLog_line_starts_with_iso8601_timestamp [permissions]
- test_claude_permseedLog_appends_rather_than_overwrites [permissions]
- test_claude_permseedLog_swallows_write_errors_silently [permissions]
- permissions_workspace [permissions fixture]
- test_claude_seedPermissions_missing_default_file_logs_and_returns [permissions]
- test_claude_seedPermissions_missing_default_sha_file_logs_and_returns [permissions]
- test_claude_seedPermissions_seeds_installed_when_missing [permissions]
- test_claude_seedPermissions_no_op_when_installed_matches_default [permissions]
- test_claude_seedPermissions_upgrades_unmodified_installed_to_new_default [permissions]
- test_claude_seedPermissions_user_edited_installed_is_preserved_and_logged [permissions]
- test_claude_seedPermissions_user_edited_no_default_change_does_not_rewrite_prior [permissions]
- test_claude_seedPermissions_log_file_none_suppresses_logging [permissions]
- test_claude_seedPermissions_default_sha_file_with_two_column_format_is_parsed [permissions]
- test_claude_marker [misc]
- test_claude_returns_overload_markers [misc]
- test_claude_repo_root_equals_cwd_no_plans_dup [misc]
- test_claude_repo_root_distinct_from_cwd [misc]
- test_claude_plans_equals_cwd_skipped [misc]
- test_claude_repo_root_empty_string_skipped [misc]
- test_claude_has_empty_string_when_no_env [misc]

(30 functions, 0 classes)

### tests/test_debate_lib.py — NEEDS_SPLIT: 9 files (main / daemon / retry / agents / prompts / tmux / locks / capacity / archive_io)

- test_debate_agents_falls_back_to_env [agents]
- _make_subject_sor [main helper]
- class TestDebateStartOrResumeFreshStart [main]
  - TestDebateStartOrResumeFreshStart.test_all_r1_prompts_built_when_files_missing [main]
  - TestDebateStartOrResumeFreshStart.test_r2_prompts_built_when_files_missing [main]
  - TestDebateStartOrResumeFreshStart.test_synthesis_prompt_built_when_file_missing [main]
  - TestDebateStartOrResumeFreshStart.test_daemon_launched_with_start_new_session [main]
  - TestDebateStartOrResumeFreshStart.test_emit_block_says_spawned_on_fresh_start [main]
- class TestDebateStartOrResumeNoDrift [main]
  - TestDebateStartOrResumeNoDrift.test_composition_drifted_false_when_agents_match [main]
  - TestDebateStartOrResumeNoDrift.test_prompts_skipped_when_all_files_exist [main]
  - TestDebateStartOrResumeNoDrift.test_emit_block_says_resumed [main]
- class TestDebateStartOrResumeWithDrift [main]
  - TestDebateStartOrResumeWithDrift.test_composition_drifted_true_when_agents_differ [main]
- class TestDebateStartOrResumeClaimFailure [main]
  - TestDebateStartOrResumeClaimFailure.test_exits_zero_and_emits_error_on_claim_failure [main]
- class TestDebateStartOrResumePromptBuildSkipped [main]
  - TestDebateStartOrResumePromptBuildSkipped.test_only_missing_r1_is_built [main]
  - TestDebateStartOrResumePromptBuildSkipped.test_synthesis_not_built_when_file_exists [main]
- _ctx_dm [main helper]
- _detect_dm [main helper]
- test_debateMain_non_debate_input_returns_zero [main]
- test_debateMain_missing_topic_emits_usage [main]
- test_debateMain_missing_repo_emits_block [main]
- test_debateMain_existing_with_synthesis_emits_already_complete [main]
- test_debateMain_existing_with_live_lock_emits_already_running [main]
- test_debateMain_existing_without_synthesis_or_lock_resumes [main]
- test_debateMain_fresh_under_two_agents_emits_count_block [main]
- test_debateMain_fresh_happy_path_creates_artifacts_and_dispatches [main]
- test_debateMain_fresh_with_transcript_invokes_capture_subprocess [main]
- test_debateMain_fresh_capture_failure_writes_failure_marker [main]
- _install_stubs_dr [retry helper]
- test_debateRetry_missing_transcript_emits_message [retry]
- test_debateRetry_missing_repo_emits_message [retry]
- test_debateRetry_no_matching_debate_emits_message [retry]
- test_debateRetry_matched_with_synthesis_emits_already_complete [retry]
- test_debateRetry_matched_with_live_lock_emits_still_running [retry]
- test_debateRetry_happy_path_lex_max_wins_and_invokes_resume [retry]
- _patch_all_daemon [daemon helper]
- _base_kwargs_daemon [daemon helper]
- class TestDaemonMainHappyPath [daemon]
  - TestDaemonMainHappyPath.test_happy_path_two_agents_returns_zero [daemon]
  - TestDaemonMainHappyPath.test_happy_path_calls_init_agent_models [daemon]
- class TestDaemonMainDriftWipesFiles [daemon]
  - TestDaemonMainDriftWipesFiles.test_drift_true_unlinks_r2_and_synthesis_instructions [daemon]
  - TestDaemonMainDriftWipesFiles.test_drift_false_leaves_files_intact [daemon]
- class TestDaemonMainMissingR2Instructions [daemon]
  - TestDaemonMainMissingR2Instructions.test_missing_r2_instructions_triggers_build [daemon]
  - TestDaemonMainMissingR2Instructions.test_present_r2_instructions_skips_build [daemon]
- class TestDaemonMainSynthesisAlreadyComplete [daemon]
  - TestDaemonMainSynthesisAlreadyComplete.test_nonempty_synthesis_md_skips_launch_and_returns_zero [daemon]
  - TestDaemonMainSynthesisAlreadyComplete.test_empty_synthesis_md_does_not_short_circuit [daemon]
- class TestDaemonMainLaunchFailure [daemon]
  - TestDaemonMainLaunchFailure.test_r1_launch_failure_returns_one [daemon]
  - TestDaemonMainLaunchFailure.test_r1_wait_failure_returns_one [daemon]
  - TestDaemonMainLaunchFailure.test_r2_launch_failure_returns_one [daemon]
  - TestDaemonMainLaunchFailure.test_synth_launch_failure_returns_one [daemon]
  - TestDaemonMainLaunchFailure.test_synth_wait_failure_returns_one [daemon]
  - TestDaemonMainLaunchFailure.test_send_prompt_failure_returns_one [daemon]
- test_gemini_marker [capacity]
- test_codex_marker [capacity]
- test_unknown_agent_returns_empty_string [capacity — INTERNAL_DUPLICATE: appears 2x in this file (lines ~828 and ~904)]
- test_empty_string_agent_returns_empty_string [capacity]
- test_codex_returns_capacity_and_overload_markers [capacity]
- test_gemini_returns_quota_markers_in_order [capacity]
- test_unknown_agent_returns_empty_list [capacity]
- test_empty_string_agent_returns_empty_list [capacity]
- test_result_is_list_type [capacity]
- test_gemini_with_model [agents]
- test_gemini_without_model [agents]
- test_codex_with_model [agents]
- test_codex_without_model [agents]
- test_creates_archive_subdirectory [archive_io]
- test_moves_context_md_into_archive [archive_io]
- test_moves_synthesis_instructions_txt [archive_io]
- test_moves_r1_instructions_glob [archive_io]
- test_moves_r1_output_md_glob [archive_io]
- test_moves_r2_instructions_and_outputs_glob [archive_io]
- test_moves_orchestrator_log_when_present [archive_io]
- test_does_not_move_synthesis_md [archive_io]
- test_does_not_move_topic_md [archive_io]
- test_idempotent_when_no_intermediate_files [archive_io]
- test_handles_preexisting_archive_dir [archive_io]
- test_returns_empty_when_gemini_binary_missing [agents]
- test_returns_empty_when_binary_present_but_no_credentials [agents]
- test_returns_model_when_oauth_creds_file_present [agents]
- test_returns_model_when_gemini_api_key_env_set [agents]
- test_returns_model_when_google_api_key_env_set [agents]
- test_returns_present_sentinel_when_no_model_configured [agents]
- test_creates_tmpdir_and_settings_file_path [main — buildClaudeCmd]
- test_writes_settings_json_with_allow_and_empty_hooks [main — buildClaudeCmd]
- test_returns_claude_cmd_with_settings_and_add_dir [main — buildClaudeCmd]
- test_invokes_permissions_seed_with_expected_paths [main — buildClaudeCmd]
- test_creates_claude_plugin_data_dir_if_missing [main — buildClaudeCmd]
- test_r1_writes_instruction_file_for_each_agent [prompts]
- test_r1_agent_filter_writes_only_matching_agent [prompts]
- test_r1_reads_agents_from_agents_txt_when_agents_list_empty [prompts]
- test_r2_writes_cross_critique_instruction_file_for_each_agent [prompts]
- test_r2_agent_filter_writes_only_matching_agent [prompts]
- test_r2_others_list_excludes_self [prompts]
- test_synthesis_writes_single_instruction_file [prompts]
- test_synthesis_references_all_r1_and_r2_paths [prompts]
- test_synthesis_contains_required_structure_sections [prompts]
- test_unknown_stage_raises_value_error [prompts]
- _seed_original [retry helper]
- _seed_outputs [retry helper]
- test_all_originals_still_available_returns_feasible [retry]
- test_appeared_agent_is_kept_in_updated_list [retry]
- test_disappeared_agent_with_complete_outputs_is_readded [retry]
- test_disappeared_agent_missing_r2_is_unusable [retry]
- test_disappeared_agent_with_empty_output_file_is_unusable [retry]
- test_unusable_reason_contains_block_message_and_agent_name [retry]
- test_no_original_instructions_returns_feasible [retry]
- test_caller_available_agents_list_is_not_mutated [retry]
- test_returns_resumefeasibility_dataclass_instance [retry]
- test_claims_first_unused_when_all_free [tmux — slot claiming]
- test_skips_collisions_until_free_slot [tmux]
- test_passes_keepalive_cmd_and_geometry_to_tmux [tmux]
- test_raises_when_all_slots_exhausted [tmux]
- test_session_names_are_sequential_debate_n [tmux]
- _write_lock [locks helper]
- _noop [helper]
- _make_main_mock [helper]
- _patch_all [helper]
- _write_lock_at_path [locks helper]
- _write [helper — INTERNAL_DUPLICATE: also in test_util_lib.py]
- fake_tmux [tmux fixture]
- test_removes_lock_with_missing_pane_id [locks]
- test_removes_lock_when_pane_not_in_window [locks]
- test_removes_lock_when_pane_current_command_mismatches_agent [locks]
- test_preserves_lock_when_pane_alive_and_command_matches_agent [locks]
- test_only_touches_locks_for_requested_stage [locks]
- test_no_locks_present_is_a_noop [locks]
- _make_plugin_root [agents helper]
- test_returns_first_claude_model [agents]
- test_returns_first_gemini_model [agents]
- test_returns_first_codex_model [agents]
- test_unknown_agent_returns_empty_string [agents — INTERNAL_DUPLICATE: 2nd occurrence; pytest collects only the last one]
- test_agent_with_empty_list_returns_empty_string [agents]
- test_missing_plugin_root_env_raises [agents]
- test_only_claude_when_both_probes_unavailable [agents]
- test_gemini_with_real_model_appended_and_model_recorded [agents]
- test_gemini_present_sentinel_marks_available_but_leaves_model_blank [agents]
- test_codex_with_real_model_appended_and_model_recorded [agents]
- test_codex_present_sentinel_marks_available_but_leaves_model_blank [agents]
- test_both_probes_available_preserves_order_claude_gemini_codex [agents]
- _make_topic_debate [retry helper]
- test_returns_none_when_no_debates_dir [retry — find_debate]
- test_returns_none_when_no_topic_matches [retry]
- test_returns_dir_path_for_single_match [retry]
- test_skips_dirs_missing_topic_md [retry]
- test_most_recent_timestamp_wins_on_multiple_matches [retry]
- test_multiline_topic_byte_exact_match [retry]
- test_partial_substring_does_not_match [retry]
- test_returns_dict_with_current_model_and_tried_models_keys [agents]
- test_all_three_agents_present_in_both_subdicts [agents]
- test_gemini_picks_up_GEMINI_MODEL_env [agents]
- test_codex_picks_up_CODEX_MODEL_env [agents]
- test_unset_gemini_env_yields_empty_string_not_missing_key [agents]
- test_unset_codex_env_yields_empty_string [agents]
- test_independent_calls_return_independent_dicts [agents]
- test_env_defaults_to_os_environ_when_omitted [agents]
- test_returns_scripts_dir_under_plugin_root [archive_io — paths]
- test_log_file_defaults_under_plugin_data_and_dir_created [archive_io]
- test_log_file_honours_debate_log_file_override [archive_io]
- test_parses_cwd_and_transcript_path_from_stdin_json [archive_io]
- test_cwd_falls_back_to_pwd_when_json_omits_it [archive_io]
- test_repo_root_resolved_for_git_cwd [archive_io]
- test_repo_root_empty_when_cwd_not_in_git [archive_io]
- test_input_field_preserves_raw_stdin [archive_io]
- test_missing_plugin_root_raises [main]
- test_missing_plugin_data_raises [main]
- test_always_calls_debate_main [main]
- test_plugin_root_exported_to_environment [main]
- test_writes_lock_file_before_launch [locks]
- test_sends_launch_cmd_via_tmux [tmux]
- test_returns_true_when_ready_marker_found [tmux — readiness]
- test_returns_false_on_timeout [tmux]
- test_calls_write_failed_on_timeout [archive_io]
- test_sleeps_between_capture_polls [tmux]
- test_default_timeout_is_120 [tmux]
- test_no_write_failed_on_success [archive_io]
- test_returns_session_name_when_lock_resolves [locks]
- test_returns_empty_when_no_lock_files [locks]
- test_returns_empty_when_lock_has_no_pane_id [locks]
- test_returns_empty_when_tmux_fails [locks]
- test_returns_empty_when_tmux_returns_empty_session [locks]
- test_skips_missing_lock_file_gracefully [locks]
- test_returns_first_resolved_session_from_multiple_locks [locks]
- test_falls_through_to_second_lock_when_first_tmux_fails [locks]
- models_file [capacity fixture]
- test_returns_first_model_when_none_tried [capacity]
- test_skips_already_tried_models [capacity]
- test_returns_none_when_all_tried [capacity]
- test_unknown_agent_returns_none [capacity]
- test_partial_tried_with_leading_comma [capacity]
- test_missing_models_file_returns_none [capacity]
- test_codex_capacity_marker_present_returns_truthy [capacity]
- test_codex_overloaded_marker_present_returns_truthy [capacity]
- test_codex_no_marker_returns_falsy [capacity]
- test_gemini_resource_exhausted_returns_truthy [capacity]
- test_gemini_marker_for_other_agent_does_not_match [capacity]
- test_claude_api_529_returns_truthy [capacity]
- test_unknown_agent_returns_falsy_without_capturing [capacity]
- test_ansi_escape_bytes_are_stripped_before_match [capacity]
- test_empty_capture_returns_falsy [capacity]
- test_returns_empty_when_codex_binary_missing [agents]
- test_returns_empty_when_no_credentials_present [agents]
- test_returns_present_when_available_but_no_model_configured [agents]
- test_returns_model_name_when_configured [agents]
- test_openai_api_key_alone_satisfies_credentials_gate [agents]
- test_no_next_model_returns_none [capacity — model rotation]
- test_updates_model_dicts_on_success [capacity]
- test_kills_old_pane_returns_new_pane_id [capacity — pane rotation on capacity]
- test_launch_agent_failure_returns_none [capacity]
- test_send_prompt_failure_returns_none [capacity]
- test_tried_models_created_when_agent_missing [capacity]
- test_raises_when_session_empty [main — context build]
- test_raises_when_debate_agents_empty_and_no_env [main]
- test_window_target_composed_from_session_and_window_name [main]
- test_stage_timeout_is_900_seconds [main]
- test_agents_parsed_from_space_separated_string [main]
- test_daemon_main_called_once_with_context [main]
- test_cleanup_called_even_when_daemon_raises [main]
- test_returns_zero_on_success [main]
- test_context_stores_all_positional_args [main]
- test_partial_completion_returns_only_completed_agents [archive_io]
- test_empty_output_file_does_not_count_as_complete [archive_io]
- test_emits_when_transcript_path_missing [retry]
- test_emits_when_repo_root_missing [retry]
- test_emits_when_no_matching_debate_found [retry]
- test_emits_still_running_when_live_lock_present [retry]
- test_emits_still_running_with_unknown_when_session_lookup_empty [retry]
- test_happy_path_deletes_dir_and_emits_success [retry — debate-abort path]
- test_lexicographic_tiebreak_picks_newest_basename [retry]
- _install_ctx [retry helper]
- _capture_emit [retry helper]
- _make_debate [retry helper]
- test_newEmptyPane_returnsPaneId_onSuccess [tmux]
- test_newEmptyPane_returnsNone_onTmuxFailure [tmux]
- test_newEmptyPane_returnsNone_onEmptyPaneId [tmux]
- test_newEmptyPane_callsRetile_beforeSplit [tmux]
- test_newEmptyPane_passesCorrectCwdToSplit [tmux]
- test_newEmptyPane_retileRcIgnored_doesNotPreventSplit [tmux]
- test_newEmptyPane_addsPaneToWindow [tmux]
- test_newEmptyPane_returnedIdInPaneList [tmux]
- test_newEmptyPane_returnsNone_onBogusTarget [tmux]
- tmux_session_newpane [tmux fixture]
- test_happy_path_two_agents_returns_zero [daemon — launchAll]
- test_skip_when_output_file_exists [daemon]
- test_skip_when_lock_file_exists [daemon]
- test_partial_failure_returns_one [daemon]
- test_empty_agents_list_returns_zero [daemon]
- test_launch_failure_returns_one [daemon]
- test_empty_output_file_does_not_skip [daemon]
- _patch_deps [daemon helper]
- test_returns_zero_when_marker_seen_immediately [tmux — waitForMarker]
- test_timeout_returns_one_and_invokes_writeFailed [tmux]
- test_ansi_escapes_are_stripped_before_match [tmux]
- test_marker_is_basename_not_full_path [tmux]
- test_returns_false_when_no_lock_files [locks — INTERNAL_DUPLICATE: 2nd occurrence; pytest collects only the last]
- test_returns_true_when_lock_pane_id_is_live [locks]
- test_returns_false_when_lock_pane_id_is_dead [locks]
- test_skips_lock_without_debate_marker [locks]
- test_returns_false_when_directory_missing [locks]
- test_returns_true_if_any_one_of_many_locks_is_live [locks]
- test_ignores_non_hidden_lock_files [locks]
- test_removes_tmp_debate_dir [archive_io — cleanup]
- test_ignores_non_tmp_debate_dir [archive_io]
- test_ignores_tmp_non_debate_prefix [archive_io]
- test_noop_when_dir_already_gone [archive_io]
- test_accepts_str_path [archive_io]
- test_writes_failed_txt_at_debate_dir_root [archive_io]
- test_header_contains_stage_reason_and_iso_timestamp [archive_io]
- test_skips_agents_with_nonempty_output_files [archive_io]
- test_empty_output_file_counts_as_missing [archive_io]
- test_missing_lock_file_emits_placeholder_line [archive_io]
- test_lock_with_pane_id_invokes_capture_and_fences_output [archive_io]
- test_overwrites_existing_failed_txt [archive_io]
- test_no_temp_files_left_behind_on_success [archive_io]
- test_missing_agents_section_header_present [archive_io]
- test_pane_capture_callback_failure_yields_unavailable_marker [archive_io]
- test_invokes_retry_when_pane_has_capacity_error_and_no_output [capacity]
- test_removes_lock_file_when_output_appears [locks]
- test_returns_true_when_all_outputs_already_present [archive_io]
- test_returns_false_with_timeout_reason_when_outputs_never_appear [archive_io]

(276 functions, 10 classes)

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

### tests/test_git_lib.py — mirror git_lib.py source buckets (Reader/Checker/Creator/Modifier/Destroyer)

- test_run [Checker — smoke test for subprocess wrapper]
- test_writeGitIgnore [Modifier]
- test_setGitUserConfigValue [Modifier]
- test_createGitUserConfig [Creator]
- test_createGitBranch [Creator]
- test_checkOutGitBranch [Modifier]
- test_createAndCheckoutGitBranch [Creator]
- test_getCurrentGitBranchName [Reader]
- test_gitStashFiles [Modifier]
- test_gitUnstashFiles [Modifier]
- test_addFileToGit [Modifier]
- test_stageFiles [Modifier]
- test_createGitCommit [Creator]
- test_checkIfGitBranchExists [Checker]
- test_countGitCommitsReachableFromRef [Reader]
- test_getSHAForGitRefViaRevParse [Reader]
- test_readWriteGitTree [Reader+Creator — exercises both]
- test_getGitTreeRevOf [Reader]
- test_getGitStatus [Reader]
- test_checkGitForCleanWorkTree [Checker]
- test_getGitCommitSubject [Reader]
- test_getGitCommitTrailers [Reader]
- test_gitResetHardToHead [Destroyer]
- test_gitCleanWorkTree [Destroyer]
- test_deleteGitBranchByForce [Destroyer]
- test_saveChangesToGitPatch [Creator]
- test_applyGitPatch [Modifier]
- test_getGitRepoRoot_returns_absolute_repo_root [Reader]
- test_getGitRepoRoot_works_from_subdirectory [Reader]
- test_getGitRepoRoot_raises_outside_repo [Reader]
- test_getGitBranchNameOrFail_returns_current_branch [Reader]
- test_getGitBranchNameOrFail_raises_outside_repo [Reader]
- test_getGitBranchNameOrFail_raises_on_detached_head [Reader]
- test_getGitRecentCommitHashes_returns_one_hash_for_single_commit [Reader]
- test_getGitRecentCommitHashes_caps_at_n [Reader]
- test_getGitRecentCommitHashes_raises_outside_repo [Reader]
- test_getGitRecentCommitHashes_raises_on_empty_repo [Reader]
- test_getGitUncommittedFilenames_clean_repo_returns_empty [Reader]
- test_getGitUncommittedFilenames_lists_modified [Reader]
- test_getGitUncommittedFilenames_lists_untracked [Reader]
- test_getGitUncommittedFilenames_raises_outside_repo [Reader]
- test_ensureGitignoreEntry_creates_file [Modifier]
- test_ensureGitignoreEntry_appends_to_existing [Modifier]
- test_ensureGitignoreEntry_is_idempotent [Modifier]

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

### tests/test_jot_lib.py — NEEDS_SPLIT: 7 files (state / audit / buildcmd / phase2 / stop / diag / dispatch). Receives 8 misplaced jot tests from tests/test_todo_lib.py.

- test_jot_initState_creates_state_directory_when_missing [state]
- test_jot_initState_creates_three_tracked_files [state]
- test_jot_initState_preserves_existing_queue_contents [state]
- test_jot_initState_preserves_existing_audit_log [state]
- test_jot_initState_idempotent_on_second_call [state]
- test_jot_initState_creates_parent_directories [state]
- test_jot_initState_accepts_string_path [state]
- test_jot_initState_touch_refreshes_mtime_on_existing_file [state]
- _seed_jot_state [state helper]
- test_jot_popFirstFromQueue_returns_first_line [state]
- test_jot_popFirstFromQueue_removes_first_line_from_queue_file [state]
- test_jot_popFirstFromQueue_writes_popped_line_to_active_job_file [state]
- test_jot_popFirstFromQueue_returns_none_on_empty_queue [state]
- test_jot_popFirstFromQueue_empty_queue_does_not_modify_active_job [state]
- test_jot_popFirstFromQueue_single_entry_queue_becomes_empty [state]
- test_jot_sendPrompt_delegates_to_tmux_sendAndSubmit_with_target_and_prompt [phase2]
- test_jot_sendPrompt_returns_nonzero_when_tmux_helper_fails [phase2]
- test_jot_sendPrompt_input_path_interpolated_verbatim [phase2]
- test_jot_rotateAudit_silent_noop_when_file_missing [audit]
- test_jot_rotateAudit_leaves_short_file_untouched [audit]
- test_jot_rotateAudit_truncates_to_last_max_lines_when_oversized [audit]
- test_jot_rotateAudit_respects_custom_max_lines [audit]
- test_jot_rotateAudit_no_trim_sidecar_left_behind [audit]
- plugin_layout [buildcmd fixture]
- _invoke_jot_build [buildcmd helper]
- test_jot_buildClaudeCmd_returns_tmpdir_inv_from_factory [buildcmd]
- test_jot_buildClaudeCmd_settings_file_lives_under_tmpdir [buildcmd]
- test_jot_buildClaudeCmd_permissions_file_under_plugin_data [buildcmd]
- test_jot_buildClaudeCmd_orchestrator_script_copied_into_tmpdir [buildcmd]
- test_jot_buildClaudeCmd_plugin_data_dir_is_created [buildcmd]
- test_jot_buildClaudeCmd_permissions_seed_invoked_with_expected_args [buildcmd]
- test_jot_buildClaudeCmd_expand_permissions_receives_cwd_home_repo_root [buildcmd]
- test_jot_buildClaudeCmd_hooks_json_file_is_written_and_valid_json [buildcmd]
- test_jot_buildClaudeCmd_hooks_json_session_start_command_includes_input_file_and_tmpdir [buildcmd]
- test_jot_buildClaudeCmd_hooks_json_stop_command_includes_state_dir [buildcmd]
- test_jot_buildClaudeCmd_claude_cmd_contains_settings_and_cwd [buildcmd]
- test_jot_buildClaudeCmd_settings_file_written_with_expanded_allow_json [buildcmd]
- phase2_env [phase2 fixture]
- _phase2_patches [phase2 helper]
- _enter_phase2_patches [phase2 helper]
- _exit_phase2_patches [phase2 helper]
- test_jot_launchPhase2Window_initializes_state_dir_under_repo_root_todos [phase2]
- test_jot_launchPhase2Window_acquires_global_tmux_lock_with_10s_timeout [phase2]
- test_jot_launchPhase2Window_returns_1_if_lock_acquire_times_out [phase2]
- test_jot_launchPhase2Window_pane_counter_increments_modulo_20 [phase2]
- test_jot_launchPhase2Window_pane_counter_wraps_from_20_to_1 [phase2]
- test_jot_launchPhase2Window_split_failure_releases_lock_and_returns_1 [phase2]
- test_jot_launchPhase2Window_writes_pane_id_atomically_via_tmp_then_rename [phase2]
- test_jot_launchPhase2Window_calls_tmux_helpers_in_required_order [phase2]
- test_jot_launchPhase2Window_ensure_session_called_with_jot_jots_session_window [phase2]
- test_jot_launchPhase2Window_split_worker_called_with_built_claude_cmd [phase2]
- test_jot_launchPhase2Window_spawn_terminal_called_after_lock_released [phase2]
- test_jot_diagSection_starts_with_leading_newline [diag]
- test_jot_diagSection_embeds_title_between_rules [diag]
- test_jot_diagSection_rule_is_59_box_chars [diag]
- test_jot_diagSection_ends_with_trailing_newline [diag]
- test_jot_diagSection_preserves_empty_title [diag]
- test_jot_diagIndent_single_line_no_trailing_newline [diag]
- test_jot_diagIndent_multiline_preserves_trailing_newline [diag]
- test_jot_diagIndent_multiline_no_trailing_newline [diag]
- test_jot_diagIndent_blank_line_still_prefixed [diag]
- test_jot_diagIndent_empty_string_returns_empty [diag]
- test_jot_diagIndent_only_newline [diag]
- test_jot_diagKv_short_key_left_padded_to_28 [diag]
- test_jot_diagKv_value_starts_at_column_29 [diag]
- test_jot_diagKv_long_key_not_truncated [diag]
- test_jot_diagKv_ends_with_single_trailing_newline [diag]
- test_jot_diagKv_empty_value_still_emits_padded_key [diag]
- test_jot_diagKv_value_with_spaces_preserved_verbatim [diag]
- test_jot_stop_missingArgsReturnsZeroAndLogsToStderr [stop]
- test_jot_stop_emptySidecarRetriesThenReturnsZero [stop]
- test_jot_stop_writesSuccessAuditLineWhenInputHasProcessedMarker [stop]
- test_jot_stop_writesFailAuditLineWhenInputHasNoProcessedMarker [stop]
- test_jot_stop_writesFailAuditLineWhenInputFileMissing [stop]
- test_jot_stop_killsPaneAndRetilesAfterAuditWrite [stop]
- test_jot_stop_initializesStateDirArtifacts [stop]
- test_jot_stop_rotatesAuditLogToOneThousandLines [stop]
- _stub_prompt_disp [dispatch helper]
- test_dispatchMain_leading_whitespace_in_prompt_tolerated [dispatch]
- test_dispatchMain_jot_namespace_normalises_to_bare_skill [dispatch]
- test_dispatchMain_default_prompt_exits_zero [dispatch]
- test_dispatchMain_unknown_argv_falls_through_to_stdin_mode [dispatch]
- _writeSidecar [stop helper]
- kill_calls [stop fixture]
- jot_dirs [stop fixture]
- test_removes_tmp_jot_directory_recursively [stop — cleanup safety]
- test_refuses_path_outside_safelist [stop — cleanup safety]
- test_refuses_empty_argument [stop — cleanup safety]
- test_accepts_private_tmp_jot_prefix [stop — cleanup safety]
- test_missing_directory_is_silent_success [stop — cleanup safety]
- test_refuses_lookalike_prefix [stop — cleanup safety]
- test_missing_input_file_returns_0_and_warns [phase2 — send/readiness]
- test_missing_tmpdir_inv_returns_0_and_warns [phase2 — send/readiness]
- test_sidecar_empty_after_retries_returns_0 [phase2 — send/readiness]
- test_sidecar_zero_byte_file_treated_as_empty [phase2 — send/readiness]
- test_readiness_timeout_returns_1 [phase2 — send/readiness]
- test_happy_path_sends_read_prompt_to_resolved_pane [phase2 — send/readiness]
- test_sidecar_first_line_only_used [phase2 — send/readiness]
- test_readiness_called_with_resolved_pane_id [phase2 — send/readiness]
- _read [phase2 helper]
- class TestReportHeader [diag — jot-diag report]
  - TestReportHeader.test_report_file_created_at_default_path [diag]
  - TestReportHeader.test_report_contains_header_line [diag]
  - TestReportHeader.test_report_contains_generated_timestamp [diag]
  - TestReportHeader.test_report_contains_cwd_line [diag]
  - TestReportHeader.test_report_contains_project_line [diag]
- class TestSectionBanners [diag]
  - TestSectionBanners.test_section_1_banner_present [diag]
  - TestSectionBanners.test_section_2_banner_present [diag]
  - TestSectionBanners.test_section_3_banner_present [diag]
  - TestSectionBanners.test_section_4_banner_present [diag]
  - TestSectionBanners.test_section_5_banner_present [diag]
  - TestSectionBanners.test_section_6_banner_present [diag]
  - TestSectionBanners.test_section_7_banner_present [diag]
  - TestSectionBanners.test_section_8_banner_present [diag]
  - TestSectionBanners.test_end_of_report_banner_present [diag]
  - TestSectionBanners.test_section_banners_use_box_drawing_rule [diag]
- class TestTodosInputSection [diag]
  - TestTodosInputSection.test_no_input_txt_shows_not_found_message [diag]
  - TestTodosInputSection.test_input_txt_present_shows_kv_path [diag]
  - TestTodosInputSection.test_input_txt_pending_status [diag]
  - TestTodosInputSection.test_input_txt_processed_status [diag]
- class TestStateDirSection [diag]
  - TestStateDirSection.test_missing_state_dir_shows_message [diag]
  - TestStateDirSection.test_queue_txt_empty_shows_empty_message [diag]
  - TestStateDirSection.test_queue_txt_missing_shows_missing [diag]
  - TestStateDirSection.test_queue_lock_held_shows_lock_message [diag]
  - TestStateDirSection.test_queue_lock_free_shows_free_message [diag]
- class TestDependencySection [diag]
  - TestDependencySection.test_dependency_section_lists_known_cmds [diag]
  - TestDependencySection.test_dependency_found_cmd_shows_path [diag]
- class TestReturnValue [diag]
  - TestReturnValue.test_returns_out_path_string [diag]
  - TestReturnValue.test_default_out_path_is_in_tmp [diag]

(128 functions, 6 classes)

### tests/test_plate_lib.py — NEEDS_SPLIT: 3 files (main / summary_watch / set_summary_cli)

- class FakeClock [shared fixture — pull into tests/fixtures/]
  - FakeClock.__init__
  - FakeClock.__call__
- class FakeTmux [shared fixture — pull into tests/fixtures/]
  - FakeTmux.__init__
  - FakeTmux.__call__
- _stub_argv [main helper]
- _stub_prompt_disp [main helper]
- _base_env_pm [main helper]
- _make_payload_pm [main helper]
- _make_deps_pm [main helper]
- _expected_repo_root_pm [main helper]
- test_plateMain_missing_plugin_root_raises [main]
- test_plateMain_missing_plugin_data_raises [main]
- test_plateMain_non_plate_input_exits_0_silently [main]
- test_plateMain_bad_json_after_fast_path_exits_0 [main]
- test_plateMain_typo_prompt_exits_0_silently [main]
- test_plateMain_prompt_with_leading_whitespace_is_accepted [main]
- test_plateMain_missing_repo_root_emits_friendly_message [main]
- _get_cli_args_pm [main helper]
- test_plateMain_dispatch_bare_plate_is_push [main]
- test_plateMain_dispatch_done [main]
- test_plateMain_dispatch_drop [main]
- test_plateMain_dispatch_trash [main]
- test_plateMain_dispatch_recycle [main]
- test_plateMain_dispatch_recycle_list [main]
- test_plateMain_dispatch_recycle_named [main]
- test_plateMain_dispatch_show [main]
- test_plateMain_dispatch_next [main]
- test_plateMain_dispatch_next_named [main]
- test_plateMain_unrecognized_variant_emits_message [main]
- test_plateMain_cli_output_forwarded_via_emit_block [main]
- test_plateMain_cli_stderr_included_in_emit_block [main]
- test_plateMain_log_file_promoted_to_per_repo_path_when_no_override [main]
- test_plateMain_log_file_override_respected [main]
- test_dispatchMain_newline_after_slashcommand_tolerated [main]
- test_returns_zero_when_output_file_already_non_empty [summary_watch]
- test_sends_exit_then_enter_when_file_becomes_non_empty [summary_watch]
- test_returns_one_on_timeout_without_sending [summary_watch]
- test_empty_file_is_treated_as_not_ready [summary_watch]
- test_swallows_tmux_send_errors_and_still_returns_zero [summary_watch]
- test_env_overrides_supply_default_timeout_and_interval [summary_watch]
- test_missing_repo_arg_is_noop [set_summary_cli]
- test_missing_branch_arg_is_noop [set_summary_cli]
- test_missing_output_file_arg_is_noop [set_summary_cli]
- test_nonexistent_output_file_is_noop [set_summary_cli]
- test_invokes_cli_set_plate_summary_with_args [set_summary_cli]
- test_writes_audit_log_line [set_summary_cli]
- test_cli_failure_is_swallowed [set_summary_cli]

(47 functions, 2 classes)

### tests/test_tmux_lib.py — mirror tmux_lib.py source buckets (Create/Destroy/Read/Communicate/Monitor/Configure). [live] suffix marks integration tests against real tmux.

- _stdin [helper]
- class _FakeProc [helper]
  - _FakeProc.__init__
- test_tmux_requireVersion_returns_1_and_logs_when_tmux_binary_is_missing [Read]
- test_tmux_requireVersion_returns_0_when_installed_version_exactly_matches_required [Read]
- test_tmux_requireVersion_returns_0_when_installed_version_exceeds_required [Read]
- test_tmux_requireVersion_returns_1_and_logs_when_installed_version_is_below_required [Read]
- test_tmux_requireVersion_returns_1_when_tmux_version_output_is_unparseable [Read]
- class _FakeCompleted [helper]
  - _FakeCompleted.__init__
- test_tmux_setOption_invokes_tmux_set_option_with_passed_args_and_returns_zero_on_success [Configure]
- test_tmux_setOption_emits_no_output_when_tmux_succeeds_with_empty_stdout [Configure]
- test_tmux_setOption_logs_caller_name_and_combined_output_to_stderr_when_tmux_fails [Configure]
- test_tmux_setOption_passes_variadic_args_through_to_tmux_in_order [Configure]
- test_tmux_setOptionForTarget_passes_target_flag_then_target_then_name_then_value_to_tmux_setOption [Configure]
- test_tmux_setOptionForTarget_returns_the_exit_code_from_tmux_setOption [Configure]
- test_tmux_setOptionGlobally_passes_dash_g_flag_then_name_then_value_to_tmux_setOption [Configure]
- test_tmux_setOptionGlobally_returns_the_exit_code_from_tmux_setOption [Configure]
- test_tmux_setOptionForWindow_passes_dash_w_then_dash_t_then_target_then_name_then_value_to_tmux_setOption [Configure]
- test_tmux_setOptionForWindow_returns_the_exit_code_from_tmux_setOption [Configure]
- _make_fake_run [helper]
- test_tmux_hasSession_returns_zero_when_session_exists [Read]
- test_tmux_hasSession_returns_one_when_session_does_not_exist [Read]
- test_tmux_hasSession_invokes_tmux_has_session_with_dash_t_target [Read]
- test_tmux_hasSession_does_not_log_to_stderr_when_session_is_simply_absent [Read]
- test_tmux_hasSession_logs_caller_name_to_stderr_on_unexpected_nonzero_rc [Read]
- test_tmux_newSession_invokes_tmux_new_session_with_dash_d_dash_s_and_session_name [Create]
- test_tmux_newSession_returns_zero_on_success [Create]
- test_tmux_newSession_returns_nonzero_and_logs_caller_when_creation_fails [Create]
- test_tmux_newSession_passes_extra_args_through_to_tmux_after_session_name [Create]
- test_tmux_killSession_invokes_tmux_kill_session_with_dash_t_target [Destroy]
- test_tmux_killSession_returns_zero_on_success [Destroy]
- test_tmux_killSession_returns_nonzero_and_logs_caller_when_kill_fails [Destroy]
- test_tmux_listClients_invokes_tmux_list_clients_with_dash_t_session_name [Read]
- test_tmux_listClients_returns_empty_list_when_no_clients_attached [Read]
- test_tmux_listClients_returns_one_string_per_client_line_on_stdout [Read]
- test_tmux_listClients_returns_empty_list_and_logs_caller_when_session_not_found [Read]
- test_tmux_newPane_invokes_tmux_split_window_with_dash_t_target [Create]
- test_tmux_newPane_returns_zero_on_success [Create]
- test_tmux_newPane_returns_nonzero_and_logs_caller_when_split_fails [Create]
- test_tmux_newPane_passes_extra_args_through_after_target [Create]
- test_tmux_newPane_prints_stdout_to_caller_on_success [Create]
- test_tmux_killPane_invokes_tmux_kill_pane_with_dash_t_target [Destroy]
- test_tmux_killPane_returns_zero_on_success [Destroy]
- test_tmux_killPane_returns_nonzero_and_logs_caller_when_kill_fails [Destroy]
- test_tmux_capturePane_invokes_tmux_capture_pane_with_dash_p_dash_t_target_when_no_scrollback_requested [Read]
- test_tmux_capturePane_returns_pane_stdout_text_on_success [Read]
- test_tmux_capturePane_includes_dash_S_negative_offset_when_scrollback_lines_given [Read]
- test_tmux_capturePane_returns_empty_string_and_logs_caller_when_target_missing [Read]
- test_tmux_listPanes_uses_default_pane_id_and_title_format_when_no_extras_given [Read]
- test_tmux_listPanes_passes_extra_args_through_when_extras_given_and_omits_default_format [Read]
- test_tmux_listPanes_returns_one_string_per_pane_line [Read]
- test_tmux_listPanes_returns_empty_list_when_no_panes_in_stdout [Read]
- test_tmux_listPanes_returns_empty_list_and_logs_caller_when_target_missing [Read]
- test_tmux_selectPane_invokes_tmux_select_pane_with_dash_t_target [Configure]
- test_tmux_selectPane_returns_zero_on_success [Configure]
- test_tmux_selectPane_returns_nonzero_and_logs_caller_when_select_fails [Configure]
- test_tmux_setPaneTitle_invokes_tmux_select_pane_with_dash_t_target_and_dash_T_title [Configure]
- test_tmux_setPaneTitle_returns_zero_on_success [Configure]
- test_tmux_setPaneTitle_returns_nonzero_and_logs_caller_when_target_missing [Configure]
- test_tmux_newWindow_invokes_tmux_new_window_with_dash_t_session_and_dash_n_window [Create]
- test_tmux_newWindow_returns_zero_on_success [Create]
- test_tmux_newWindow_returns_nonzero_and_logs_caller_when_creation_fails [Create]
- test_tmux_newWindow_passes_extra_args_through_after_window_name [Create]
- test_tmux_killWindow_invokes_tmux_kill_window_with_dash_t_target [Destroy]
- test_tmux_killWindow_returns_zero_on_success [Destroy]
- test_tmux_killWindow_returns_nonzero_and_logs_caller_when_window_missing [Destroy]
- test_tmux_listWindows_uses_default_window_index_and_name_format_when_no_extras_given [Read]
- test_tmux_listWindows_passes_extra_args_through_when_extras_given_and_omits_default_format [Read]
- test_tmux_listWindows_returns_one_string_per_window_line [Read]
- test_tmux_listWindows_returns_empty_list_when_no_windows_in_stdout [Read]
- test_tmux_listWindows_returns_empty_list_and_logs_caller_when_session_missing [Read]
- test_tmux_windowExists_returns_zero_when_window_name_appears_in_listed_windows [Read]
- test_tmux_windowExists_returns_one_when_window_name_not_in_listed_windows [Read]
- test_tmux_windowExists_uses_exact_match_not_substring [Read]
- test_tmux_windowExists_invokes_tmux_listWindows_with_F_window_name_format [Read]
- test_tmux_paneHasTitle_returns_zero_when_title_appears_in_listed_panes [Read]
- test_tmux_paneHasTitle_returns_one_when_title_not_in_listed_panes [Read]
- test_tmux_paneHasTitle_uses_exact_match_not_substring [Read]
- test_tmux_paneHasTitle_invokes_tmux_listPanes_with_F_pane_title_format [Read]
- test_tmux_splitWindow_invokes_tmux_split_window_with_dash_h_for_horizontal [Create]
- test_tmux_splitWindow_invokes_tmux_split_window_with_dash_v_for_vertical [Create]
- test_tmux_splitWindow_returns_zero_on_success [Create]
- test_tmux_splitWindow_returns_nonzero_and_logs_caller_when_split_fails [Create]
- test_tmux_splitWindow_raises_ValueError_for_invalid_direction [Create]
- test_tmux_selectLayout_invokes_tmux_select_layout_with_dash_t_target_then_layout_name [Configure]
- test_tmux_selectLayout_returns_zero_on_success [Configure]
- test_tmux_selectLayout_returns_nonzero_and_logs_caller_when_layout_invalid [Configure]
- test_tmux_retile_invokes_tmux_selectLayout_with_tiled_for_the_given_target [Configure]
- test_tmux_retile_returns_the_exit_code_from_tmux_selectLayout [Configure]
- test_tmux_sendKeys_invokes_tmux_send_keys_with_dash_t_target_then_text [Communicate]
- test_tmux_sendKeys_returns_zero_on_success [Communicate]
- test_tmux_sendKeys_returns_nonzero_and_logs_caller_when_target_missing [Communicate]
- test_tmux_sendKeys_passes_text_with_special_chars_unchanged [Communicate]
- test_tmux_sendEnter_invokes_tmux_send_keys_with_dash_t_target_and_literal_Enter_token [Communicate]
- test_tmux_sendEnter_returns_zero_on_success [Communicate]
- test_tmux_sendEnter_returns_nonzero_and_logs_caller_when_target_missing [Communicate]
- test_tmux_sendCtrlC_invokes_tmux_send_keys_with_dash_t_target_and_literal_C_dash_c_token [Communicate]
- test_tmux_sendCtrlC_returns_zero_on_success [Communicate]
- test_tmux_sendCtrlC_returns_nonzero_and_logs_caller_when_target_missing [Communicate]
- test_tmux_sendAndSubmit_calls_sendKeys_then_sendEnter_with_same_target [Communicate]
- test_tmux_sendAndSubmit_returns_zero_when_both_sends_succeed [Communicate]
- test_tmux_sendAndSubmit_short_circuits_when_sendKeys_fails [Communicate]
- test_tmux_sendAndSubmit_returns_sendEnter_rc_when_only_sendEnter_fails [Communicate]
- test_tmux_sendAndSubmit_sleeps_between_sendKeys_and_sendEnter [Communicate]
- test_tmux_cancelAndSend_stops_retrying_once_marker_seen [Communicate]
- test_tmux_cancelAndSend_caps_at_five_attempts_and_still_submits [Communicate]
- test_tmux_cancelAndSend_returns_rc_from_final_send [Communicate]
- test_tmux_cancelAndSend_logs_label_when_retry_needed [Communicate]
- test_tmux_cancelAndSend_omits_log_when_first_attempt_succeeds [Communicate]
- class _FakeCompleted [helper — INTERNAL_DUPLICATE: _FakeCompleted defined twice in this file]
  - _FakeCompleted.__init__
- test_tmux_splitWorkerPane_returns_pane_id_on_success [Create]
- test_tmux_splitWorkerPane_returns_None_when_tmux_fails [Create]
- test_tmux_splitWorkerPane_returns_None_when_pane_id_blank [Create]
- test_tmux_splitWorkerPane_logs_caller_attributed_stderr_on_failure [Create]
- test_tmux_waitForClaudeReadiness_returns_zero_when_glyph_present_immediately [Monitor]
- test_tmux_waitForClaudeReadiness_returns_one_on_timeout_and_logs_stderr [Monitor]
- test_tmux_waitForClaudeReadiness_polls_until_ready [Monitor]
- test_tmux_waitForClaudeReadiness_swallows_capture_errors [Monitor]
- test_tmux_waitForClaudeReadiness_default_timeout_is_ten_seconds [Monitor]
- test_tmux_waitForClaudeReadiness_passes_pane_id_and_five_line_window [Monitor]
- test_tmux_ensureKeepalivePane_returns_early_when_pane_with_title_exists [Create]
- test_tmux_ensureKeepalivePane_creates_pane_sets_title_and_retiles_when_absent [Create]
- test_tmux_ensureKeepalivePane_skips_set_title_when_split_returns_none [Create]
- test_tmux_ensureSession_creates_session_when_absent [Create]
- test_tmux_ensureSession_creates_window_when_session_exists_but_window_absent [Create]
- test_tmux_ensureSession_delegates_to_keepalive_pane_when_both_exist [Create]
- test_tmux_too_old_emits_block [Read]
- test_setOptionForWindow_rejects_nonexistent_window [Configure live]
- test_setOptionForWindow_accepts_valid_window_option [Configure live]
- test_setOptionGlobally_rejects_invalid_option [Configure live]
- test_setOptionGlobally_accepts_valid_global_option [Configure live]
- test_setOptionForTarget_rejects_nonexistent_target [Configure live]
- test_setOptionForTarget_rejects_invalid_option [Configure live]
- test_setOptionForTarget_accepts_valid_session_option [Configure live]
- tmux_session_opts [live fixture]
- test_killSession_fails_onNonexistentSession [Destroy live]
- test_hasSession_returnsFalse_afterKill [Read live]
- session_name [live fixture]
- test_hasSession_returnsFalse_forNonexistentSession [Read live]
- test_newSession_createsSession [Create live]
- test_hasSession_returnsTrue_forExistingSession [Read live]
- test_newSession_rejectsDuplicate [Create live]
- test_killSession_succeeds_onExistingSession [Destroy live]
- live_tmux_session [live fixture]
- test_sendKeys_returnsZero_onLiveSession [Communicate live]
- test_sendKeys_textVisible_inPaneCapture [Communicate live]
- test_sendCtrlC_returnsZero_onLiveSession [Communicate live]
- test_sendEnter_returnsZero_onLiveSession [Communicate live]
- test_sendAndSubmit_returnsZero_onLiveSession [Communicate live]
- test_sendAndSubmit_outputVisible_inPaneCapture [Communicate live]
- test_sendKeys_returnsNonzero_onNonexistentTarget [Communicate live]
- test_sendEnter_returnsNonzero_onNonexistentTarget [Communicate live]
- tmux_session_panes [live fixture]
- _first_pane_id [live helper]
- test_listPanes_newSession_hasOnePane [Read live]
- test_newPane_addsPaneToSession [Create live]
- test_listPanes_afterNewPane_hasTwoPanes [Read live]
- test_selectPane_byKnownPaneId_succeeds [Configure live]
- test_setPaneTitle_succeeds [Configure live]
- test_setPaneTitle_roundTripsThroughListPanes [Configure live]
- test_capturePane_returnsContent [Read live]
- test_newPane_failsOnNonexistentSession [Create live]
- test_selectPane_failsOnNonexistentTarget [Configure live]
- test_killPane_removesLivePane [Destroy live]
- test_listPanes_afterKillPane_hasOnePane [Read live]
- test_killPane_failsOnNonexistentTarget [Destroy live]
- layout_session [live fixture]
- test_selectLayout_tiled_succeeds [Configure live]
- test_selectLayout_evenHorizontal_succeeds [Configure live]
- test_selectLayout_invalidName_fails [Configure live]
- test_retile_succeeds [Configure live]
- test_retile_nonexistentTarget_fails [Configure live]
- _tmux_has_session [live helper]
- _tmux_window_exists [live helper]
- _tmux_pane_has_title [live helper]
- _tmux_show_option [live helper]
- _kill [live helper]
- tmux_session_clean [live fixture]
- test_ensure_session_creates_new_session [Create live]
- test_ensure_session_sets_keepalive_pane_title [Create live]
- test_ensure_session_applies_pane_border_status_top [Create live]
- test_split_worker_pane_returns_pane_id [Create live]
- test_ensure_session_idempotent_on_existing_session [Create live]
- test_ensure_session_adds_new_window_to_existing_session [Create live]
- _writeSidecar [helper]
- kill_calls [helper]
- fake_tmux [helper]
- _make_tmpdir [helper]
- class FakeClock [helper — INTERNAL_DUPLICATE: also in test_plate_lib.py; pull into tests/fixtures/]
  - FakeClock.__init__
  - FakeClock.__call__
- class FakeTmux [helper — INTERNAL_DUPLICATE: also in test_plate_lib.py; pull into tests/fixtures/]
  - FakeTmux.__init__
  - FakeTmux.__call__

(191 functions, 5 classes)

### tests/test_todo_lib.py — NEEDS_SPLIT: 4 files (list / capture / stop / send) + 8 misplaced jot tests MOVE_TO test_jot_lib.py

- test_todo_launcher_success [send — phase2 launcher entry]
- _setStdin [list helper]
- test_non_todoList_prompt_exits_silently [list]
- test_bad_prompt_after_fast_path_exits_silently [list]
- test_missing_repo_emits_not_a_git_repo [list]
- test_missing_todos_folder_emits_message [list]
- test_empty_formatter_output_emits_no_open_todos [list]
- test_non_empty_formatter_output_is_forwarded [list]
- _set_stdin [capture helper]
- _base_env [capture helper]
- _patch_repo_root [capture helper]
- test_missing_plugin_data_raises [capture]
- test_non_todo_input_exits_zero_silently [capture]
- test_bad_prompt_format_exits_zero [capture]
- test_missing_git_repo_emits_block [capture]
- test_happy_path_writes_valid_pending_json [capture]
- test_idea_with_quotes_and_newlines_round_trips [capture]
- test_bare_todo_yields_empty_idea [capture]
- base_env [MOVE_TO: tests/test_jot_lib.py — jot fixture]
- _stub_passing_deps [MOVE_TO: tests/test_jot_lib.py — jot helper]
- _stdin [MOVE_TO: tests/test_jot_lib.py — jot helper]
- test_missing_plugin_env_raises [MOVE_TO: tests/test_jot_lib.py — tests jot_main, not todo]
- test_non_jot_input_exits_zero_silently [MOVE_TO: tests/test_jot_lib.py — tests jot_main]
- test_prompt_not_strict_jot_exits_zero [MOVE_TO: tests/test_jot_lib.py — tests jot_main]
- test_empty_idea_emits_block [MOVE_TO: tests/test_jot_lib.py — tests jot_main]
- test_missing_repo_emits_block [MOVE_TO: tests/test_jot_lib.py — tests jot_main]
- test_happy_path_writes_input_file_with_all_sections [MOVE_TO: tests/test_jot_lib.py — tests jot_main]
- test_skip_launch_does_not_call_phase2 [MOVE_TO: tests/test_jot_lib.py — tests jot_main]
- test_phase2_called_on_happy_path [MOVE_TO: tests/test_jot_lib.py — tests jot_main]
- test_safe_wrapper_falls_back_to_unavailable [stop — cleanup safety]
- test_empty_string_is_rejected [stop — cleanup safety]
- test_nonexistent_valid_path_is_silently_ignored [stop — cleanup safety]
- test_valid_tmp_prefix_calls_rmtree [stop — cleanup safety]
- test_valid_tmp_prefix_suffix_variation [stop — cleanup safety]
- test_valid_private_tmp_prefix_calls_rmtree [stop — cleanup safety]
- test_invalid_prefix_prints_stderr_and_skips_rmtree [stop — cleanup safety]
- test_invalid_prefix_leaves_directory_intact [stop — cleanup safety]
- test_missing_args_returns_early [stop]
- _make_tmpdir [stop helper]
- test_missing_state_dir_returns_early [stop]
- test_empty_sidecar_logs_and_returns [stop]
- test_missing_sidecar_file_logs_and_returns [stop]
- test_processed_marker_writes_success_to_audit [stop]
- test_processed_marker_removes_input_file [stop]
- test_no_processed_marker_writes_fail_to_audit [stop]
- test_no_processed_marker_does_not_remove_input_file [stop]
- test_missing_input_file_writes_fail_missing_to_audit [stop]
- test_audit_rotated_when_over_1000_lines [stop]
- test_kill_pane_called_with_correct_target [stop]
- test_retile_called_with_todo_todos_window [stop]
- test_state_dir_created_if_absent [stop]
- test_returns_empty_list_when_todos_dir_missing [list — scan_open_todos]
- _write [list helper]
- test_returns_empty_list_when_todos_dir_has_no_markdown [list — scan_open_todos]
- test_returns_only_files_with_status_open_in_frontmatter [list — scan_open_todos]
- test_results_are_sorted_alphabetically_like_bash_glob [list — scan_open_todos]
- test_status_open_must_anchor_at_line_start [list — scan_open_todos]
- test_only_first_ten_lines_are_inspected [list — scan_open_todos]
- test_returns_absolute_paths [list — scan_open_todos]
- test_accepts_string_path_argument [list — scan_open_todos]
- test_missing_input_file_returns_0 [send]
- test_missing_tmpdir_inv_returns_0 [send]
- test_missing_sidecar_returns_0 [send]
- test_empty_sidecar_returns_0 [send]
- test_claude_not_ready_returns_1 [send]
- test_happy_path_sends_prompt [send]
- test_happy_path_propagates_send_rc [send]
- test_sidecar_read_strips_whitespace [send]

(68 functions, 0 classes)

### tests/test_util_lib.py — NEEDS_SPLIT: 3 files (shell / terminal / filelock)

- test_shell_runWithTimeout_returns_zero_for_successful_fast_command [shell]
- test_shell_runWithTimeout_returns_nonzero_for_failing_fast_command [shell]
- test_shell_runWithTimeout_kills_command_that_exceeds_timeout [shell]
- test_shell_runWithTimeout_returns_promptly_when_command_finishes_early [shell]
- test_shell_runWithTimeout_kills_process_that_ignores_sigterm [shell]
- test_terminal_spawnIfNeeded_empty_session_raises_value_error [terminal]
- test_terminal_spawnIfNeeded_skips_spawn_when_clients_attached [terminal]
- test_terminal_spawnIfNeeded_darwin_spawns_osascript_with_attach_command [terminal]
- test_terminal_spawnIfNeeded_darwin_maximize_yes_includes_full_desktop_block [terminal]
- test_terminal_spawnIfNeeded_darwin_maximize_compact_includes_centred_1000x700_block [terminal]
- test_terminal_spawnIfNeeded_darwin_missing_osascript_writes_advisory_and_returns_zero [terminal]
- test_terminal_spawnIfNeeded_non_darwin_writes_advisory_and_does_not_spawn [terminal]
- test_terminal_spawnIfNeeded_dev_null_log_does_not_create_file [terminal]
- test_terminal_spawnIfNeeded_advisory_write_failure_is_swallowed [terminal]
- _hold_lock_worker [filelock helper]
- _try_acquire_worker [filelock helper]
- test_FileLock_acquire_succeeds_on_fresh_path [filelock]
- test_FileLock_release_clears_acquired_state [filelock]
- test_FileLock_reacquire_after_release [filelock]
- test_FileLock_release_is_idempotent_when_not_held [filelock]
- test_FileLock_competing_process_blocks_until_holder_releases [filelock]
- test_FileLock_timeout_elapses_when_lock_is_held [filelock]
- test_FileLock_auto_released_when_holder_process_dies [filelock]
- _write_lock [filelock helper]
- test_darwin_terminal_not_running_launches_terminal [terminal]
- test_darwin_terminal_already_running_skips_launch [terminal]
- test_non_darwin_never_launches_terminal [terminal]
- _noop [terminal helper]
- _make_main_mock [terminal helper]
- test_terminal_launch_before_debate_main [terminal]
- _write_lock_at_path [filelock helper]
- _make_lock [filelock helper]
- _write [filelock helper — INTERNAL_DUPLICATE: appears 2x in this file]
- test_returns_true_when_file_already_nonempty [shell — shell_waitForFile]
- test_returns_false_when_file_never_appears [shell]
- test_returns_false_when_file_exists_but_empty [shell]
- test_returns_true_when_file_appears_during_polling [shell]
- _read [shell helper]
- _write [shell helper — INTERNAL_DUPLICATE: appears 2x in this file]

(39 functions, 0 classes)

---

**Totals:** 51 files, 1319 functions, 29 classes.

