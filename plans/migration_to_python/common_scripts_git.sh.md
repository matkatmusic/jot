# Migrate `common/scripts/git.sh` to Python

## Source

- File: `common/scripts/git.sh`
- Class: `(sourced)` — Medium. Sourced by 9 callers; never invoked as a subprocess. Bash shim must keep function names intact.
- Size: 207 lines bash (7 functions; 1 is internal self-test)
- Dependency graph position: leaf utility for git plumbing. Sources `silencers.sh` (`hide_output`, `hide_errors`). No further upstream deps.
- Convo-summary trailer logic: **NOT in git.sh**. Recent trailer work (commits 5cf06f5, 6c631c6) lives in `skills/plate/scripts/`. git.sh is pure git query helpers; trailer parsing is out of scope.

## Live callers (must keep working through shim)

Sourced by:
1. `skills/todo-list/scripts/todo-list.sh:15` - `. "$REPO/common/scripts/git.sh"`
2. `skills/jot/scripts/jot.sh:127` - `. "${CLAUDE_PLUGIN_ROOT}/common/scripts/git.sh"`
3. `skills/plate/scripts/plate.sh:20` - `. "${CLAUDE_PLUGIN_ROOT}/common/scripts/git.sh"`
4. `skills/plate/scripts/archive/paths.sh:4` - archive (verify dead before skipping)
5. `skills/plate/tests/plate-e2e-live.sh:23` - `source "$REPO_ROOT/common/scripts/git.sh"`
6. `skills/plate/tests/plate-claude-e2e.sh:19` - `source ...`
7. `skills/todo/scripts/todo.sh:21` - `. "$REPO/common/scripts/git.sh"`
8. `skills/todo/scripts/todo-launcher.sh:33` - `. "$PLUGIN_ROOT/common/scripts/git.sh"`

Functions consumed externally (verify exact set during step 2): `git_is_repo`, `git_get_repo_root`, `git_get_branch_name`, `git_get_recent_commits`, `git_get_uncommitted`, `git_ensure_gitignore_entry`. `git_tests` is internal self-test - confirm no caller references it.

## Behavior spec (per function)

### `git_is_repo <directory>`
- Runs `git -C <dir> rev-parse --is-inside-work-tree` with stdout+stderr suppressed.
- Returns 0 if inside work tree, 1 otherwise. No stdout.

### `git_get_repo_root [directory]`
- Default directory: `.`
- Runs `git -C <dir> rev-parse --git-common-dir` (stderr suppressed).
- On failure: stderr `[git] not inside a git repository`, return 1.
- On success: prints `(cd dir && cd dirname(git_common_dir) && pwd)`. The double-cd resolves the **main** repo root (handles linked worktrees and bare-style `.git` files).

### `git_get_branch_name <directory>`
- If `git_is_repo` fails: stderr `[git] not a git repository: <dir>`, return 1.
- Runs `git -C <dir> branch --show-current`.
- Empty output (detached HEAD): stderr `HEAD detached at <short-sha>`, return 1.
- Else: stdout = branch name, return 0.

### `git_get_recent_commits <directory>`
- If not a repo: stderr `[git] not a git repository: <dir>`, return 1.
- Runs `git -C <dir> log --oneline -5 --format='%h'`, joins newlines into a single space-separated line, strips trailing space.
- No commits: stderr `No commits yet`, return 1.
- Else: stdout = space-separated short hashes (newest first), return 0.

### `git_get_uncommitted <directory>`
- If not a repo: stderr `[git] not a git repository: <dir>`, return 1.
- Runs `git -C <dir> status --short`, takes whitespace field 2 per line, joins with spaces, strips trailing space.
- Clean tree (empty): stdout `None`, return 0.
- Else: stdout = space-separated filenames, return 0.
- Caveat: `awk '{print $2}'` mishandles renames (`R old -> new` yields `->`) and quoted paths with spaces. Port preserves observable output by default; flag deviation if fixed.

### `git_ensure_gitignore_entry <repo_root> <pattern>`
- Target: `<repo_root>/.gitignore`.
- If `grep -qxF` finds exact-line match: no-op.
- Else: appends `\n<pattern>\n`.
- Idempotent. No repo check (caller guarantees). Always returns 0 in current bash impl despite header doc.

### `git_tests`
- Internal mktemp-based self-test harness exercising all 6 public functions. Replaced by pytest; not exposed in shim unless callers reference it (none do - verify).

## External commands & env vars

- External commands: `git`, `awk`, `grep`, `sed`, `tr`, `mktemp` (tests only), `printf`, `echo`, `wc` (tests only).
- Env vars: only `${BASH_SOURCE[0]}` for self-locating silencers. No other env reads.
- Side effects:
  - Writes to `<repo_root>/.gitignore` (append-only).
  - `git_tests` creates and removes `mktemp -d` dirs.
- All read functions are read-only against the repo.

## Target Python module path

- Library: `common/scripts/git_lib.py` (importable, pure functions).
- CLI shim: `common/scripts/git_cli.py` (argparse subcommands).
- Bash shim (replacement for `git.sh`): same path; body becomes function definitions delegating to `python3 git_cli.py <subcmd>`.

### `git_lib.py` public API

```python
def git_is_repo(directory: Path) -> bool: ...
def git_get_repo_root(directory: Path | None = None) -> Path: ...        # raises NotARepoError
def git_get_branch_name(directory: Path) -> str: ...                      # raises NotARepoError, DetachedHeadError
def git_get_recent_commits(directory: Path, count: int = 5) -> list[str]: ... # raises NotARepoError, NoCommitsError
def git_get_uncommitted(directory: Path) -> list[str]: ...                # [] means clean
def git_ensure_gitignore_entry(repo_root: Path, pattern: str) -> bool: ...# True if appended, False if already present
```

Module-level exception classes: `NotARepoError`, `DetachedHeadError`, `NoCommitsError`. `git_cli.py` translates them to bash-compatible `(stderr message, exit code)`.

### `git_cli.py` shim spec

argparse dispatcher with subcommands matching bash function names. Each subcommand emits stdout/stderr and exits with the bash-equivalent code.

Subcommand list:
- `is-repo <dir>` -> exit 0/1, no stdout.
- `get-repo-root [dir]` -> stdout abspath OR stderr `[git] not inside a git repository`, exit 0/1.
- `get-branch-name <dir>` -> stdout branch OR stderr (`[git] not a git repository: ...` | `HEAD detached at <sha>`), exit 0/1.
- `get-recent-commits <dir>` -> stdout `h1 h2 h3 h4 h5` OR stderr (`[git] not a git repository: ...` | `No commits yet`), exit 0/1.
- `get-uncommitted <dir>` -> stdout `None` | `f1 f2 ...` OR stderr `[git] not a git repository: ...`, exit 0/1.
- `ensure-gitignore-entry <repo_root> <pattern>` -> exit 0.

### Bash shim body (`git.sh` after migration)

```bash
#!/bin/bash
# git.sh - bash compatibility shim. Real logic in git_cli.py.
_GIT_CLI="$(dirname "${BASH_SOURCE[0]}")/git_cli.py"

git_is_repo()                { python3 "$_GIT_CLI" is-repo "$1"; }
git_get_repo_root()          { python3 "$_GIT_CLI" get-repo-root "${1:-.}"; }
git_get_branch_name()        { python3 "$_GIT_CLI" get-branch-name "$1"; }
git_get_recent_commits()     { python3 "$_GIT_CLI" get-recent-commits "$1"; }
git_get_uncommitted()        { python3 "$_GIT_CLI" get-uncommitted "$1"; }
git_ensure_gitignore_entry() { python3 "$_GIT_CLI" ensure-gitignore-entry "$1" "$2"; }
```

`git_tests` dropped (pytest replaces). Drop `source silencers.sh` only after confirming no transitive consumer.

## RED test scenarios (pytest, plain English first)

File: `tests/test_git_lib.py`. Each scenario fails initially with `assert False`; refine to real assertions during GREEN. Use `tmp_path` + `subprocess.run(["git", "-C", ...])` for fixtures.

### git_is_repo
1. `test_git_is_repo_returns_true_for_initialized_repo` - init repo in tmp_path, expect True.
2. `test_git_is_repo_returns_false_for_plain_directory` - bare tmp_path, expect False.
3. `test_git_is_repo_returns_false_for_nonexistent_path` - pass `/nonexistent/abc`, expect False, no exception.
4. `test_git_is_repo_true_inside_subdirectory_of_repo` - nested dir of a repo, expect True.

### git_get_repo_root
5. `test_git_get_repo_root_returns_absolute_repo_path` - init repo, returned path == `tmp_path.resolve()`.
6. `test_git_get_repo_root_raises_for_non_repo` - expect NotARepoError.
7. `test_git_get_repo_root_returns_main_root_from_linked_worktree` - main repo + `git worktree add`; query worktree, expect main repo root (validates double-cd dirname trick).
8. `test_git_get_repo_root_defaults_to_cwd_when_no_arg` - chdir into repo, no arg, expect repo root.

### git_get_branch_name
9. `test_git_get_branch_name_returns_current_branch` - init repo with commit on `main-test`, expect `"main-test"`.
10. `test_git_get_branch_name_raises_on_detached_head` - checkout SHA, expect DetachedHeadError.
11. `test_git_get_branch_name_raises_on_non_repo` - expect NotARepoError.

### git_get_recent_commits
12. `test_git_get_recent_commits_returns_short_hashes_newest_first` - 3 commits, expect 3 hashes, first is HEAD short SHA.
13. `test_git_get_recent_commits_caps_at_five` - 7 commits, expect exactly 5.
14. `test_git_get_recent_commits_raises_on_empty_repo` - init only, expect NoCommitsError.
15. `test_git_get_recent_commits_raises_on_non_repo` - expect NotARepoError.

### git_get_uncommitted
16. `test_git_get_uncommitted_returns_empty_list_for_clean_tree` - committed repo, expect [].
17. `test_git_get_uncommitted_lists_modified_file` - modify tracked file, expect filename in list.
18. `test_git_get_uncommitted_lists_untracked_file` - untracked file, expect filename in list.
19. `test_git_get_uncommitted_raises_on_non_repo` - expect NotARepoError.
20. `test_git_get_uncommitted_handles_filenames_with_spaces` - explicit deviation test; document expected behavior (replicate bash bug or fix).

### git_ensure_gitignore_entry
21. `test_git_ensure_gitignore_entry_appends_when_missing` - empty `.gitignore`, call with `.plate/`, expect file contains `.plate/`, returns True.
22. `test_git_ensure_gitignore_entry_is_idempotent_for_existing_entry` - pre-populated with `.plate/`, call again, expect single occurrence, returns False.
23. `test_git_ensure_gitignore_entry_creates_file_if_missing` - no `.gitignore` exists, expect created with pattern.
24. `test_git_ensure_gitignore_entry_does_not_match_substring` - file contains `.plate/old`; call with `.plate/`; expect both lines after.
25. `test_git_ensure_gitignore_entry_preserves_trailing_newline_pattern` - verify exact byte output matches bash's `printf '\n%s\n'`.

### CLI parity (subprocess against `git_cli.py`)
26. `test_cli_is_repo_exit_code_matches_bash` - exit 0 inside repo, 1 outside.
27. `test_cli_get_repo_root_stderr_message_matches_bash` - stderr text == `[git] not inside a git repository`.
28. `test_cli_get_branch_name_stderr_for_non_repo_matches_bash` - stderr text == `[git] not a git repository: <dir>`.
29. `test_cli_get_branch_name_stderr_for_detached_head_matches_bash` - `HEAD detached at <short-sha>` format.
30. `test_cli_get_recent_commits_stdout_is_space_separated_no_trailing_space`.
31. `test_cli_get_uncommitted_clean_prints_None_on_stdout`.

### Shim parity (sourced bash test)
32. `test_bash_shim_sources_without_error` - `bash -c '. git.sh'` exits 0.
33. `test_bash_shim_function_names_resolve` - assert each of 6 functions callable after sourcing.
34. `test_bash_shim_git_get_branch_name_matches_python_output_for_real_repo` - end-to-end via tmp repo.

**Total: 34 RED scenarios.**

## Risk callouts

1. **Repo-root double-cd semantics.** The `--git-common-dir` + `dirname` recipe returns the **main** repo root from a linked worktree. Naive `git rev-parse --show-toplevel` returns the worktree path. Port must mirror the bash recipe to preserve plate behavior across worktrees.
2. **`git status --short | awk '{print $2}'`** mishandles renames (`R old -> new`) and filenames with spaces or rename arrows. Replicate by default; flag in test #20.
3. **Stderr message text is part of the contract.** Plate/jot scripts may grep stderr. Exact strings (`[git] not inside a git repository`, `HEAD detached at <sha>`, `No commits yet`, `[git] not a git repository: <dir>`) must round-trip byte-for-byte.
4. **Trailing-space trimming.** Bash uses `tr '\n' ' ' | sed 's/ $//'`. Python `" ".join(...)` is equivalent; do not accidentally add a trailing space.
5. **Multi-line folding (convo-summary trailers): NOT applicable to git.sh.** That logic lives in `skills/plate/`. Listed only to confirm out-of-scope.
6. **`silencers.sh` dependency.** Bash shim no longer needs to source it (Python captures stderr internally). Confirm no caller relies on git.sh transitively exposing `hide_errors` / `hide_output`.
7. **`python3` startup latency.** Each shim function spawns a fresh interpreter. Plate hot paths call `git_get_branch_name` repeatedly. Measure before declaring done; if material, batch via single Python entry point. Out of scope for v1.
8. **`git_get_repo_root` default arg.** Bash defaults to `.`. Use `directory: Path | None = None` and resolve at call time, not import time.

## Verification plan

### Pytest
- `pytest tests/test_git_lib.py -v` - all 34 scenarios green.
- Coverage target: >=95% on `git_lib.py`.

### Bash shim parity
- Source the new `git.sh` from a scratch bash shell; manually invoke each of the 6 functions; compare stdout/stderr/exit against pre-migration captures (capture them in step 2 BEFORE changing anything).

### Live caller regression
For each caller in the list above, exercise the path that sources git.sh:
1. `skills/jot/scripts/jot.sh` - run `/jot foo` flow end-to-end; verify `git_get_branch_name`, `git_get_recent_commits`, `git_get_uncommitted` produce identical output to a bash-only worktree of the same SHA.
2. `skills/todo/scripts/todo.sh` and `todo-launcher.sh` - run `/todo bar`; check generated TODO file's `Branch:` and `Recent commits:` lines.
3. `skills/todo-list/scripts/todo-list.sh` - run `/todo-list`; verify branch column.
4. `skills/plate/scripts/plate.sh` - run `/plate` then `/plate --done`; verify `.plate/` is added to `.gitignore` exactly once, repo root resolves correctly inside a linked worktree.
5. `skills/plate/tests/plate-e2e-live.sh` and `plate-claude-e2e.sh` - execute as-is; both must pass without modification.
6. `skills/plate/scripts/archive/paths.sh` - confirm dead before declaring victory; if live, exercise it.

### Failing-verification design (per `feedback_verify_work.md`)
Verification fails if: a caller emits different stdout/stderr after migration, OR exit codes differ, OR `.gitignore` accumulates duplicates, OR linked-worktree plate ops resolve to worktree path instead of main repo root. Capture pre-migration outputs first; diff post-migration. No eyeballing.

## Numbered TODO list (template steps 0-8)

0. **Plan TODO list** - this list.
1. **Mark `[i]`** in `MIGRATION_TO_PYTHON.md` for `common/scripts/git.sh` (verify line entries on lines 95, 131, 190).
2. **Capture pre-migration golden output.** For each function, run against fixture repos (clean, dirty, detached, empty, linked worktree) and save stdout+stderr+exit to `tests/fixtures/git_sh_golden/`. Parity oracle.
3. **Write RED tests** in `tests/test_git_lib.py` (34 scenarios). Run pytest; confirm all fail.
4. **Mark `[~]`** in `MIGRATION_TO_PYTHON.md`.
5. **Implement `common/scripts/git_lib.py`** - pure functions, custom exceptions (`NotARepoError`, `DetachedHeadError`, `NoCommitsError`). Use `subprocess.run([...], capture_output=True, check=False)`; never `shell=True`.
6. **Run pytest**; iterate `git_lib.py` until all RED -> GREEN. Do NOT proceed until 34/34 pass.
7. **Implement `common/scripts/git_cli.py`** - argparse dispatcher. Replicate exact stderr strings and exit codes. Add CLI parity tests (#26-31) and shim tests (#32-34); iterate to GREEN.
8. **Replace `common/scripts/git.sh` body** with the bash shim above. Drop `silencers.sh` source only after confirming no caller depends on it via this file.
9. **End-to-end verification** - run live-caller checklist above. Diff against goldens from step 2. Run `plate-e2e-live.sh` and `plate-claude-e2e.sh` - both must exit 0.
10. **Mark `[x]`** in `MIGRATION_TO_PYTHON.md`. Document any deviations (e.g., `git status` filename-with-spaces handling) in the migration entry.

