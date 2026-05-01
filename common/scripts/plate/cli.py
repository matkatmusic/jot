#!/usr/bin/env python3
"""cli.py — single argv entry point for the /plate slash command.

Invoked by skills/plate/scripts/plate.sh:
    python3 -m common.scripts.plate.cli <variant> [args...]

Or directly:
    python3 common/scripts/plate/cli.py <variant> [args...]

Variants and their argv contracts:
    push    <convo_id> <transcript_path> <cwd>
    done    <repo>
    drop    <repo>
    trash   <repo> [--clean-wt]
    recycle <repo>
    next    <repo>                  # list mode
    next    <repo> <index>          # jump mode (index is raw string;
                                    # validation lives in plate_lib)
    show    <repo>                  # stub — returns "TODO"

Contract with the bash wrapper:
    - On success (incl. soft no-ops like "no plate to drop"): print the
      user-facing message to stdout, exit 0.
    - On uncaught exceptions: let Python's default handler print the
      traceback to stderr and exit non-zero. The bash ERR trap catches
      this and converts it to `emit_block "plate crashed..."` for the
      user.

The return value of every plate_* function is the literal text the user
sees in the Claude conversation (the bash wrapper passes it straight
through `emit_block` with no machine-formatting prefix).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# plate_lib lives in skills/plate/tests/sequence/helpers.py for now —
# pragmatic v1 (proper move + split is a follow-up). Inject that path
# so we can `import helpers as plate_lib`.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLATE_LIB_DIR = _REPO_ROOT / "skills" / "plate" / "tests" / "sequence"
if str(_PLATE_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_PLATE_LIB_DIR))

import helpers as plate_lib  # noqa: E402


def generatePlateSummary(transcript_path: Path) -> Optional[str]:
    """Stub for the ~400-word convo summary generator.

    Roadmap item 3 will fire a background tmux agent that reads the
    transcript and produces a structured summary, then strips the
    convo-summary trailer from earlier plate commits. Until then,
    plate_push receives None and skips the trailer.
    """
    return None


def _cmd_push(argv: list[str]) -> str:
    """push <convo_id> <transcript_path> <cwd>"""
    if len(argv) != 3:
        return "plate: usage: push <convo_id> <transcript_path> <cwd>"
    convo_id, transcript_path, cwd = argv
    repo = Path(cwd)

    tp = Path(transcript_path) if transcript_path else None
    convo_name = plate_lib.extractConvoNameFromTranscript(tp) if tp else None
    convo_summary = generatePlateSummary(tp) if tp else None

    sha = plate_lib.plate_push(
        repo,
        convo_id=convo_id or None,
        convo_name=convo_name,
        convo_summary=convo_summary,
    )
    if sha is None:
        return "plate: no changes to stack"
    branch = plate_lib.getCurrentBranchName(repo)
    return f"plate: pushed {sha[:8]} on {branch}-plate"


def _cmd_done(argv: list[str]) -> str:
    """done <repo>"""
    if len(argv) != 1:
        return "plate: usage: done <repo>"
    plate_lib.plate_done(Path(argv[0]))
    return "plate: replayed plate stack onto current branch"


def _cmd_drop(argv: list[str]) -> str:
    """drop <repo>"""
    if len(argv) != 1:
        return "plate: usage: drop <repo>"
    result = plate_lib.plate_drop(Path(argv[0]))
    if result is None:
        return "plate: no plate to drop"
    return f"plate: dropped (saved patch at {result})"


def _cmd_trash(argv: list[str]) -> str:
    """trash <repo> [--clean-wt]"""
    if len(argv) < 1 or len(argv) > 2:
        return "plate: usage: trash <repo> [--clean-wt]"
    repo = Path(argv[0])
    clean_wt = len(argv) == 2 and argv[1] == "--clean-wt"
    result = plate_lib.plate_trash(repo, clean_wt=clean_wt)
    if result is None:
        return "plate: no plate to trash"
    return f"plate: trashed (saved patch at {result})"


def _cmd_recycle(argv: list[str]) -> str:
    """recycle <repo>"""
    if len(argv) != 1:
        return "plate: usage: recycle <repo>"
    result = plate_lib.plate_recycle(Path(argv[0]))
    if result is None:
        return "plate: nothing to recycle"
    return f"plate: recycled session {result}"


def _cmd_next(argv: list[str]) -> str:
    """next <repo> [<index>]"""
    if len(argv) == 1:
        return plate_lib.plate_next(Path(argv[0]))
    if len(argv) == 2:
        # Pass argv index straight through — _plate_next_jump validates
        # numeric-only and range internally.
        return plate_lib.plate_next(Path(argv[0]), index=argv[1])
    return "plate: usage: next <repo> [<index>]"


def _cmd_show(argv: list[str]) -> str:
    """show <repo> — stub for now; render-tree design deferred."""
    return "TODO"


_DISPATCH = {
    "push":    _cmd_push,
    "done":    _cmd_done,
    "drop":    _cmd_drop,
    "trash":   _cmd_trash,
    "recycle": _cmd_recycle,
    "next":    _cmd_next,
    "show":    _cmd_show,
}


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point. Returns process exit code."""
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("plate: missing variant (push|done|drop|trash|recycle|next|show)")
        return 0
    variant, *rest = argv
    handler = _DISPATCH.get(variant)
    if handler is None:
        print(f"plate: unknown variant {variant!r}")
        return 0
    print(handler(rest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
