#!/usr/bin/env python3
"""plate_cli.py — single argv entry point for the /plate slash command.

Invoked by skills/plate/scripts/plate.sh:
    python3 -m common.scripts.plate.plate_cli <variant> [args...]

Or directly:
    python3 common/scripts/plate/plate_cli.py <variant> [args...]

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

# plate_lib is a sibling module in this same directory; also expose the
# project root so dotted `common.scripts.X` imports resolve identically to
# pytest rootdir auto-discovery.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import plate_lib  # noqa: E402


def _cmd_push(argv: list[str]) -> str:
    """push <convo_id> <transcript_path> <cwd>"""
    if len(argv) != 3:
        return "plate: usage: push <convo_id> <transcript_path> <cwd>"
    convo_id, transcript_path, cwd = argv
    repo = Path(cwd)

    tp = Path(transcript_path) if transcript_path else None
    convo_name = plate_lib.plate_extractConvoNameFromTranscript(tp) if tp else None
    # convo_summary is left as None on push; a background agent (spawned
    # below) writes it to the new tip's trailer asynchronously via
    # `plate_cli.py set-plate-summary`.
    sha = plate_lib.plate_push(
        repo,
        convo_id=convo_id or None,
        convo_name=convo_name,
        convo_summary=None,
        # Pass transcript_path explicitly: the multi-agent extraction
        # path (`_plate_buildExtractedTree`) needs the actual transcript file
        # to scan for tool_use entries. Production passes a session UUID
        # as convo_id, NOT a path; without this, extraction falls back
        # to `Path(convo_id)` which doesn't exist, returns no edits, and
        # the resulting tree equals parent_tree → push silently no-ops.
        transcript_path=transcript_path or None,
    )
    if sha is None:
        return "plate: no changes to stack"
    branch = plate_lib.git_getCurrentBranchName(repo)
    # Fire-and-forget background summary agent. Returns immediately.
    # PLATE_SKIP_LAUNCH=1 short-circuits (used by tests).
    attach_hint: Optional[str] = None
    try:
        from spawn_summary_agent import spawn as _spawn_summary
        attach_hint = _spawn_summary(repo, branch, sha, transcript_path)
    except Exception:
        # Spawn failures must never block the user-facing push success.
        pass
    msg = f"plate: pushed {sha[:8]} on {branch}-plate"
    if attach_hint:
        # Keep the bare attach command on its own line, no prefix, so the
        # whole command is one selectable token in the user's terminal
        # (renderers wrap on whitespace; an inline prefix splits the cmd).
        msg += f"\n{attach_hint}"
    return msg


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
    """recycle <repo> [--list] [<session-dir-name>]"""
    if len(argv) < 1 or len(argv) > 2:
        return "plate: usage: recycle <repo> [--list|<session-dir-name>]"
    repo = Path(argv[0])
    if len(argv) == 2:
        if argv[1] == "--list":
            return plate_lib.plate_recycle_list(repo)
        result = plate_lib.plate_recycle(repo, session=argv[1])
    else:
        result = plate_lib.plate_recycle(repo)
    if result is None:
        return "plate: nothing to recycle"
    return f"plate: recycled tip {result[:8]}"


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


def _cmd_set_plate_summary(argv: list[str]) -> str:
    """set-plate-summary <repo> <branch> <summary-file>

    Invoked by the per-invocation SessionEnd hook of the spawned
    summary agent (plate-summary-stop.sh). Reads the agent's output
    file and writes its content as the convo-summary trailer on the
    tip of <branch>-plate, replacing the placeholder commit subject
    with the agent's subject (line 1 of the payload).

    Routes through `plate_lib.plate_regenerateTipSummary`, which uses
    `git commit-tree` directly. The legacy `plate_rewriteBranchTipSummary`
    rebase-and-worktree path was leaking orphan worktrees and
    corrupting trailer blocks in production; the commit-tree path
    avoids both failure modes.
    """
    if len(argv) != 3:
        return "plate: usage: set-plate-summary <repo> <branch> <summary-file>"
    repo, branch, summary_file = Path(argv[0]), argv[1], Path(argv[2])
    summary_text = summary_file.read_text()
    new_tip = plate_lib.plate_regenerateTipSummary(
        repo,
        branch,
        prior_summary="",  # unused — agent already produced summary_text
        agent_callable=lambda _prior: summary_text,
    )
    return f"plate: summary written ({new_tip[:8]} on {branch}-plate)"


_DISPATCH = {
    "push":               _cmd_push,
    "done":               _cmd_done,
    "drop":               _cmd_drop,
    "trash":              _cmd_trash,
    "recycle":            _cmd_recycle,
    "next":               _cmd_next,
    "show":               _cmd_show,
    "set-plate-summary":  _cmd_set_plate_summary,
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
