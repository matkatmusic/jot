# Lock Cluster Migration Summary (ABSORBED + TEST)

Source: `scripts/jot-plugin-orchestrator.sh`
Date: 2026-05-04

## Replacement idiom (canonical Python)

```python
from _tmp_FileLock import FileLock  # post-merge: from .filelock import FileLock

with FileLock(path, timeout=10.0):
    # critical section
    ...
```

`fcntl.flock` is auto-released on fd close / process death, so the bash
stale-lock sweep is no longer needed. `LockTimeout` (subclass of
`TimeoutError`) is raised when `timeout` elapses.

## PENDING markers -> replacement tags

| # | Bash function | PENDING line | Marker replacement |
|---|---|---|---|
| 1 | `lock_acquire` | 1604 | `# [ABSORBED -> with FileLock(path): ... @ 2026-05-04]` |
| 2 | `lock_release` | 1635 | `# [ABSORBED -> with FileLock(path): ... @ 2026-05-04]` |
| 3 | `lock_tests` | 1642 | `# [TEST -> test_acquire_succeeds_on_fresh_path, test_release_clears_acquired_state, test_reacquire_after_release, test_release_is_idempotent_when_not_held, test_competing_process_blocks_until_holder_releases, test_timeout_elapses_when_lock_is_held, test_lock_auto_released_when_holder_process_dies @ 2026-05-04]` |
| 4 | `jot_lock_acquire` | 1726 | `# [ABSORBED -> with FileLock(path): ... @ 2026-05-04]` |
| 5 | `jot_lock_release` | 1728 | `# [ABSORBED -> with FileLock(path): ... @ 2026-05-04]` |

## Name-map rows (4 ABSORBED entries)

```
| lock_acquire     | ABSORBED | replaced by `with FileLock(path, timeout=...)` context manager (fcntl.flock) |
| lock_release     | ABSORBED | paired with FileLock context manager exit; no standalone callable          |
| jot_lock_acquire | ABSORBED | thin alias of FileLock; callers use `with FileLock(path, timeout=...)`     |
| jot_lock_release | ABSORBED | paired with FileLock context manager exit; no standalone callable          |
```

## Call-site rewrite recipe

Bash:
```bash
jot_lock_acquire "$state_dir/queue.lock" 10 60 || return 1
jot_queue_pop_first "$state_dir"
jot_lock_release "$state_dir/queue.lock"
```

Python:
```python
from pathlib import Path
from .filelock import FileLock, LockTimeout

try:
    with FileLock(Path(state_dir) / "queue.lock", timeout=10.0):
        jot_queue_pop_first(state_dir)
except LockTimeout:
    return 1
```

## Files produced

- `_tmp_FileLock.py` — context manager module
- `_tmp_test_lock_tests.py` — 7 pytest cases (real multiprocessing, no mocks)
- `_tmp_lock_cluster_summary.md` — this document
