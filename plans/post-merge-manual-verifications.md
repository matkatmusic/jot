# Post-merge manual verifications

These checks cannot run inside the python-migration worktree because Claude Code uses the cached/installed plugin code at `/plate` time, not the in-tree source. Run them after this branch is merged into `fix-plate-bugs` and the plugin is reinstalled.

## /plate summary-agent shell->python migration (worktree: python-migration)

Verifies that `spawn_summary_agent.py` no longer touches any `.sh` files - three subprocess paths must resolve through Python.

Steps:
1. After merging all branches into `main` and tagging the repo and pushing to github, reinstall the plugin so the merged code is what `/plate` invokes.
2. `cd` into a repo with at least one **tracked** dirty file plus one **untracked** file. **untracked** means a new file that has never been committed.
3. Run `/plate` interactively in Claude Code.
4. Observe: a tmux session named `plate-summary-<N>` is created and a Terminal.app window auto-attaches to it.
5. Observe: the spawned agent writes a summary file under `/var/folders/.../plate-summary-*/summary.txt`.
6. Observe: once the summary file is non-empty, the watcher subprocess sends `/exit` into the pane and the agent exits cleanly.
7. Observe: SessionEnd fires. Check `<repo>/.plate/plate-log.txt` for a line like:
   `<ts> plate-summary-stop repo=<repo> branch=<branch> out=plate: summary written (<sha8> on <branch>-plate)`
8. Observe: the plate-branch tip's commit subject and trailers were rewritten with the agent's summary.

If any step fails, the corresponding subprocess path is broken - debug by looking at the per-invocation tmpdir's `settings.json` to confirm the SessionEnd command starts with `python3` (not `bash`).
