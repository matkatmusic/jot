# Workspace temp file for migration of bash `jot_session_end` -> Python `jot_sessionEnd`.
# RELAXED_COVERAGE: no paired bash _tests; tests authored from intent + docstring.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def jot_sessionEnd(tmpdir_inv: str | None) -> int:
    """SessionEnd hook: wipe the per-invocation tmpdir at end of a jot claude session.

    Mirrors bash `jot_session_end` (jot-plugin-orchestrator.sh ~3399-3415).

    Safety guard: refuses to remove any path not matching the expected
    `/tmp/jot.*` or `/private/tmp/jot.*` patterns. Without this guard a
    misconfigured hook could wipe an arbitrary directory.

    Args:
        tmpdir_inv: absolute path to per-invocation tmpdir (e.g. /tmp/jot.abcXYZ).

    Returns:
        Exit code (always 0 — bash version `exit 0`s on both refusal and success).

    Side effects:
        Recursively deletes `tmpdir_inv` when it matches the safelist pattern.
        Writes a refusal message to stderr when the path does not match.
    """
    import re
    import shutil

    # Refuse missing/empty arg (bash treats unset $1 as empty string, falls through case).
    if not tmpdir_inv:
        print(
            f"[jot-session-end] refusing to rm unexpected path: {tmpdir_inv or ''}",
            file=sys.stderr,
        )
        return 0

    # Safety pattern: only /tmp/jot.* or /private/tmp/jot.* allowed.
    # Bash glob `/tmp/jot.*` matches paths starting with that literal prefix.
    if not re.match(r"^(/tmp/jot\.|/private/tmp/jot\.)", tmpdir_inv):
        print(
            f"[jot-session-end] refusing to rm unexpected path: {tmpdir_inv}",
            file=sys.stderr,
        )
        return 0

    # rm -rf semantics: ignore missing path, recursive, no error on nonexistent.
    shutil.rmtree(tmpdir_inv, ignore_errors=True)
    return 0
