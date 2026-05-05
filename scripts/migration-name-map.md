# Migration Name Map

Audit trail for the bash-to-Python migration of `scripts/jot-plugin-orchestrator.sh` -> `scripts/jot-plugin-orchestrator.py`. See `/Users/matkatmusicllc/.claude/plans/it-is-time-to-jolly-blossom.md` for the full plan.

## Naming Convention (binding)

`domain_behaviorUsingCamelCase`

- `domain` is a lowercase subsystem prefix: `tmux`, `git`, `jot`, `plate`, `debate`, `todo`, `todoList`, `hookjson`, `claude`, `terminal`, `shell`, etc.
- An underscore separates domain from behavior.
- `behaviorUsingCamelCase` is camelCase starting lowercase, expressing the action as a verb phrase.
- Entrypoint `*_main` functions keep `_main` (e.g. `jot_main`, `plate_main`).

## Tag Legend

- `MIGRATE` - translated to a real Python function via Red-Yellow-Green TDD.
- `ABSORBED` - bash-only idiom; not translated as a function; replaced inline at each call site.
- `IMPORT_FROM_GIT_LIB` - already exists in `common/scripts/git_lib.py`; orchestrator imports from there.
- `COVERED_BY_GIT_LIB_TESTS` - bash test already covered in `tests/test_git_lib.py`; not ported.
- `TEST` - pytest function in `scripts/test_monolith.py`; not in production surface; not in this map.
- `RELAXED_COVERAGE` - notes-column flag indicating the pytest test was authored from spec/docstring rather than ported from an existing bash `_tests` function (because none existed for that function).

## Map

| python_name | bash_name | signature | notes | date |
|---|---|---|---|---|
| ABSORBED | hide_output | `hide_output cmd...` | Replace each call with `subprocess.run(..., stdout=subprocess.DEVNULL)` | 2026-05-04 |
| ABSORBED | hide_errors | `hide_errors cmd...` | Replace each call with `subprocess.run(..., stderr=subprocess.DEVNULL)` or try/except | 2026-05-04 |
| ABSORBED | invoke_command | `invoke_command cmd...` | Replace each call with `subprocess.run(..., check=True, capture_output=True, text=True)` + try/except logging caller via `sys._getframe(1).f_code.co_name` | 2026-05-04 |
| hookjson_emitBlock | emit_block | `(reason: str) -> str` | RELAXED_COVERAGE; idiomatic json.dumps replaces jq+hand-roll fallback | 2026-05-04 |
| hookjson_installHint | _hookjson_install_hint | `(cmd: str) -> str` | RELAXED_COVERAGE; dict.get replaces bash case | 2026-05-04 |
| hookjson_checkRequirements | check_requirements | `(prefix: str, *cmds: str) -> None` | RELAXED_COVERAGE; uses shutil.which, sys.exit(0) on missing | 2026-05-04 |
| tmux_requireVersion | tmux_require_version | `(minimum: str) -> int` | RELAXED_COVERAGE; tuple compare on M.m parts | 2026-05-04 |
| tmux_setOption | tmux_set_option | `(*args: str) -> int` | RELAXED_COVERAGE; inlines invoke_command idiom (subprocess + caller logging) | 2026-05-04 |
