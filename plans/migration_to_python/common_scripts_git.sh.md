# `common/scripts/git.sh`: in progress

**Status:** `[~]` (in progress). Python module and tests already exist; bash callers and `.sh` deletion remain.

## Current state

- `common/scripts/git_lib.py` exists (~15.6KB, 44 functions). Extracted from `common/scripts/plate/plate_lib.py` on the archived `DNU-python-migration-plate` branch and migrated forward.
- `tests/test_git_lib.py` exists (~44 tests). Covers both the plate-extracted API and the `git.sh`-parity helpers.
- `common/scripts/git.sh` still exists with 6 public bash functions; live callers still source it.
- `git_lib.py` is structured in two halves:
  1. **Plate-extracted API** (lines 1-300): general-purpose git utilities used by plate (commits, trailers, patches, stashing, tree-SHA, env-based git operations, branch ops). Not in scope for `git.sh` parity but available to future Python callers.
  2. **`git.sh` parity helpers** (lines 302+): explicit replacements for the 6 public bash functions, plus a `GitError` exception that the bash shim maps to exit-1 + stderr message.

## Naming convention divergence

`git_lib.py` uses **camelCase** for public function names (matches the prior `plate_lib.py` extraction style). This diverges from the MIGRATION_TO_PYTHON.md philosophy line that says "every bash function becomes a Python function with the same name." The parity helpers were named to fit the camelCase module they were added to, not to match the bash `git_*` snake_case names.

Decision: do not rename `git_lib.py` to satisfy the philosophy. The camelCase convention is the existing precedent for new Python modules in this repo. The philosophy line should be softened to "match the existing module's naming convention; preserve bash names verbatim only when the receiving module has no convention yet." Flagged for follow-up edit on `MIGRATION_TO_PYTHON.md`.

## Bash to Python name map

| bash (in `git.sh`) | Python (in `git_lib.py`) | notes |
|---|---|---|
| `git_is_repo` | `isGitRepo(path: Path) -> bool` | line 61. |
| `git_get_repo_root` | `getGitRepoRoot(path: Path) -> Path` | line 313. Raises `GitError` on miss. |
| `git_get_branch_name` | `getGitBranchNameOrFail(path: Path) -> str` | line 336. Raises `GitError` on miss / detached HEAD. |
| `git_get_recent_commits` | `getGitRecentCommitHashes(path: Path, n: int = 5) -> list[str]` | line 353. Returns list, not space-joined string. Raises `GitError` on empty repo / non-repo. |
| `git_get_uncommitted` | `getGitUncommittedFilenames(path: Path) -> list[str]` | line 374. Returns `[]` for clean tree (was: bash printed `"None"`). Raises `GitError` on non-repo. |
| `git_ensure_gitignore_entry` | `ensureGitignoreEntry(repo_root: Path, pattern: str) -> None` | line 398. Returns `None` instead of bash exit code. |

`git_tests` (bash internal self-test): dropped. Replaced by pytest coverage in `tests/test_git_lib.py`.

## Remaining work

The `_lib.py` and tests are done. What's left is the caller side and `.sh` deletion.

### 1. Update bash callers

For each caller, choose migrate-together or transitional shim:

| Caller | Action |
|---|---|
| `skills/jot/scripts/jot.sh:127` | Migrate-together when jot.sh's own plan lands; replace `. "$REPO/common/scripts/git.sh"` + bash function calls with `from common.scripts.git_lib import getGitBranchNameOrFail, ...`. |
| `skills/plate/scripts/plate.sh:20` | Same. Heaviest consumer (`getGitRepoRoot` across worktrees, `ensureGitignoreEntry` for `.plate/`). |
| `skills/todo/scripts/todo.sh:21` | Same. |
| `skills/todo/scripts/todo-launcher.sh:33` | Same. |
| `skills/todo-list/scripts/todo-list.sh:15` | Same. |
| `skills/plate/tests/plate-e2e-live.sh:23` | Bash test harness; either rewrite to invoke Python or migrate harness in same change. |
| `skills/plate/tests/plate-claude-e2e.sh:19` | Same as e2e-live. |
| `skills/plate/scripts/archive/paths.sh:4` | Verify dead before final deletion; if live, treat as caller. |

If any bash caller has not migrated when this script's deletion is queued, install a transitional `[s]` shim at `common/scripts/git.sh` whose body replaces each `git_*` function with a `python3 -c "from common.scripts.git_lib import <camelCase>; ..." "$@"` wrapper, and mark `git.sh` as `[s]` in the tracker.

### 2. Stderr message contract audit

Bash callers currently rely on these literal stderr strings (grep before deletion):
- `[git] not inside a git repository`
- `[git] not a git repository: <dir>`
- `HEAD detached at <sha>`
- `No commits yet`

`GitError` carries a message; the transitional shim must reproduce these exact strings on stderr to preserve the contract. Audit each caller's stderr-grep usage before installing the shim.

### 3. Delete `git.sh`

When no caller sources `git.sh`: `git rm common/scripts/git.sh`. Tracker entry flips from `[~]` (or `[s]` if a transitional shim was installed) to `[x]`.

## Verification

- `pytest tests/test_git_lib.py -v` -> all 44 GREEN. **Already satisfied by current branch state.** Re-run on each caller migration to catch regressions.
- Live integration on caller migration: run `/jot`, `/plate`, `/plate --done`, `/todo`, `/todo-list` end-to-end; capture pre-migration goldens for each function's output and diff against post-migration.
- `git.sh` deletion: run `git grep -nE '(\. |source ).*git\.sh' -- ':!docs' ':!*.md'` and confirm zero matches before `git rm`.

## Risk callouts

1. **`git_get_uncommitted` clean-tree return.** Bash printed `"None"`; Python returns `[]`. If any caller's downstream rendering checks for the literal `"None"` string, that caller's migration must convert. Audit during step 1.
2. **`git_get_recent_commits` return shape.** Bash returned space-joined string; Python returns list. Same audit during step 1.
3. **Stderr contract preservation.** See section 2 above.
4. **`silencers.sh` dependency.** `git.sh` sources it; `git_lib.py` does not (uses `subprocess.run(capture_output=True)`). Confirm no caller leans on `git.sh` transitively re-exporting `hide_errors` / `hide_output`.
5. **Plate-extracted API exposure.** `git_lib.py` includes ~38 functions beyond the 6-function bash parity surface. These were extracted for plate's needs and are now general-purpose; document them as available, but no caller is required to use them.
