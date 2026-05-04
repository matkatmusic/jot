# `common/scripts/lock.sh`: absorbed into callers

**Decision:** no Python module is created. The script is reclassified `[a]` in `MIGRATION_TO_PYTHON.md`.

## Why

`lock.sh` exists because bash has no atomic locking primitive on macOS (no `flock(1)` in the base system). It uses `mkdir`-as-mutex and a manual stale-lock sweep to compensate. Python has these primitives in stdlib. Porting the workaround verbatim would re-invent flaws Python does not have.

## What callers do instead

Each Python caller that needs locking uses stdlib directly:

```python
import fcntl

with open(lock_path, "w") as f:
    fcntl.flock(f, fcntl.LOCK_EX)   # blocks; or LOCK_EX | LOCK_NB for non-blocking
    try:
        ...                          # critical section
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
```

Or, if Windows portability ever matters, the `filelock` package (third-party, single dep). Default is stdlib `fcntl`.

POSIX `fcntl.flock` is advisory and fd-scoped: it auto-releases when the holding process exits or the fd is closed. This is strictly stronger than the bash mkdir-with-stale-sweep approach and removes the race window the bash version had between "detect stale" and "rmdir."

## Bash callers

Two paths per caller (same as `[s]` rules in the philosophy section):

1. **Migrate-together.** When a bash caller migrates to Python in its own change, that change replaces its `lock_acquire`/`lock_release` calls with `fcntl.flock` and removes the `source .../lock.sh` line.
2. **Transitional shim.** If a bash caller is not migrating yet, replace `common/scripts/lock.sh`'s body with a 2-line shim that defines `lock_acquire` and `lock_release` as bash functions wrapping `python3 -c 'import fcntl; ...'`. Mark `lock.sh` as `[s]` while the shim exists. The shim does not call any Python module from this repo; it goes straight to stdlib.

## Deletion criteria

`git rm common/scripts/lock.sh` when no caller (Python or bash) references it. Tracker entry flips from `[a]` to `[x]` in the same change.

## Current callers (verify before deletion)

- `skills/jot/scripts/jot-state-lib.sh` (bash, on migration list)
- `skills/todo/scripts/todo-launcher.sh` (bash, on migration list)
- `skills/plate/scripts/archive/push.sh` (verify dead)

Doc-only references (update prose at deletion time): `skills/plate/IMPLEMENTATION.md`, `skills/plate/tests/test-push-smoke.sh`.

## Tests

No `tests/test_lock_lib.py`. Each caller's own test suite covers its locking behavior end-to-end. If a caller's lock usage is non-trivial, that caller's plan adds the locking-specific tests there.
