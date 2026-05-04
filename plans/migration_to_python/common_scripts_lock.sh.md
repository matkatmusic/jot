# Migrate `common/scripts/lock.sh` to Python

## Source

- File: `common/scripts/lock.sh`
- Class: `(sourced)` — sourced via `. lock.sh` so callers use its functions; never invoked as a subprocess on the hot path.
- Size: ~80 lines bash (two public funcs `lock_acquire` / `lock_release`, plus an in-file `lock_tests` self-check).
- Position in dependency graph: leaf utility. Sources only `silencers.sh` (for `hide_errors`). Sourced by:
  - `skills/jot/scripts/jot-state-lib.sh` (sourced by jot-launcher / jot-state writers)
  - `skills/todo/scripts/todo-launcher.sh` (entry-point)
  - `skills/plate/scripts/archive/push.sh` (archived; verify dead before plan completes)
  - Documented (not executed) in `skills/plate/IMPLEMENTATION.md` and `skills/plate/tests/test-push-smoke.sh` references.
- Locking primitive: **`mkdir`-based** (atomic per POSIX; chosen because macOS lacks `flock(1)`). No fcntl, no lockfile library, no PID file.

## Behavior spec

Two public functions plus stale-sweep policy. Exit codes are load-bearing: callers branch on them.

### `lock_acquire <lock_dir> [timeout_seconds=10] [stale_after_seconds=60]`

1. Polls `mkdir "$lock_dir"` in a 50ms loop until success or timeout.
2. `mkdir` is the atomic primitive: exactly one process across the host wins on any POSIX FS (incl. macOS APFS, Linux ext4/btrfs/zfs). No NFS guarantee — unused on networked FS.
3. Stale-lock sweep: each iteration, if `$lock_dir` exists and its mtime is `>= stale_after_seconds` old, `rmdir` it and `continue` (retry the `mkdir` race immediately).
4. mtime read is platform-portable: tries BSD `stat -f %m` first (macOS), falls back to GNU `stat -c %Y` (Linux); on both failing, sets `lock_mtime=$now` (treats as fresh — fail-safe, never sweeps).
5. Timeout: `max = timeout * 20` iterations of 50ms each. On exhaustion, prints `[lock] lock_acquire: timed out after Ns on '<dir>'` to stderr and returns 1.
6. Returns 0 on success.
7. Errors from `mkdir` / `stat` / `rmdir` are silenced via `hide_errors` (no raw redirects per project rules).

### `lock_release <lock_dir>`

1. Calls `rmdir "$lock_dir"` (silenced).
2. Returns the `rmdir` exit code: 0 on success, non-zero if the dir didn't exist or wasn't empty.
3. Idempotency note: caller code in jot/todo treats non-zero as "lock was already gone or never held" and does not retry; Python module must preserve same exit semantics.

### `lock_tests` (in-file harness)

Manual smoke runner. Six assertions: fresh acquire / contended timeout / release / re-acquire / release-nonexistent-fails / stale-sweep. Migrated equivalent lives in pytest, not in the library.

### Concurrency / race-condition contract preserved by Python rewrite

- **Mutual exclusion**: `os.mkdir` raises `FileExistsError` atomically; only one of N concurrent callers wins. Same guarantee as bash `mkdir`.
- **Stale sweep race**: between "detect age >= threshold" and `rmdir`, a different process may have already swept and reacquired. `rmdir` of a now-fresh dir would corrupt the held lock. Mitigation: re-`stat` immediately before `rmdir`, or accept the bash version's existing window (it has the same race; preserving parity is acceptable since stale_after=60s makes the window vanishingly rare). **Test must document chosen behavior.**
- **mtime resolution**: 1s on most FS. `stale_after_seconds` minimum effectively 2s.
- **Process death mid-hold**: lock dir persists; next acquirer sweeps after `stale_after_seconds`. PID-in-lockfile alternative was explicitly rejected upstream (mkdir-only is simpler and macOS-portable).

## Target Python module path

- Library: `common/scripts/lock_lib.py`
- CLI dispatcher: `common/scripts/lock_cli.py` (argparse: `acquire DIR [--timeout N] [--stale-after N]`, `release DIR`, exit codes mirror bash)
- Bash shim: `common/scripts/lock.sh` becomes a thin file defining `lock_acquire` and `lock_release` shell functions that `exec` `python3 .../lock_cli.py …` so existing `source` callers keep working unchanged.

### Library choice: stdlib `os.mkdir` (no `fcntl.flock`, no `filelock` package)

**Recommendation: stdlib only.** Rationale:

1. **Behavioral parity is a hard requirement.** Callers depend on directory existence + mtime as the lock state. Switching to `fcntl.flock` (advisory, fd-scoped, vanishes on process exit) or `filelock` (lockfile + fcntl) changes the on-disk artifact and breaks the stale-sweep contract that callers and operators rely on.
2. **macOS portability.** `fcntl.flock` works on macOS but stale detection becomes process-liveness-based, not mtime-based — different semantics, different failure modes.
3. **No new runtime deps.** `filelock` would add a third-party dep for a leaf utility; project trend (per MIGRATION_TO_PYTHON principles) is stdlib-first.
4. **One-to-one bash translation.** `os.mkdir` raises `FileExistsError` (EEXIST) atomically; `os.stat(...).st_mtime` replaces both `stat -f %m` and `stat -c %Y`; `os.rmdir` replaces `rmdir`. Map is exact.

Trade-off acknowledged: stdlib mkdir-locks share the same edge cases as bash (no automatic release on crash; relies on stale sweep). Accepted because parity with current production behavior outweighs theoretical robustness.

## Migration template steps

0. Create numbered TODO list (see end of doc).
1. Mark `[i]` in `MIGRATION_TO_PYTHON.md` (done before this plan).
2. Plan written here; mark `[p]`.
3. RED tests: `tests/test_lock_lib.py` (plain-English scenario comments first, all failing).
4. Mark `[~]`.
5. Implement `common/scripts/lock_lib.py` until pytest GREEN. Do **not** touch `lock.sh` yet.
6. Add `common/scripts/lock_cli.py` argparse dispatcher (since lock.sh is sourced, shim must preserve `lock_acquire` / `lock_release` callable function names).
7. Replace `lock.sh` body with bash function shims that call `python3 lock_cli.py acquire|release …` and forward exit codes.
8. End-to-end verify all callers (jot-state-lib, todo-launcher), run integration smokes, mark `[x]`.

## RED test scenarios (pytest)

File: `tests/test_lock_lib.py`. Each test starts as a plain-English scenario comment, then a failing assertion. Use `tmp_path` for lock dirs. Use `multiprocessing.Process` (not threads) for true concurrency; threads share GIL state and would not exercise the `os.mkdir` race.

Behavior scenarios (15):

1. `acquire_succeeds_on_fresh_path` — non-existent dir → `acquire(path)` returns 0, dir now exists.
2. `acquire_creates_only_the_leaf_dir` — parent must pre-exist; missing parent → returns 1 (mirrors `mkdir` without `-p`).
3. `release_succeeds_when_held` — after acquire, `release(path)` returns 0, dir removed.
4. `release_returns_nonzero_when_not_held` — `release(/nonexistent)` returns non-zero.
5. `reacquire_after_release_succeeds` — acquire → release → acquire → 0.
6. `second_acquire_times_out_when_held` — proc A holds, proc B `acquire(path, timeout=1)` returns 1 within ~1.0–1.3s.
7. `timeout_message_written_to_stderr` — on timeout, stderr matches `^\[lock\] lock_acquire: timed out after 1s on '.+'$`.
8. `concurrent_acquire_only_one_winner` — spawn N=8 processes racing on same path with timeout=5; assert exactly one returns 0, the rest return 1. Repeat across 5 trials to surface race.
9. `stale_lock_swept_when_older_than_threshold` — pre-create dir, set mtime to epoch via `os.utime`, call `acquire(path, timeout=2, stale_after=1)` → returns 0 (swept and acquired). Confirms portable mtime read replaces `stat -f %m` / `stat -c %Y`.
10. `fresh_lock_not_swept` — pre-create dir with current mtime, `acquire(path, timeout=1, stale_after=60)` → returns 1 (timed out, not swept).
11. `stale_sweep_race_does_not_corrupt_winner` — proc A holds fresh lock; proc B sees stale-but-actually-fresh path (force the rare race) → asserts B does not rmdir A's lock. Test documents whether implementation re-stats before rmdir or accepts parity-with-bash window; either is acceptable but must be explicit.
12. `mtime_unreadable_treated_as_fresh` — monkeypatch `os.stat` to raise OSError on the lock dir path → acquire times out (does not erroneously sweep). Mirrors `lock_mtime="$now"` fallback.
13. `polling_interval_is_50ms` — measure that contended-acquire loop sleeps approximately 50ms between attempts (assert iter count ≈ timeout*20 ± 20%). Prevents accidental tight-loop CPU regression.
14. `cli_acquire_release_roundtrip` — invoke `python3 lock_cli.py acquire DIR` from subprocess, then `release DIR`, assert exit codes 0/0 and dir lifecycle correct.
15. `bash_shim_preserves_function_names` — source the rewritten `lock.sh` in a bash subshell, assert `type lock_acquire` and `type lock_release` resolve, and that `lock_acquire /tmp/…/x 1` returns 0.

Total: **15 RED scenarios** (3 acquire-basic, 2 release-basic, 1 reacquire, 1 contention-timeout, 1 stderr, 1 concurrent-N, 3 stale-sweep, 1 mtime-fallback, 1 polling-interval, 2 shim/CLI parity).

## Implementation outline

`common/scripts/lock_lib.py`:

```python
#!/usr/bin/env python3
"""mkdir-based cross-platform locking. Mirrors common/scripts/lock.sh."""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

POLL_SECONDS = 0.05
DEFAULT_TIMEOUT = 10
DEFAULT_STALE_AFTER = 60


def _mtime_or_now(path: Path) -> float:
    """Portable replacement for `stat -f %m` / `stat -c %Y` with fail-safe."""
    try:
        return path.stat().st_mtime
    except OSError:
        return time.time()  # fail-safe: treat as fresh, never sweep


def acquire(lock_dir: str | os.PathLike,
            timeout: float = DEFAULT_TIMEOUT,
            stale_after: float = DEFAULT_STALE_AFTER) -> int:
    """Returns 0 on acquire, 1 on timeout. Stderr message on timeout."""
    p = Path(lock_dir)
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.mkdir(p)
            return 0
        except FileExistsError:
            pass
        except OSError:
            # parent missing or permission — bash mkdir would also fail.
            return 1
        # stale sweep
        if p.is_dir():
            age = time.time() - _mtime_or_now(p)
            if age >= stale_after:
                try:
                    os.rmdir(p)
                except OSError:
                    pass
                continue
        if time.monotonic() >= deadline:
            print(f"[lock] lock_acquire: timed out after {int(timeout)}s on '{p}'",
                  file=sys.stderr)
            return 1
        time.sleep(POLL_SECONDS)


def release(lock_dir: str | os.PathLike) -> int:
    """Returns 0 on success, 1 if dir didn't exist or wasn't empty."""
    try:
        os.rmdir(lock_dir)
        return 0
    except OSError:
        return 1
```

`common/scripts/lock_cli.py`:

```python
#!/usr/bin/env python3
import argparse, sys
from lock_lib import acquire, release, DEFAULT_TIMEOUT, DEFAULT_STALE_AFTER

def main() -> int:
    p = argparse.ArgumentParser(prog="lock_cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("acquire")
    a.add_argument("dir")
    a.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    a.add_argument("--stale-after", type=float, default=DEFAULT_STALE_AFTER)
    r = sub.add_parser("release")
    r.add_argument("dir")
    args = p.parse_args()
    if args.cmd == "acquire":
        return acquire(args.dir, args.timeout, args.stale_after)
    return release(args.dir)

if __name__ == "__main__":
    sys.exit(main())
```

## Shim (final `.sh` body)

`lock.sh` must remain source-able and expose `lock_acquire` / `lock_release` as bash functions (callers invoke them positionally with `$1` `$2` `$3`). Body:

```bash
#!/bin/bash
# lock.sh - bash shim over lock_cli.py. Preserves source-able function names.
_LOCK_PY="$(dirname "${BASH_SOURCE[0]}")/lock_cli.py"

lock_acquire() {
  local dir="$1"
  local timeout="${2:-10}"
  local stale_after="${3:-60}"
  python3 "$_LOCK_PY" acquire "$dir" --timeout "$timeout" --stale-after "$stale_after"
}

lock_release() {
  python3 "$_LOCK_PY" release "$1"
}
```

(Note: the in-file `lock_tests` harness is dropped — pytest replaces it.)

## Risk callouts

1. **Per-call interpreter spawn.** Bash callers acquire/release on every state mutation. `python3` startup is ~30–80ms on macOS, vs <1ms for the bash funcs. Hot paths (jot-state writes, todo writes) will slow measurably. **Mitigation**: benchmark before merge; if regression > 100ms on common flows, in-process the lock by porting the caller to Python in the same migration wave (jot-state-lib is on the migration list).
2. **Stale-sweep race window.** Bash version has the race (stat → rmdir without re-stat). Python port should at minimum match parity; consider adding a re-stat-immediately-before-rmdir guard. Decision must be recorded in test #11.
3. **Exit-code shape change.** Bash `mkdir` failures (permission, missing parent) currently bubble through `hide_errors` and timeout-loop. Python returns 1 immediately on non-EEXIST `OSError`. This is a **semantic improvement** (faster failure) but technically a behavior change. Test #2 pins it.
4. **mtime fallback divergence.** Bash falls back to `now` only when both `stat -f %m` and `stat -c %Y` fail (effectively never). Python falls back on any `os.stat` failure. Equivalent in practice; documented in test #12.
5. **`hide_errors` removal.** Python uses `try/except` instead of stderr suppression; no raw redirects, satisfying the "no raw redirects" project rule.
6. **NFS / network FS unsupported.** Same as bash. Document in module docstring; do not promise correctness.
7. **Bash shim per-call overhead** (see #1) plus argparse import cost (~20ms). Consider replacing argparse with manual `sys.argv` parsing if benchmarking shows it matters.
8. **Archived caller (`skills/plate/scripts/archive/push.sh`).** Confirm it is truly dead before migration completes; if live, include in verification matrix.

## Verification

1. `pytest tests/test_lock_lib.py -v` → 15/15 GREEN.
2. Concurrency stress: run scenario #8 with N=32, 50 trials in CI; assert exactly-one-winner each trial.
3. Bash shim source-ability: `bash -c 'source common/scripts/lock.sh && lock_acquire /tmp/x.$$ 1 60 && lock_release /tmp/x.$$'` exits 0.
4. Caller integration:
   - `bash -c 'source skills/jot/scripts/jot-state-lib.sh; …'` exercise that uses lock — still GREEN.
   - `skills/todo/scripts/todo-launcher.sh` smoke — still launches; lock acquired and released.
5. Stale-sweep verification (rigorous, per repo rule): create lock dir, force mtime to `time.time() - 120`, call `acquire(timeout=2, stale_after=60)` → assert returns 0 AND that lock dir's new mtime is within 2s of `time.time()` (proves it was rmdir'd and recreated, not just inherited). A failing implementation would either time out or leave the old mtime — both detectable.
6. Benchmark: `hyperfine 'bash -c "source common/scripts/lock.sh && lock_acquire /tmp/b.$$ 1 60 && lock_release /tmp/b.$$"'` before vs after; record delta in commit body.
7. macOS + Linux CI matrix run (mtime read code path differs; both must pass).
8. Mark `[x]` in `MIGRATION_TO_PYTHON.md` only after steps 1–7 all pass.

## Numbered TODO list (template step 0)

1. Mark `common/scripts/lock.sh` as `[i]` in `MIGRATION_TO_PYTHON.md`.
2. Write this plan; mark `[p]`.
3. Create `tests/test_lock_lib.py` with the 15 RED scenarios as plain-English comments + failing asserts. Verify all 15 fail (no module yet).
4. Mark `[~]` in `MIGRATION_TO_PYTHON.md`.
5. Implement `common/scripts/lock_lib.py` (`acquire`, `release`, `_mtime_or_now`, constants).
6. Run `pytest tests/test_lock_lib.py -v`; iterate until 15/15 GREEN. Do NOT proceed until fully GREEN.
7. Implement `common/scripts/lock_cli.py` argparse dispatcher.
8. Re-run pytest including CLI scenarios #14 and shim scenario #15.
9. Replace `common/scripts/lock.sh` body with bash function shim that calls `lock_cli.py`.
10. Source-test the shim from a clean bash subshell; assert `lock_acquire` / `lock_release` resolve.
11. Run full caller integration: jot-state-lib path, todo-launcher path.
12. Run concurrency stress (scenario #8 at N=32, 50 trials).
13. Run benchmark vs original bash; record delta.
14. Run macOS + Linux CI matrix.
15. Confirm `skills/plate/scripts/archive/push.sh` is dead (or include in #11).
16. Mark `[x]` in `MIGRATION_TO_PYTHON.md`. Commit.

