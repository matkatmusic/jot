# Migrate `scripts/jot-plugin-orchestrator.sh` to Python

## Source

- File: `scripts/jot-plugin-orchestrator.sh`
- Class: `(entry-point)` (called by hooks/hooks.json; never sourced)
- Size: 54 lines bash
- Position in dependency graph: top-level dispatcher; root of fan-out to seven sub-orchestrators

## Behavior spec

The script is an `UserPromptSubmit` (and `SessionEnd`) hook entry. Behavior:

1. Reads JSON from stdin into `INPUT`.
2. Extracts `.prompt` via `jq -r '.prompt // ""'` with stderr suppressed.
3. Strips leading whitespace from prompt so `"  /jot foo"` is treated as `"/jot foo"`.
4. If prompt starts with `/jot:` (Claude Code's plugin-namespaced form), rewrites:
   - the local `PROMPT` var: `/jot:foo` → `/foo`
   - the `INPUT` JSON's `.prompt` field to the rewritten value (so sub-orchestrators see the normalized form)
5. Dispatches to one of seven sub-orchestrator paths via case match on `<cmd>`, `<cmd> *`, `<cmd>\n*`:
   - `/jot` → `skills/jot/scripts/jot-orchestrator.sh`
   - `/plate` → `skills/plate/scripts/plate-orchestrator.sh`
   - `/debate` → `skills/debate/scripts/debate-orchestrator.sh`
   - `/debate-retry` → `skills/debate-retry/scripts/debate-retry-orchestrator.sh`
   - `/debate-abort` → `skills/debate-abort/scripts/debate-abort-orchestrator.sh`
   - `/todo` → `skills/todo/scripts/todo-orchestrator.sh`
   - `/todo-list` → `skills/todo-list/scripts/todo-list-orchestrator.sh`
6. Pipes the (possibly-rewritten) `INPUT` to the chosen sub-orchestrator via `bash <path>`.
7. Returns the sub-orchestrator's exit code (via `set -e` + pipefail-implicit propagation).
8. Unknown prompts: `exit 0` silently. Empty/missing `.prompt`: also pass-through.

`PLUGIN_ROOT` resolves from `$CLAUDE_PLUGIN_ROOT` else the parent of the script's directory.

## Migration template steps

1. Mark `[i]` in `MIGRATION_TO_PYTHON.md` (done before this plan).
2. Plan written here; mark `[p]`.
3. RED tests: `tests/test_jot_plugin_orchestrator.py`.
4. Mark `[~]`.
5. Implement single module: `scripts/jot-plugin-orchestrator.py`.
6. Run pytest GREEN.
7. Replace `.sh` body with one-line `exec python3` shim.
8. Verify end-to-end. Mark `[x]`.

## RED test scenarios (pytest)

Each begins as a plain-English scenario comment then a failing assertion. Sub-orchestrator stubs are written into `tmp_path/skills/<x>/scripts/<x>-orchestrator.sh` and record their stdin to a sibling file. The `route()` helper accepts `plugin_root` so tests can override.

- `empty_stdin_passes_through` — empty bytes → exit 0, no subprocess
- `missing_prompt_field_passes_through` — `{}` → exit 0
- `null_prompt_passes_through` — `{"prompt": null}` → exit 0
- `unknown_prompt_passes_through` — `{"prompt": "/unknown"}` → exit 0
- `slash_jot_dispatches_to_jot` — `{"prompt": "/jot foo"}` → invokes jot stub, full JSON forwarded
- `leading_whitespace_stripped` — `{"prompt": "  /plate --done"}` → plate stub gets full JSON
- `colon_form_normalized` — `{"prompt": "/jot:todo-list"}` → todo-list stub receives JSON whose `.prompt == "/todo-list"`
- `newline_form_dispatches` — `{"prompt": "/jot\nfoo"}` → jot stub
- `each_subcmd_routes_correctly` — parametrize over all seven prefixes
- `subprocess_exit_code_propagates` — stub exits 7 → script exits 7
- `session_end_path_dispatches_plate` — `{"prompt": "/plate"}` (matches the `SessionEnd` injection) → plate stub
- `malformed_json_treated_as_empty` — `not json` → exit 0, no subprocess

## Implementation outline

`scripts/jot-plugin-orchestrator.py`:

```python
#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path

ROUTES = {
    "/jot":          "skills/jot/scripts/jot-orchestrator.sh",
    "/plate":        "skills/plate/scripts/plate-orchestrator.sh",
    "/debate":       "skills/debate/scripts/debate-orchestrator.sh",
    "/debate-retry": "skills/debate-retry/scripts/debate-retry-orchestrator.sh",
    "/debate-abort": "skills/debate-abort/scripts/debate-abort-orchestrator.sh",
    "/todo":         "skills/todo/scripts/todo-orchestrator.sh",
    "/todo-list":    "skills/todo-list/scripts/todo-list-orchestrator.sh",
}

def normalize_prompt(input_json: str) -> tuple[str, str]:
    try:
        data = json.loads(input_json)
    except (ValueError, TypeError):
        return "", input_json
    prompt = data.get("prompt") or "" if isinstance(data, dict) else ""
    if not isinstance(prompt, str):
        return "", input_json
    prompt = prompt.lstrip()
    if prompt.startswith("/jot:"):
        prompt = "/" + prompt[len("/jot:"):]
        data["prompt"] = prompt
        return prompt, json.dumps(data)
    return prompt, input_json

def route(prompt: str, plugin_root: Path) -> Path | None:
    for cmd, rel in ROUTES.items():
        if prompt == cmd or prompt.startswith(cmd + " ") or prompt.startswith(cmd + "\n"):
            return plugin_root / rel
    return None

def main() -> int:
    plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
    raw = sys.stdin.read()
    prompt, forwarded = normalize_prompt(raw)
    target = route(prompt, plugin_root)
    if target is None:
        return 0
    result = subprocess.run(["bash", str(target)], input=forwarded, text=True, check=False)
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
```

## Shim (final `.sh` body)

```bash
#!/bin/bash
exec python3 "$(dirname "${BASH_SOURCE[0]}")/jot-plugin-orchestrator.py" "$@"
```

## Verification

1. `pytest tests/test_jot_plugin_orchestrator.py -v` → GREEN
2. `pytest skills/plate/tests/sequence/test_session_end_hook.py -v` → still GREEN
3. `bash tests/orchestrator-dispatch-todo-test.sh` → still passes
4. Smoke: `echo '{"prompt":"/jot:todo-list"}' | bash scripts/jot-plugin-orchestrator.sh` then assert the todo-list orchestrator received `.prompt == "/todo-list"`.
5. Failing-stub exit code propagation check.
