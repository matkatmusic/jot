# Migrate `common/scripts/permissions-seed.sh` to Python

## Source

`common/scripts/permissions-seed.sh` - sourced bash library exposing one
function, `permissions_seed`, that performs a three-state first-run / upgrade
seed of a user-editable permissions allowlist file (typically
`${CLAUDE_PLUGIN_DATA}/permissions.local.json`).

## Migration class

**`(sourced)` - Medium.** Every active caller uses `. permissions-seed.sh` to
import the `permissions_seed` shell function into its own scope. No caller
invokes the file as a subprocess. Per the tracker rules, the shim must be a
bash file that defines a `permissions_seed` function which delegates to a
`_cli.py` per template step 6.

## Callers (active)

1. `skills/jot/scripts/jot.sh:126`
2. `skills/todo/scripts/todo-launcher.sh:30`
3. `skills/debate/scripts/debate.sh:161`
4. `skills/plate/scripts/archive/push.sh:27`

Inactive / archived (do not adapt):
- `skills/debate/scripts/OLD_DISCARD/debate.sh:95` (dead)
- `plans/debate-resume.md:500` (planning doc)
- `plans/plate-status-2026-04-14.md` (planning doc)

Each caller sources the file then invokes `permissions_seed` with positional
args during plugin start-up to compose the allowlist consumed downstream by
spawned Claude agents (whose permissions are then expanded by
`common/scripts/jot/expand_permissions.py`).

## Interaction with `expand_permissions.py`

Two distinct stages, no shared code path:

1. `permissions_seed` (this file) - **on-disk seeding**: writes
   `permissions.local.json` and the sidecar `prior.sha` only when needed.
   Runs once per plugin start.
2. `expand_permissions.py` - **in-memory expansion**: reads the now-existing
   `permissions.local.json`, expands `${CWD}/${HOME}/${REPO_ROOT}` placeholders,
   and prints the allow array to stdout for the spawned worker.

Stage 1 is a precondition of stage 2: without seeding, the JSON read by
`expand_permissions.py` does not exist. The two helpers are intentionally
separate (per `plans/jot-generalizing-refactor.md` commit 8) and stay
separate after migration.

## Behavior spec - `permissions_seed`

Signature (preserved across migration):

```
permissions_seed <installed> <default> <default_sha_file> <prior_sha_file>
                 [log_file] [log_prefix]
```

Defaults:
- `log_file` = `""` (silent if empty)
- `log_prefix` = `"plugin"`

Decision tree (in order):

1. **Bundled default missing.** If `default` does not exist OR
   `default_sha_file` does not exist -> log
   `"bundled permissions default missing at <default> - cannot seed"`,
   return 0. No on-disk writes.
2. **Read current default sha.** `current_default_sha` = first whitespace-
   separated token of `default_sha_file`.
3. **Fresh install.** If `installed` does not exist -> `cp default installed`,
   write `current_default_sha\n` to `prior_sha_file`, log
   `"seeded <installed> from bundled default (sha=<current_default_sha>)"`,
   return 0.
4. **Compute installed sha.** `installed_sha` = `shasum -a 256 <installed>`
   first token (silent failure -> empty string).
5. **Compute prior sha.** `prior_sha` = first token of `prior_sha_file` if
   that file exists; else empty string.
6. **Already up-to-date.** If `installed_sha == current_default_sha` ->
   return 0 (no writes, no log).
7. **Untouched copy of an older default.** If `prior_sha` non-empty AND
   `installed_sha == prior_sha` -> `cp default installed`, write
   `current_default_sha\n` to `prior_sha_file`, log
   `"upgraded <installed> to new bundled default (was <prior_sha>, now <current_default_sha>)"`,
   return 0.
8. **User-edited file with a stale prior record.** If
   `prior_sha != current_default_sha` -> log
   `"<installed> is user-edited; bundled default updated - diff manually. installed_sha=<...> prior_sha=<...> current_default_sha=<...>"`,
   write `current_default_sha\n` to `prior_sha_file` (the installed file is
   NEVER overwritten), return 0.
9. **User-edited file with already-current prior record.** Implicit fall-through
   from step 8 when `prior_sha == current_default_sha`: no log, no writes,
   return 0.

Always returns 0. Never raises. Logging failures are swallowed
(`>> file 2>/dev/null || true`).

Log line format: `<ISO-8601 with offset> <log_prefix>: <message>` appended
to `log_file`.

## Target Python module path

`common/scripts/jot/permissions_seed.py`

Mirrors the existing `common/scripts/jot/expand_permissions.py` neighbour and
keeps the namespaced-python-helpers convention noted in `README.md`.

Public API:

```python
def permissions_seed(
    installed: Path,
    default: Path,
    default_sha_file: Path,
    prior_sha_file: Path,
    log_file: Path | None = None,
    log_prefix: str = "plugin",
) -> None: ...
```

CLI entry: `common/scripts/jot/permissions_seed_cli.py` parses positional
args matching the bash signature, calls `permissions_seed(...)`, exits 0
unconditionally (matching bash behavior).

## Shim (final `.sh` body)

`common/scripts/permissions-seed.sh` becomes a thin bash file that still works
when sourced and still exposes `permissions_seed` as a shell function:

```bash
#!/bin/bash
# Shim: delegates to common/scripts/jot/permissions_seed_cli.py.
# Preserves the sourced-function calling convention used by callers.

permissions_seed() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/jot/permissions_seed_cli.py" "$@"
}
```

Rationale: callers use `permissions_seed <args>` in their own scope; the
shim provides exactly that name. The Python CLI does all I/O (cp, sha
compute, sha-file write, optional log append).

## RED test scenarios (pytest)

Test file: `tests/test_permissions_seed.py`. Each test starts with a plain-
English scenario comment then a failing assertion. All filesystem state is
built under `tmp_path`; `subprocess`/`os.environ` are not needed because the
public API is a pure function operating on `Path` arguments. A small helper
`build_layout(tmp_path, *, default_text, default_sha=None, installed_text=None,
prior_sha=None)` constructs the four input paths and returns them.

Behavior coverage (12 scenarios):

1. `bundled_default_missing_returns_silently` - default file absent -> nothing
   created, return value is None, log file untouched.
2. `bundled_default_sha_file_missing_returns_silently` - sha sidecar absent ->
   no writes, no exception.
3. `fresh_install_copies_default_and_records_prior_sha` - installed absent ->
   installed file equals default text, prior_sha_file contains
   `current_default_sha\n`.
4. `fresh_install_logs_seed_message` - log_file given on fresh install ->
   log file contains `seeded <installed> from bundled default (sha=...)`.
5. `installed_sha_equals_current_default_is_noop` - installed == default
   bytes -> no writes (mtime unchanged), no log lines.
6. `untouched_old_default_is_upgraded` - installed_sha == prior_sha and
   prior_sha != current_default_sha -> installed overwritten with new default,
   prior_sha_file rewritten, upgrade log emitted.
7. `user_edited_file_with_stale_prior_is_left_alone_and_logged` - installed
   bytes differ from default and from prior -> installed file bytes preserved,
   prior_sha_file rewritten to current_default_sha, user-edited log emitted.
8. `user_edited_file_is_never_overwritten_even_after_log` - assert installed
   bytes byte-for-byte equal pre-call snapshot in scenario 7.
9. `user_edited_with_current_prior_record_is_silent` - installed differs from
   default but prior_sha already equals current_default_sha -> no log line
   appended, no file mutated.
10. `silent_when_log_file_arg_omitted` - scenario 3 with log_file=None ->
    no log file path is created or touched.
11. `log_file_directory_missing_does_not_raise` - log_file points into a
    non-existent directory -> call still completes, return None (matches
    bash `|| true`).
12. `log_prefix_default_is_plugin_when_omitted` - log line contains
    ` plugin: ` between timestamp and message.

CLI-shim coverage (3 scenarios) in same file:

13. `cli_invokes_permissions_seed_with_positional_args` - invoke
    `permissions_seed_cli.py` via `subprocess.run` with all 6 args; assert
    same on-disk effect as direct call.
14. `cli_omits_optional_log_args` - only 4 positional args -> no log file
    created.
15. `cli_exits_zero_when_default_missing` - exit code 0 when bundled default
    missing (matches bash return 0).

## Risk callouts

1. **Sourced-function contract.** Callers expect a *shell function* named
   `permissions_seed`. The shim must define this function, not just `exec`.
   Replacing the file with a one-line `exec python3` shim (the standalone
   pattern) would silently break every caller because sourcing such a file
   would either run python at source-time or do nothing useful.
2. **Subprocess overhead.** Each call now spawns `python3`. Acceptable: each
   caller invokes `permissions_seed` exactly once at start-up, never in a
   loop.
3. **Timestamp format.** Bash uses `date -Iseconds`. Python must emit an
   equivalent ISO-8601-with-offset string. Use
   `datetime.datetime.now().astimezone().isoformat(timespec="seconds")` and
   verify the format in a test.
4. **`shasum` vs `hashlib.sha256`.** Bash piped through `shasum -a 256 |
   awk '{print $1}'`. Python must compute
   `hashlib.sha256(file.read_bytes()).hexdigest()` to match exactly. RED
   test 6 asserts an upgrade triggered by sha equality.
5. **Silent log-write failure.** Bash swallows append failures. Python must
   wrap the log append in `try/except OSError: pass` to preserve scenario 11.
6. **Sha sidecar parsing.** Bash uses `awk '{print $1}'` on `default_sha_file`
   and `prior_sha_file`, tolerating optional trailing data (e.g. `<sha>
   <filename>` from `shasum -a 256 file > sha`). Python must split on
   whitespace and take token zero, not assume the file is the bare hex string.
7. **`$BASH_SOURCE` resolution in shim.** `dirname "${BASH_SOURCE[0]}"` must
   resolve to `common/scripts/`. Confirm by sourcing the shim from each of
   the four caller scripts in the verification phase.
8. **No on-disk mutation when default missing.** Scenarios 1 and 2 must not
   create the prior_sha_file. A naive port that always writes the sha would
   regress this.

## Verification plan

1. `pytest tests/test_permissions_seed.py -v` -> GREEN (all 15 scenarios).
2. End-to-end source check, per caller:
   - `bash -c '. common/scripts/permissions-seed.sh; type permissions_seed'`
     must print `permissions_seed is a function`.
3. End-to-end seed check (fresh install simulation, isolated tmp dir):

```
TMP=$(mktemp -d)
echo '{"permissions":{"allow":[]}}' > "$TMP/default.json"
shasum -a 256 "$TMP/default.json" > "$TMP/default.sha"
bash -c '. common/scripts/permissions-seed.sh; permissions_seed \
  "$1/installed.json" "$1/default.json" "$1/default.sha" "$1/prior.sha" \
  "$1/log.txt" test' _ "$TMP"
diff "$TMP/installed.json" "$TMP/default.json"   # must be empty
test -s "$TMP/prior.sha"                          # must be non-empty
grep -q 'seeded ' "$TMP/log.txt"                  # log line written
```

4. End-to-end upgrade check: pre-populate `installed.json` with bytes
   matching `prior.sha`, then change `default.json` and `default.sha`, run
   `permissions_seed`, assert installed bytes now match new default and
   `upgraded` log line appears.
5. End-to-end user-edit check: pre-populate `installed.json` with custom
   bytes whose sha differs from prior; run; assert installed bytes UNCHANGED
   byte-for-byte and `is user-edited` log line appears.
6. Smoke each real caller in dev install:
   - `bash skills/todo/scripts/todo-launcher.sh < /dev/null` (with a stub
     pending file) - must not error before the function call returns.
   - `echo '{}' | bash skills/jot/scripts/jot.sh` - must reach Phase 2.
   - `echo '{}' | bash skills/debate/scripts/debate.sh` - must reach the
     post-source code path.
7. Diff timestamps `installed.json` and `prior.sha` between two consecutive
   no-op runs (scenario 5 equivalent) - neither file's mtime should change.

A failing verification looks like: any scenario above producing a different
on-disk state than the bash original; or `type permissions_seed` returning
non-zero in step 2.

## Migration template steps (TODO)

0. **Confirm tracker state.** Verify `MIGRATION_TO_PYTHON.md` line for
   `common/scripts/permissions-seed.sh` is still `[ ]`. Annotate migration
   class `(sourced)` if missing.
1. **Mark `[i]`.** Flip the four tracker rows to `[i]` (lines 105, 130, 245,
   355) before any code lands.
2. **Land this plan; mark `[p]`.** Commit this file at
   `plans/migration_to_python/common_scripts_permissions-seed.sh.md` and
   flip tracker rows to `[p]`.
3. **Write RED tests.** Create `tests/test_permissions_seed.py` containing
   the 15 scenarios above. Run `pytest tests/test_permissions_seed.py -v`
   and confirm RED (all fail with `ModuleNotFoundError` or `AttributeError`
   referencing `permissions_seed`).
4. **Mark `[~]`.** Flip tracker rows to `[~]`.
5. **Implement Python module + CLI.** Create
   `common/scripts/jot/permissions_seed.py` (pure function) and
   `common/scripts/jot/permissions_seed_cli.py` (positional-args entry).
   Match the behavior spec section above exactly. No reads from
   `os.environ`. No prints to stdout. All errors swallowed per scenarios
   1, 2, 11.
6. **Run pytest GREEN.** `pytest tests/test_permissions_seed.py -v` ->
   all 15 pass. Resolve any deltas before proceeding.
7. **Replace `.sh` body with sourced-function shim.** Overwrite
   `common/scripts/permissions-seed.sh` with the shim shown above. Keep
   the existing top-of-file header comment block intact (callers read it).
8. **Verify end-to-end and mark `[x]`.** Run every step in the Verification
   plan section. On full GREEN, flip the four tracker rows to `[x]`.

