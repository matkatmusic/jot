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

## Map

| python_name | bash_name | signature | notes | date |
|---|---|---|---|---|
