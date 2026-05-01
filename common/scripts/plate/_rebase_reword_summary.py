#!/usr/bin/env python3
"""_rebase_reword_summary.py — dual-role git editor script for the
`rewriteBranchTipSummary` rebase pipeline.

Two roles selected by argv[1]:

  sequence   — invoked as GIT_SEQUENCE_EDITOR. Rewrites the rebase-todo
               file to mark every commit `reword` so each one stops for
               message editing.

  message    — invoked as GIT_EDITOR. Rewrites COMMIT_EDITMSG depending
               on whether the current commit is the original tip:
                 - tip:     strip any existing `convo-summary:` trailer,
                            append the new one (collapsed to a single line).
                 - non-tip: only strip `convo-summary:` if present.
               Other trailers (convo-id, convo-name, parent-branch) are
               preserved as-is.

Determining "current commit" during message edit: read
`.git/rebase-merge/stopped-sha` (or `.git/rebase-merge/orig-head` for the
top of the rebase). Git writes `stopped-sha` to the file at the start of
each `reword` step.

Args (passed via env-set command before `git rebase -i` runs):
  message --tip-sha <sha> --new-summary-file <path> [--git-dir <path>]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _collapse(text: str) -> str:
    """Git trailers are single-line by spec. Collapse whitespace to one space."""
    return " ".join(text.split())


def _strip_summary_trailer(message: str) -> str:
    """Remove every `convo-summary: ...` line from the message."""
    return "\n".join(
        line for line in message.splitlines()
        if not line.lstrip().lower().startswith("convo-summary:")
    )


def _append_summary_trailer(message: str, summary: str) -> str:
    """Insert `convo-summary: <summary>` at the end of the existing
    trailer block. Must come BEFORE git's `# comment` lines (which it
    appends to COMMIT_EDITMSG during interactive rebase) — otherwise
    git strips the comments and our new trailer ends up in its own
    paragraph, breaking trailer-block contiguity for `git interpret-
    trailers`.

    Strategy: split the message into (content_lines_before_first_comment,
    comment_lines). Strip trailing blank lines from content. Append the
    new trailer. Re-attach the comment block (preserved verbatim).
    """
    lines = message.splitlines()
    first_comment_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("#")),
        len(lines),
    )
    content = lines[:first_comment_idx]
    comments = lines[first_comment_idx:]

    # Strip trailing blanks from content so the new trailer is
    # contiguous with the existing trailer paragraph.
    while content and content[-1].strip() == "":
        content.pop()
    content.append(f"convo-summary: {_collapse(summary)}")

    rebuilt = "\n".join(content)
    if comments:
        rebuilt += "\n\n" + "\n".join(comments)
    if not rebuilt.endswith("\n"):
        rebuilt += "\n"
    return rebuilt


def _is_tip_commit(commit_editmsg_text: str) -> bool:
    """Detect whether the current reword step is the last one.

    Git's interactive rebase appends a comment block to COMMIT_EDITMSG
    that includes either "Next command to do" (more steps remain) or
    "No commands remaining." (this is the tip). That marker is more
    reliable than reading `<git_dir>/rebase-merge/stopped-sha`, which
    git does NOT write during a `reword` step.
    """
    return "No commands remaining." in commit_editmsg_text


def _do_sequence(todo_path: Path) -> int:
    text = todo_path.read_text()
    new_lines = []
    for line in text.splitlines():
        if line.startswith("pick "):
            new_lines.append("reword " + line[len("pick "):])
        else:
            new_lines.append(line)
    todo_path.write_text("\n".join(new_lines) + "\n")
    return 0


def _do_message(commit_msg_path: Path, tip_sha: str, summary_file: Path,
                git_dir: Path) -> int:
    original = commit_msg_path.read_text()
    stripped = _strip_summary_trailer(original)
    on_tip = _is_tip_commit(original)
    if on_tip:
        summary = summary_file.read_text()
        new = _append_summary_trailer(stripped, summary)
    else:
        new = stripped
        if not new.endswith("\n"):
            new += "\n"
    commit_msg_path.write_text(new)
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("usage: _rebase_reword_summary.py {sequence|message} ...", file=sys.stderr)
        return 2
    role, rest = argv[0], argv[1:]

    if role == "sequence":
        # Last positional arg is the rebase-todo file path.
        if not rest:
            print("sequence: missing rebase-todo path", file=sys.stderr)
            return 2
        return _do_sequence(Path(rest[-1]))

    if role == "message":
        # Parse --tip-sha + --new-summary-file out of rest. The very last
        # positional (not consumed by flags) is COMMIT_EDITMSG, supplied
        # by git when it invokes GIT_EDITOR.
        parser = argparse.ArgumentParser()
        parser.add_argument("--tip-sha", required=True)
        parser.add_argument("--new-summary-file", required=True)
        parser.add_argument("--git-dir", required=True)
        parser.add_argument("commit_msg_path")
        ns = parser.parse_args(rest)
        return _do_message(
            Path(ns.commit_msg_path),
            ns.tip_sha,
            Path(ns.new_summary_file),
            Path(ns.git_dir),
        )

    print(f"unknown role {role!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
