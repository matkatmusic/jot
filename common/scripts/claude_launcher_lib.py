"""Build the `claude` launch command + its settings.json file.

Spec:
- Write a JSON file at <settings_out> whose parsed structure is exactly
  {"permissions": {"allow": <parsed allow_json>}, "hooks": <parsed hooks_json_file>}.
- Return a shell command string that, when shell-evaluated, runs:
    claude --settings <settings_out> --add-dir <cwd> [--add-dir <add_dir>]...

Migrated from common/scripts/claude-launcher.sh per MIGRATION_TO_PYTHON.md.
The bash original used naive `'<path>'` quoting (broken on paths with `'`)
and raw heredoc string interpolation of JSON fragments. The Python port
uses shlex.join (correct quoting) and json.dumps (guaranteed valid JSON).
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path


def buildClaudeCmd(
    settings_out: Path,
    allow_json: str,
    hooks_json_file: Path,
    cwd: str,
    add_dirs: list[str],
) -> str:
    """Write settings_out and return the resolved `claude ...` command string.

    Args:
        settings_out:    path to write the generated settings JSON.
        allow_json:      JSON-array string of expanded permissions.
        hooks_json_file: path to a file whose contents are a JSON object
                         describing Claude Code hooks.
        cwd:             becomes the first --add-dir argument.
        add_dirs:        zero or more additional --add-dir paths, in order.

    Returns:
        A shell command string. The CLI prints it via print() to add the
        trailing newline; callers in-process can pass it to a shell as-is.

    Raises:
        json.JSONDecodeError: if allow_json or hooks_json_file is malformed.
        FileNotFoundError:    if hooks_json_file does not exist.
    """
    settings = {
        "permissions": {"allow": json.loads(allow_json)},
        "hooks": json.loads(hooks_json_file.read_text()),
    }
    settings_out.write_text(json.dumps(settings, indent=2) + "\n")

    argv = ["claude", "--settings", str(settings_out), "--add-dir", cwd]
    for d in add_dirs:
        argv += ["--add-dir", d]
    return shlex.join(argv)
