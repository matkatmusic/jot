#!/usr/bin/env python3
"""UserPromptSubmit / SessionEnd dispatcher.

Reads hook JSON from stdin, inspects `.prompt`, and delegates to the
sub-orchestrator bash script for /jot, /plate, /debate, /debate-retry,
/debate-abort, /todo, or /todo-list. Unknown prompts pass through silently
(exit 0).

Replaces scripts/jot-plugin-orchestrator.sh. The .sh body is a one-line
shim that exec's this module so hooks/hooks.json keeps working unchanged.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROUTES: dict[str, str] = {
    "/jot":          "skills/jot/scripts/jot-orchestrator.sh",
    "/plate":        "skills/plate/scripts/plate-orchestrator.sh",
    "/debate":       "skills/debate/scripts/debate-orchestrator.sh",
    "/debate-retry": "skills/debate-retry/scripts/debate-retry-orchestrator.sh",
    "/debate-abort": "skills/debate-abort/scripts/debate-abort-orchestrator.sh",
    "/todo":         "skills/todo/scripts/todo-orchestrator.sh",
    "/todo-list":    "skills/todo-list/scripts/todo-list-orchestrator.sh",
}

_JOT_NS_PREFIX = "/jot:"


def normalize_prompt(input_json: str) -> tuple[str, str]:
    """Extract and normalize the prompt; return (prompt, forwarded_json).

    Mirrors the bash dispatcher:
    - parse failures yield ("", input_json) — matches `hide_errors jq`
      semantic of swallowing errors and treating prompt as empty.
    - leading whitespace is stripped from the prompt.
    - "/jot:foo" is rewritten to "/foo" both in the returned prompt and in
      the JSON's .prompt field so sub-orchestrators see the normalized form.
    """
    try:
        data = json.loads(input_json) if input_json else None
    except (ValueError, TypeError):
        return "", input_json
    if not isinstance(data, dict):
        return "", input_json
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return "", input_json
    prompt = prompt.lstrip()
    if prompt.startswith(_JOT_NS_PREFIX):
        prompt = "/" + prompt[len(_JOT_NS_PREFIX):]
        data["prompt"] = prompt
        return prompt, json.dumps(data)
    return prompt, input_json


def route(prompt: str, plugin_root: Path) -> Path | None:
    """Resolve prompt to its sub-orchestrator path, or None for pass-through.

    Match logic mirrors bash case patterns: exact match, "<cmd> *", or
    "<cmd>\\n*". Iteration order is longest-first so /todo-list wins over
    /todo on the literal "/todo-list" prefix.
    """
    for cmd in sorted(ROUTES, key=len, reverse=True):
        if (
            prompt == cmd
            or prompt.startswith(cmd + " ")
            or prompt.startswith(cmd + "\n")
        ):
            return plugin_root / ROUTES[cmd]
    return None


def _resolve_plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def main() -> int:
    plugin_root = _resolve_plugin_root()
    raw = sys.stdin.read()
    prompt, forwarded = normalize_prompt(raw)
    target = route(prompt, plugin_root)
    if target is None:
        return 0
    result = subprocess.run(
        ["bash", str(target)],
        input=forwarded,
        text=True,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
