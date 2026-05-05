# Git Cluster Marker Swap (jot-plugin-orchestrator.sh)

Date: 2026-05-04
Scope: Marker-only work. No bash translation. The cluster is already owned by
`common/scripts/git_lib.py` and `tests/test_git_lib.py`.

## Per-function marker replacements

For each function, the line listed below is the `# [PENDING]` marker
immediately above the function definition in
`/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/jot-plugin-orchestrator.sh`.
Replace that single line with the listed string.

| Bash function | PENDING line # | Function def line # | Replacement marker line |
|---|---|---|---|
| git_is_repo | 1289 | 1290 | `# [IMPORT_FROM_GIT_LIB -> git_lib.isGitRepo @ 2026-05-04]` |
| git_get_repo_root | 1298 | 1299 | `# [IMPORT_FROM_GIT_LIB -> git_lib.getGitRepoRoot @ 2026-05-04]` |
| git_get_branch_name | 1313 | 1314 | `# [IMPORT_FROM_GIT_LIB -> git_lib.getGitBranchNameOrFail @ 2026-05-04]` |
| git_get_recent_commits | 1330 | 1331 | `# [IMPORT_FROM_GIT_LIB -> git_lib.getGitRecentCommitHashes @ 2026-05-04]` |
| git_get_uncommitted | 1348 | 1349 | `# [IMPORT_FROM_GIT_LIB -> git_lib.getGitUncommittedFilenames @ 2026-05-04]` |
| git_ensure_gitignore_entry | 1366 | 1367 | `# [IMPORT_FROM_GIT_LIB -> git_lib.ensureGitignoreEntry @ 2026-05-04]` |
| git_tests | 1375 | 1376 | `# [COVERED_BY_GIT_LIB_TESTS @ 2026-05-04]` |

## Migration name-map rows

Append these to the migration name-map. `git_tests` is intentionally omitted
from the name-map — tests are not on the production surface and are covered by
`tests/test_git_lib.py`.

| Python symbol | Bash symbol | Status | Tag | Date |
|---|---|---|---|---|
| git_lib.isGitRepo | git_is_repo | (existing in git_lib.py) | IMPORT_FROM_GIT_LIB | 2026-05-04 |
| git_lib.getGitRepoRoot | git_get_repo_root | (existing in git_lib.py) | IMPORT_FROM_GIT_LIB | 2026-05-04 |
| git_lib.getGitBranchNameOrFail | git_get_branch_name | (existing in git_lib.py) | IMPORT_FROM_GIT_LIB | 2026-05-04 |
| git_lib.getGitRecentCommitHashes | git_get_recent_commits | (existing in git_lib.py) | IMPORT_FROM_GIT_LIB | 2026-05-04 |
| git_lib.getGitUncommittedFilenames | git_get_uncommitted | (existing in git_lib.py) | IMPORT_FROM_GIT_LIB | 2026-05-04 |
| git_lib.ensureGitignoreEntry | git_ensure_gitignore_entry | (existing in git_lib.py) | IMPORT_FROM_GIT_LIB | 2026-05-04 |
| (n/a — tests not on production surface) | git_tests | covered by tests/test_git_lib.py | COVERED_BY_GIT_LIB_TESTS | 2026-05-04 |

## Call sites inside jot-plugin-orchestrator.sh

These are the in-file call sites of the 6 production git functions. When the
orchestrator itself is converted to Python, swap each call to its
`git_lib.<name>` equivalent (per the name-map above). Internal calls inside
`git_tests` (lines 1379–1492) are intentionally excluded — that whole function
disappears under COVERED_BY_GIT_LIB_TESTS.

| Line | Caller context | Bash call | Python target |
|---|---|---|---|
| 1315 | inside `git_get_branch_name` | `git_is_repo "$1"` | `git_lib.isGitRepo` |
| 1332 | inside `git_get_recent_commits` | `git_is_repo "$1"` | `git_lib.isGitRepo` |
| 1350 | inside `git_get_uncommitted` | `git_is_repo "$1"` | `git_lib.isGitRepo` |
| 1973 | snapshot-of-state block | `safe git_get_branch_name "$CWD"` | `git_lib.getGitBranchNameOrFail` |
| 1974 | snapshot-of-state block | `safe git_get_recent_commits "$CWD"` | `git_lib.getGitRecentCommitHashes` |
| 1975 | snapshot-of-state block | `safe git_get_uncommitted "$CWD"` | `git_lib.getGitUncommittedFilenames` |
| 2084 | plate setup | `hide_errors git_ensure_gitignore_entry "$REPO_ROOT" ".plate/plate-log.txt"` | `git_lib.ensureGitignoreEntry` |
| 3239 | repo-root resolve | `hide_errors git_get_repo_root "$CWD"` | `git_lib.getGitRepoRoot` |
| 3324 | repo-root resolve | `hide_errors git_get_repo_root "$CWD"` | `git_lib.getGitRepoRoot` |
| 3568 | diagnostic block | `hide_errors git_get_branch_name "$CWD"` | `git_lib.getGitBranchNameOrFail` |
| 3569 | diagnostic block | `hide_errors git_get_recent_commits "$CWD"` | `git_lib.getGitRecentCommitHashes` |
| 3570 | diagnostic block | `hide_errors git_get_uncommitted "$CWD"` | `git_lib.getGitUncommittedFilenames` |

No call sites of `git_tests` exist outside its own definition.
