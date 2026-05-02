"""Run a subprocess with combined stdout+stderr; uniform error reporting.

Spec:
- Run argv as a subprocess, capturing combined stdout+stderr.
- Missing program (FileNotFoundError) -> exit code 127, errno-style msg as output.
- exit != 0: write `[<caller>] command <argv-quoted> failed: <output>` to stderr.
- exit == 0 with output: write `<output>\\n` to stdout.
- exit == 0 with no output: silent.
- Returns the underlying exit code.

Migrated from common/scripts/invoke_command.sh per MIGRATION_TO_PYTHON.md.
The bash original used `${FUNCNAME[1]}` for the caller name (bash reflection)
and `$*` for the argv render (loses original quoting). The Python port takes
the caller name as an explicit argument (the bash shim still captures
`${FUNCNAME[1]}` and passes it through) and uses `shlex.join` for the argv
render (shell-safe, copy-pasteable from logs).
"""
from __future__ import annotations

import shlex
import subprocess
import sys


def invokeCommand(caller: str, argv: list[str]) -> int:
    """Run argv with combined stream capture; emit output or caller-tagged error.

    Args:
        caller: identifier for the calling context, used in the error prefix.
        argv:   the command to run, as a list of strings.

    Returns:
        The subprocess exit code, or 127 if argv[0] is not on PATH.
    """
    try:
        completed = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # combine into stdout
            text=True,
            check=False,
        )
        rc = completed.returncode
        output = (completed.stdout or "").rstrip("\n")
    except FileNotFoundError as exc:
        rc, output = 127, str(exc)

    if rc != 0:
        print(
            f"[{caller}] command {shlex.join(argv)} failed: {output}",
            file=sys.stderr,
        )
    elif output:
        print(output, file=sys.stdout)
    return rc
