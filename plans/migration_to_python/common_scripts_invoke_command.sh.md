# `common/scripts/invoke_command.sh`: absorbed into callers

**Decision:** no Python module is created. The script is reclassified `[a]` in `MIGRATION_TO_PYTHON.md`.

## Why

`invoke_command.sh` exists because bash needs help to (a) run a command capturing both stdout and stderr in interleaved order, (b) shell-quote the original argv safely for an error message, and (c) translate exit conditions into a single return code. Python's `subprocess.run` does all of this natively. The wrapper adds nothing Python lacks; the only behavior beyond stdlib is a one-line formatted error log, which is a 5-line helper at most.

## What callers do instead

Direct `subprocess.run`:

```python
import subprocess

result = subprocess.run(
    argv,
    stderr=subprocess.STDOUT,
    stdout=subprocess.PIPE,
    text=True,
    check=False,
)
output = result.stdout.rstrip("\n")
```

`output` and `result.returncode` cover everything the bash function returned. `subprocess.run` already translates "child killed by signal N" to a negative `returncode`; callers that need the bash-style `128 + N` form do `code = rc if rc >= 0 else 128 - rc`. ENOENT raises `FileNotFoundError`; callers that want the bash-style return-127 behavior wrap with `try/except FileNotFoundError`. Neither convention is enforced repo-wide; pick what each caller needs.

## Logging the failure line

The bash function's only value-add over stdlib is an error log line of the form:

```
[<caller>] command '<shlex.join(argv)>' failed: <output>
```

If multiple Python callers want that exact format, add a small shared helper at `common/scripts/_proc_log.py`:

```python
import shlex, sys
def log_failed(caller: str, argv: list[str], output: str) -> None:
    sys.stderr.write(f"[{caller}] command '{shlex.join(argv)}' failed: {output}\n")
```

Callers that don't need the formatted line just log however they prefer. No central wrapper, no `tuple[int, str]` return convention to memorize.

## Bash callers

Two paths per caller (same as `[s]` rules in the philosophy section):

1. **Migrate-together.** When a bash caller migrates to Python, that change replaces its `invoke_command tmux ...` calls with direct `subprocess.run([...], stderr=STDOUT, ...)` and (optionally) `log_failed(...)` from the helper above. The `source .../invoke_command.sh` line is removed.
2. **Transitional shim.** If a bash caller is not migrating yet, replace `invoke_command.sh`'s body with a 2-line bash shim that defines `invoke_command` as a function wrapping `python3 -c '...'` directly invoking `subprocess.run`. Mark `invoke_command.sh` as `[s]` while the shim exists. The shim does not import any module from this repo; it inlines the subprocess call.

## Deletion criteria

`git rm common/scripts/invoke_command.sh` when no caller (Python or bash) references it. Tracker entry flips from `[a]` to `[x]` in the same change.

## Current callers (verify before deletion)

- `common/scripts/tmux.sh` (bash, on migration list; ~20 call sites of `invoke_command tmux ...`)
- `skills/jot/scripts/jot-state-lib.sh` (bash, on migration list)
- `skills/jot/scripts/jot-stop.sh` (transitive via jot-state-lib)
- `skills/jot/scripts/jot.sh` (bash; copies the file into `$TMPDIR_INV`)
- `skills/debate/scripts/debate-tmux-orchestrator.sh` (bash)
- `skills/todo/scripts/todo-stop.sh` (bash)
- `skills/todo/scripts/todo-launcher.sh` (bash; copies the file into `$TMPDIR_INV`)

Dead / archived (ignore): `skills/debate/tests/archive/test.sh`, `skills/debate/scripts/OLD_DISCARD/debate-tmux-orchestrator.sh`.

Doc-only references (update prose at deletion time): `CHANGELOG.md`, `README.md`, `CODING_RULES.md`, `common/scripts/USAGE.md`.

## Tests

No `tests/test_invoke_command_lib.py`. Each caller's own test suite covers its subprocess usage. If the `_proc_log.log_failed` helper is added, write a minimal `tests/test_proc_log.py` covering the format string only.
