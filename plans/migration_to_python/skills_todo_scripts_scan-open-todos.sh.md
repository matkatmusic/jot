# Plan: Migrate `skills/todo/scripts/scan-open-todos.sh` to Python (TDD, spec-based)

## Context

Continuing the bash-to-Python migration tracked in `MIGRATION_TO_PYTHON.md`. Most `common/scripts/` files are now `[x]`. The other agent pane is working on `lock.sh`. Picking the next-easiest **`(standalone)`** item per the tracker's new migration-class annotations.

**Target: `skills/todo/scripts/scan-open-todos.sh`** (22 lines, `(standalone)`, sibling of jot's already-migrated version with a different spec).

This is a `(standalone)` script per the template — invoked as a subprocess by exactly one caller (`skills/todo/scripts/todo-launcher.sh:61`, via `hide_errors "$SCRIPTS_DIR/scan-open-todos.sh" "$REPO_ROOT"`). Migration follows template step 7: rewrite the `.sh` body as a one-line `exec python3 <module> "$@"` shim. Caller continues to invoke the `.sh` path; behavior identical.

**Prior art**: jot's `skills/jot/scripts/scan-open-todos.sh` was already migrated this way (see tracker line 99). Jot's lib lives at `common/scripts/jot/scan_open_todos_lib.py`. The todo version gets a parallel namespace at `common/scripts/todo/scan_open_todos_lib.py` to avoid module collisions.

## Spec (what `scan-open-todos.sh` must do, independent of bash)

**Inputs**

| Name | Type | Notes |
|---|---|---|
| `repo_root` | filesystem path (positional arg #1) | Required. The repo whose `Todos/` directory is scanned. |

**Behavior**

1. Compute `<repo_root>/Todos`.
2. If `<repo_root>/Todos/` does **not** exist as a directory: print exactly `(none)` to stdout and exit 0.
3. Glob `<repo_root>/Todos/*.md` (non-recursive — `Todos/done/foo.md` is NOT included because the glob doesn't descend; this is preserved behavior).
4. If the glob yields zero files: print exactly `(none)` to stdout and exit 0.
5. Otherwise: print each absolute path on its own line (one trailing `\n` per path), in **sorted-by-name** order, then exit 0.
6. Always exit 0 — this script never fails for environmental reasons (the caller wraps it in `hide_errors`, but it shouldn't need to).
7. Missing `repo_root` arg: argparse error, exit nonzero (acceptable — the bash version's `${1:?}` also exits nonzero on missing arg).

## Behavior changes vs the bash original (intentional)

| Behavior | Bash | Python | Why |
|---|---|---|---|
| Output ordering | Bash glob expansion order (locale-dependent, usually alphabetical) | Explicit `sorted()` | Deterministic across environments. |
| `nullglob` workaround | `shopt -s nullglob` to prevent glob-pattern leak | `Path.glob` returns `[]` naturally | Python doesn't need the workaround. |
| `found=0` counter pattern | Manual loop counter | Single `if not paths` check | Idiomatic. |
| Error on bad I/O (e.g. permission denied) | Silently logs and continues per `set -uo pipefail` (no `-e`) | Same — `Path.iterdir()`/`glob` exceptions for unreadable dirs are caught and treated as "no files" | Preserves "always exit 0" contract. |
| Path absolute-ness | Whatever `printf '%s\n' "$f"` produces (absolute iff `$REPO_ROOT` is absolute) | Explicit `Path.resolve()` to absolute | Matches the only known caller pattern (passes `$REPO_ROOT` which is absolute via `git rev-parse --show-toplevel`); explicit is safer. |

The "absolute path" change is a minor behavior shift: with the bash original, if the caller passed a relative `repo_root`, the printed paths would be relative. The Python port always emits absolute paths. This matches the only existing caller's intent and removes a latent class of confusion.

## Execution order (matches MIGRATION_TO_PYTHON.md template, TDD-strict)

### Step 0 (template): mark IN PROGRESS in tracker

Flip `- [p] skills/todo/scripts/scan-open-todos.sh — \`(standalone)\` 22 lines` to `[~]` in `MIGRATION_TO_PYTHON.md` so the parallel agent pane doesn't claim the same file.

### Step 0a — Numbered tasks

Tracked as new TaskList items #21-#24 (RED tests / lib GREEN / shim+CLI / verify).

### Step 1 — RED tests first

Create `tests/test_todo_scan_open_todos_lib.py` (note the `todo_` prefix to avoid collision with jot's `tests/test_scan_open_todos_lib.py`). Stub `common/scripts/todo/scan_open_todos_lib.py` with `def listOpenTodos(*args, **kwargs): raise NotImplementedError` so every test fails meaningfully.

Test cases:

- **Missing `Todos/` dir** -> returns `["(none)"]` (caller prints lines).
- **Empty `Todos/` dir (no .md files)** -> returns `["(none)"]`.
- **`Todos/` with one `*.md` file** -> returns `[absolute_path]`.
- **`Todos/` with multiple `*.md` files** -> returns sorted-by-name absolute paths.
- **`Todos/done/*.md` is NOT included** -> only top-level `*.md` files appear.
- **Non-`.md` files in `Todos/` are ignored** -> e.g. `foo.txt` doesn't appear.
- **Subdirectory inside `Todos/` is not listed** -> directories don't appear in output.
- **Sentinel value is exactly `(none)`** (not `"None"` or `""`).
- **Returned paths are absolute** even when `repo_root` is passed as a relative `Path`.

Run pytest; confirm all RED.

### Step 2 — Implement `common/scripts/todo/scan_open_todos_lib.py`

Create the dir + `__init__.py` (empty) + the lib. Public API:

```python
def listOpenTodos(repo_root: Path) -> list[str]:
    """Return absolute paths of <repo_root>/Todos/*.md, sorted, or ['(none)'].

    The caller (CLI) prints one line per element. Never raises for
    environmental reasons (missing dir, unreadable dir) - returns
    ['(none)'] in those cases.
    """
```

Implementation sketch:

```python
NONE_SENTINEL = "(none)"

def listOpenTodos(repo_root: Path) -> list[str]:
    todos = (Path(repo_root) / "Todos").resolve()
    try:
        if not todos.is_dir():
            return [NONE_SENTINEL]
        paths = sorted(p for p in todos.glob("*.md") if p.is_file())
    except OSError:
        return [NONE_SENTINEL]
    if not paths:
        return [NONE_SENTINEL]
    return [str(p) for p in paths]
```

### Step 3 — Run pytest until GREEN

Iterate on the lib until all Step 1 tests pass.

### Step 4 — Hard gate

Do not proceed to Step 5 until Step 3 is GREEN.

### Step 5 — Add `scan_open_todos_cli.py` + bash shim

5a. **NEW `common/scripts/todo/scan_open_todos_cli.py`** (~20 lines):

```python
import argparse, sys
from pathlib import Path
from scan_open_todos_lib import listOpenTodos

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scan_open_todos")
    parser.add_argument("repo_root", type=Path)
    args = parser.parse_args(argv)
    for line in listOpenTodos(args.repo_root):
        print(line)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Note: argparse exits nonzero for missing arg — matches `${1:?}` behavior.

5b. **MODIFY `skills/todo/scripts/scan-open-todos.sh`** to a one-line `exec` shim (template step 7 pattern, mirrors jot's already-migrated sibling):

```bash
#!/usr/bin/env bash
# scan-open-todos.sh - delegates to common/scripts/todo/scan_open_todos_cli.py.
# See that file for the open-todos contract. File kept executable so the
# existing caller (todo-launcher.sh:61) works unmodified; remove once the
# caller is itself migrated to Python (MIGRATION_TO_PYTHON.md).
exec python3 \
  "$(dirname "${BASH_SOURCE[0]}")/../../../common/scripts/todo/scan_open_todos_cli.py" \
  "$@"
```

5c. **NEW `tests/test_todo_scan_open_todos_cli.py`** (~5 tests): subprocess-driven CLI tests + bash-shim parity:
   - CLI: missing `Todos/` -> stdout is exactly `(none)\n`, exit 0.
   - CLI: populated `Todos/` -> stdout lists the absolute paths sorted, one per line, exit 0.
   - CLI: missing arg -> exit nonzero.
   - Shim: invoking the `.sh` produces identical output to invoking the CLI directly with the same arg.
   - Shim: shebang/exec works (file is executable).

### Step 6 — Hook entry point step (covered by Step 5b)

`scan-open-todos.sh` is `(standalone)` — invoked as `bash X.sh`. The `exec python3` shim IS the standalone-class migration; no separate hook-entry-point work needed.

### Step 7 — End-to-end verification + tracker update

7a. `pytest tests/test_todo_scan_open_todos_lib.py tests/test_todo_scan_open_todos_cli.py` -> all pass.
7b. `pytest` -> full repo passes; total = current count + new tests.
7c. `/tmp/todo_scan_smoke.sh`: build a tmp dir with mock `Todos/` contents and call the `.sh`; assert output matches spec for missing dir / empty dir / populated dir cases.
7d. **Live caller integration**: `bash skills/todo/scripts/todo-launcher.sh ...` (or simulate the caller's grep pattern by running the existing `skills/todo/tests/hook-writes-pending-test.sh`) to confirm the launcher's `OPEN_TODOS=$(... scan-open-todos.sh "$REPO_ROOT")` capture still produces the expected value.
7e. Flip `- [~] skills/todo/scripts/scan-open-todos.sh` to `- [x] skills/todo/scripts/scan-open-todos.sh — bash entry point now a one-line \`exec python3\` to common/scripts/todo/scan_open_todos_cli.py + scan_open_todos_lib.py`.

## Rollback

Single-file revert of `skills/todo/scripts/scan-open-todos.sh`. Pure-addition `.py` files and tests can stay.

## Cost of the shim

One Python interpreter spawn per call (~30-60 ms cold). The caller invokes this once per todo-launcher run; not in a loop. Acceptable. Disappears once `todo-launcher.sh` is itself migrated and calls `listOpenTodos` directly in-process.

## Out of scope (tracked in MIGRATION_TO_PYTHON.md)

- Migrating `todo-launcher.sh` (the caller).
- Deleting `scan-open-todos.sh` (only after the caller is itself migrated).
- Other todo skill scripts.
- Coordinating with the parallel pane working on `lock.sh` — different files; no conflict.
