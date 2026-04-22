append_plate_to_stack.py: appends a new plate to an instance JSON `stack[]` (creates the instance file if it doesn't exist yet)
build_settings_json.py: builds the per-invocation `settings.json` for the bg-agent tmux window with expanded permissions and SessionStart/Stop/SessionEnd worker hooks
cascade_parent_chain.py: removes a completed child from the parent's `delegated_to[]` and flips the parent plate back to `paused` when no delegated children remain
check_drift_alert.py: prints and clears any pending drift-alert message on an instance (silent if none)
check_live_children.py: prints `yes`/`no` indicating whether an instance has any plate in `delegated` state with live `delegated_to` children
check_rolling_intent_refresh.py: prints `yes` if the instance's rolling-intent snapshot is missing or older than 5 minutes, `no` otherwise
clear_drift_alert.py: clears any stale drift-alert flag on session resume
commit_message.py: reads a plate JSON on stdin and formats its commit message per spec §7.3
instance_rw.py: atomic JSON read/write/mutate helpers for `.plate/instances/*.json` plus a CLI (`stack-oldest`, `stack-newest`, `top`, `drop-top`, `complete`, `touch`, `create-instance`)
list_paused_plates.py: prints one row per paused plate in an instance file as `convoID|plate_id|label|summary_action|pushed_at`
next_resume_point.py: walks the parent-delegation chain upward and prints the next ancestor that still has paused work (with the `cd ... && claude --resume ...` command)
print_resume_pointer.py: prints the `cd ... && claude --resume <convo>` command for the instance's immediate parent, if one exists
register_parent.py: sets a child instance's `parent_ref`, appends the child to the parent's `delegated_to[]`, and flips the parent plate's state to `delegated`
render_tree.py: renders `.plate/tree.md` showing the parent/child delegation tree across every instance JSON, sorted by `last_touched` desc
transcript_parse.py: parses a Claude `.jsonl` transcript with `parentUuid` dedup — subcommands `dedup`, `recent [n]`, `errors [since_ts]`
verify_stash_refs.py: verifies each plate's `refs/plates/<convo>/<plate>` git ref exists and `push_time_head_sha` is still an ancestor of HEAD, warning on stderr otherwise
