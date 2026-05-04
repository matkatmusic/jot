# Migrate `common/scripts/permissions-seed.sh` to Python

## Source

`common/scripts/permissions-seed.sh` is a sourced bash library exposing a single function, `permissions_seed`, that performs a three-state first-run / upgrade seed of a user-editable permissions allowlist file (typically `${CLAUDE_PLUGIN_DATA}/permissions.local.json`).

## Target

`common/scripts/permissions_seed_lib.py` (new module). No `_cli.py`. No surviving `.sh`. Callers import the module and call `permissions_seed(...)` directly.

## Function table

The spine of this plan. Every row gets a Python function with the same name, typed signature, declared return type, and stub body `print("TODO: <name>")`. Per-function notes follow each row inline.

| name | Python signature | return type | one-line behavior note |
|---|---|---|---|
| `permissions_seed` | `permissions_seed(installed: Path, default: Path, default_sha_file: Path, prior_sha_file: Path, log_file: Path \| None = None, log_prefix: str = "plugin") -> None` | `None` | Top-level entry. Runs the three-state decision tree. Mutates files. Returns nothing. |
| `_permseed_log` | `_permseed_log(log_file: Path \| None, log_prefix: str, message: str) -> None` | `None` | Append `<ISO-8601-with-offset> <prefix>: <message>\n` to `log_file`. No-op if `log_file` is `None`. Swallow `OSError`. |
| `_read_first_token` | `_read_first_token(path: Path) -> str` | `str` | Read `path`, return first whitespace-separated token of first line. Return `""` if file missing or unreadable. Replaces bash `awk '{print $1}'`. was: inline `awk` pipeline. |
| `_sha256_file` | `_sha256_file(path: Path) -> str` | `str` | Return `hashlib.sha256(path.read_bytes()).hexdigest()`. Return `""` on `OSError`. Replaces bash `shasum -a 256 ... \| awk '{print $1}'`. was: inline shell pipeline. |
| `_write_prior_sha` | `_write_prior_sha(prior_sha_file: Path, sha: str) -> None` | `None` | Write `f"{sha}\n"` to `prior_sha_file`. Replaces bash `printf '%s\n' "$sha" > "$prior_sha_file"`. was: inline `printf >`. |

Per-function notes:

- **`permissions_seed`.** Decision tree (preserved from bash, in order):
  1. If `default` missing OR `default_sha_file` missing -> log `"bundled permissions default missing at <default> - cannot seed"`; return. No on-disk writes.
  2. `current_default_sha = _read_first_token(default_sha_file)`.
  3. If `installed` missing -> `shutil.copyfile(default, installed)`; `_write_prior_sha(prior_sha_file, current_default_sha)`; log `"seeded <installed> from bundled default (sha=<current_default_sha>)"`; return.
  4. `installed_sha = _sha256_file(installed)`.
  5. `prior_sha = _read_first_token(prior_sha_file)` (returns `""` if absent).
  6. If `installed_sha == current_default_sha` -> return (no writes, no log).
  7. If `prior_sha` non-empty AND `installed_sha == prior_sha` -> `shutil.copyfile(default, installed)`; `_write_prior_sha(prior_sha_file, current_default_sha)`; log `"upgraded <installed> to new bundled default (was <prior_sha>, now <current_default_sha>)"`; return.
  8. If `prior_sha != current_default_sha` -> log `"<installed> is user-edited; bundled default updated - diff manually. installed_sha=<...> prior_sha=<...> current_default_sha=<...>"`; `_write_prior_sha(prior_sha_file, current_default_sha)`; return. Installed bytes NEVER overwritten.
  9. Implicit fall-through (`prior_sha == current_default_sha` and installed differs from both): no log, no write, return.

- **`_permseed_log`.** Timestamp via `datetime.datetime.now().astimezone().isoformat(timespec="seconds")` to match `date -Iseconds`. Open with `mode="a"`. Wrap in `try/except OSError: pass` to preserve bash `|| true`.

- **`_read_first_token`.** `try: text = path.read_text(); except OSError: return ""`. Then `tokens = text.split(); return tokens[0] if tokens else ""`. Tolerates `<sha>  <filename>` form emitted by `shasum -a 256 file > sha`.

- **`_sha256_file`.** `try: return hashlib.sha256(path.read_bytes()).hexdigest(); except OSError: return ""`. Return value must equal `shasum -a 256` output (lowercase hex, no prefix).

- **`_write_prior_sha`.** Use `path.write_text(f"{sha}\n")`. No directory creation; bash original assumed parent exists.

## Callers needing import-site updates

1. `skills/jot/scripts/jot.sh:126` (bash) - migrate this caller in same change OR install transitional shim per `MIGRATION_TO_PYTHON.md` philosophy.
2. `skills/todo/scripts/todo-launcher.sh:30` (bash) - same.
3. `skills/debate/scripts/debate.sh:161` (bash) - same.
4. `skills/plate/scripts/archive/push.sh:27` (bash) - same.

Inactive (do not adapt): `skills/debate/scripts/OLD_DISCARD/debate.sh`, `plans/debate-resume.md`, `plans/plate-status-2026-04-14.md`.

Each active bash caller currently does `. permissions-seed.sh` then calls `permissions_seed <args>`. Until each bash caller is itself migrated, the file `common/scripts/permissions-seed.sh` survives temporarily as a `[s]` transitional shim:

```bash
permissions_seed() {
  python3 -c 'from common.scripts.permissions_seed_lib import permissions_seed; import sys; from pathlib import Path; \
args=sys.argv[1:]; permissions_seed(Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3]), \
Path(args[4]) if len(args)>4 and args[4] else None, args[5] if len(args)>5 else "plugin")' "$@"
}
```

Delete the `.sh` once all four bash callers migrate to Python and import `permissions_seed_lib` directly.

## Interaction with `expand_permissions.py`

Two distinct stages, no shared code path:

1. `permissions_seed` (this module) - on-disk seeding. Writes `permissions.local.json` and the sidecar `prior.sha` only when needed. Runs once per plugin start.
2. `expand_permissions.py` - in-memory expansion. Reads the now-existing JSON, expands `${CWD}/${HOME}/${REPO_ROOT}` placeholders, prints the allow array.

Stage 1 is a precondition of stage 2. The two stay separate after migration.

## RED tests

Test file: `tests/test_permissions_seed_lib.py`. Fixture helper `build_layout(tmp_path, *, default_text, default_sha=None, installed_text=None, prior_sha=None) -> tuple[Path, Path, Path, Path]` constructs the four input paths.

All assertions hit return values or filesystem/log side effects. None capture stdout.

Behavior coverage:

1. `test_bundled_default_missing_returns_none_and_writes_nothing` - default absent -> `permissions_seed(...) is None`, `installed.exists() is False`, `prior_sha_file.exists() is False`.
2. `test_bundled_default_sha_file_missing_returns_none_and_writes_nothing` - sha sidecar absent -> same as #1.
3. `test_fresh_install_copies_default_bytes` - installed absent -> `installed.read_bytes() == default.read_bytes()`.
4. `test_fresh_install_records_current_default_sha` - `prior_sha_file.read_text() == f"{current_default_sha}\n"`.
5. `test_fresh_install_emits_seeded_log_line` - `log_file.read_text()` contains `"seeded "` and `current_default_sha`.
6. `test_installed_equals_default_is_total_noop` - capture mtimes pre-call; assert mtimes unchanged post-call AND `log_file.exists() is False`.
7. `test_untouched_old_default_is_upgraded` - `installed.read_bytes() == new_default.read_bytes()` and `prior_sha_file.read_text() == f"{new_default_sha}\n"`.
8. `test_upgrade_emits_upgraded_log_line` - log contains `"upgraded "` and both old and new sha values.
9. `test_user_edited_bytes_preserved_byte_for_byte` - snapshot `installed.read_bytes()` pre-call; assert equal post-call.
10. `test_user_edited_with_stale_prior_rewrites_prior_sha_only` - `prior_sha_file.read_text() == f"{current_default_sha}\n"`, installed bytes unchanged, log contains `"is user-edited"`.
11. `test_user_edited_with_current_prior_record_is_silent` - prior already equals current_default; assert no log file created, no file mutation.
12. `test_log_file_none_creates_no_log` - `log_file=None` on a fresh install path -> no extra files appear in `tmp_path`.
13. `test_log_file_directory_missing_does_not_raise` - `log_file=tmp_path/"nonexistent"/"log.txt"` -> call returns `None`, no exception.
14. `test_log_prefix_default_is_plugin` - log line matches regex `r" plugin: "` between timestamp and message.
15. `test_log_prefix_custom_appears_in_line` - pass `log_prefix="todo"` -> log line contains `" todo: "`.
16. `test_sha_sidecar_with_trailing_filename_parsed` - write `default_sha_file` as `"<sha>  default.json\n"`; assert `prior_sha_file.read_text()` equals `f"{sha}\n"` (proves first-token parse).
17. `test_returns_none_in_every_branch` - parametrize over each scenario; assert `permissions_seed(...) is None` every time.

## RED -> GREEN order (callees-first)

Per `RED_GREEN_TDD.md`: write all RED first, confirm RED, then implement bottom-up so each commit flips a small, named cluster.

Implementation order:

1. `_write_prior_sha` - flips tests #4, #7, #10, #16.
2. `_read_first_token` - flips #16 fully; partially unblocks #2, #4, #7.
3. `_sha256_file` - flips #6 (noop branch), unblocks #7 vs #10 distinction.
4. `_permseed_log` - flips #5, #8, #10, #13, #14, #15.
5. `permissions_seed` - flips remaining: #1, #2, #3, #6, #9, #11, #12, #17.

Commit per leaf or per small cluster. After each, run `pytest tests/test_permissions_seed_lib.py -v` and confirm new tests green, no prior tests regress.

## Migration template steps (TODO)

0. **Tracker `[i]`.** Flip `MIGRATION_TO_PYTHON.md` row for `common/scripts/permissions-seed.sh` to `[i]`.
1. **Inventory done.** Function table above.
2. **Scaffold.** Create `common/scripts/permissions_seed_lib.py` with all 5 functions from the table. Each body is `print(f"TODO: {name}")` and the declared return (`return None` or `return ""`) so signatures hold under static checkers.
3. **RED tests.** Create `tests/test_permissions_seed_lib.py` with all 17 scenarios. Run `pytest tests/test_permissions_seed_lib.py -v`. Every test must fail on assertion (not on import or signature mismatch). If any test errors on import, fix the scaffold, not the test.
4. **Confirm RED.** Capture pytest output showing 17/17 failing on assertion. Mark tracker `[~]`.
5. **GREEN, callees-first.** Implement the 5 bodies in the order above. After each body, run pytest and confirm the expected cluster flips green with zero regressions. Commit per body or per small cluster.
6. **Update bash callers.** For each of the four active bash callers, either (a) migrate the caller in this same change to Python and import `permissions_seed_lib` directly, or (b) replace `common/scripts/permissions-seed.sh` body with the transitional shim shown in the Callers section and mark the file `[s]`.
7. **Delete the `.sh`.** Once no bash caller remains, `git rm common/scripts/permissions-seed.sh`. Until then, the shim survives as `[s]`.
8. **Verify end-to-end.** Per `feedback_verify_before_commit.md`: pytest is necessary but not sufficient.
   - `pytest tests/test_permissions_seed_lib.py -v` -> 17/17 green.
   - Live integration: run a real plugin start (`echo '{}' | bash skills/jot/scripts/jot.sh` while shim is in place) and confirm `${CLAUDE_PLUGIN_DATA}/permissions.local.json` materializes with expected bytes and `prior.sha` sidecar.
   - Two-run mtime check: invoke twice in succession with installed already current; assert `installed` and `prior_sha_file` mtimes unchanged between runs (proves scenario #6 in vivo).
   - Upgrade simulation: pre-populate `installed` with bytes matching old `prior.sha`; bump `default` and `default.sha`; run; assert installed bytes equal new default and log contains `"upgraded "`.
   - User-edit simulation: pre-populate `installed` with custom bytes whose sha matches neither; run; assert installed bytes byte-for-byte unchanged and log contains `"is user-edited"`.
9. **Tracker `[x]`.** After live verification passes, flip the tracker row to `[x]` (or `[s]` if any bash caller still remains).

## Risk callouts

1. **Timestamp format parity.** Bash `date -Iseconds` emits e.g. `2026-05-04T01:40:12-07:00`. Python `datetime.now().astimezone().isoformat(timespec="seconds")` emits the same. Test #14 asserts the prefix shape implicitly via the `" plugin: "` separator; add an explicit format regex if needed.
2. **`shasum` vs `hashlib.sha256` parity.** `shasum -a 256 file` and `hashlib.sha256(file.read_bytes()).hexdigest()` agree on lowercase hex. Test #7 asserts upgrade triggered by sha equality across the two implementations.
3. **Silent log-write failure.** Bash swallows append failures. Python wraps the append in `try/except OSError: pass`. Test #13 enforces this.
4. **Sha sidecar parsing.** `_read_first_token` splits on whitespace and takes index 0; tolerates `<sha>  <filename>` form. Test #16 enforces this.
5. **No on-disk mutation when default missing.** Tests #1 and #2 assert `prior_sha_file.exists() is False` after the call, preventing a regression where a naive port writes the sha unconditionally.
6. **Installed never overwritten on user edit.** Test #9 snapshots bytes pre-call and compares post-call. This is the single most important invariant; bash currently guarantees it via the absence of any `cp` on the user-edit branch.
