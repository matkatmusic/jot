#!/usr/bin/env python3
"""_rebase_reword_summary.py — dual-role git editor script for the
`plate_rewriteBranchTipSummary` rebase pipeline.

Two roles selected by argv[1]:

  sequence   — invoked as GIT_SEQUENCE_EDITOR. Rewrites the rebase-todo
               file to mark every commit `reword` so each one stops for
               message editing.

  message    — invoked as GIT_EDITOR. Rewrites COMMIT_EDITMSG depending
               on whether the current commit is the original tip:
                 - tip:     replace the subject line with the agent's
                            new subject (line 1 of <new-summary-file>),
                            strip any existing `convo-summary:` trailer,
                            and append the new one with the body part
                            (collapsed to a single line).
                 - non-tip: only strip `convo-summary:` if present.
                            Subject is preserved untouched.
               Other trailers (convo-id, convo-name, parent-branch) are
               preserved as-is on every commit.

`<new-summary-file>` format: agent writes a payload with
  Line 1: subject (≤50 chars)
  Line 2: blank
  Lines 3+: 5-section summary body
Split is on the first blank line.

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


def _format_trailer_body(text: str) -> str:
    """Format summary body for a multi-line git trailer value.

    Git trailers can span multiple lines if every line after the first
    starts with whitespace (RFC 822 / `git interpret-trailers` continuation
    rule). We preserve line breaks so section labels (`what:` `why:` `how:`
    `open questions:` `next steps:`) render on their own lines when the
    user runs `git log -1 --format='%(trailers)'`.

    `getGitCommitTrailers` reads with `unfold=true`, which collapses these
    continuation lines back to a single space-joined string for
    code paths that want the flat form (preserves the existing test
    contract).

    Trims leading/trailing blank lines. For empty body lines, emits a
    single space so git keeps treating the block as one trailer rather
    than ending it.
    """
    raw = [line.rstrip() for line in text.splitlines()]
    # Drop ALL blank lines (leading, trailing, AND interior). Git treats
    # whitespace-only lines as paragraph separators that terminate a
    # trailer block — so emitting `" "` for blank body lines produced
    # un-parseable trailers. Section labels still render on their own
    # lines because each label line is itself non-blank and gets
    # indented as a continuation line below.
    raw = [line for line in raw if line.strip()]
    if not raw:
        return ""
    first = raw[0].lstrip()
    rest = [" " + line.lstrip() for line in raw[1:]]
    return "\n".join([first] + rest)


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
    content.append(f"convo-summary: {_format_trailer_body(summary)}")

    rebuilt = "\n".join(content)
    if comments:
        rebuilt += "\n\n" + "\n".join(comments)
    if not rebuilt.endswith("\n"):
        rebuilt += "\n"
    return rebuilt


def _parse_payload(text: str) -> tuple[str, str]:
    """Split agent output into (subject, summary_body).

    Format: line 1 is the subject; the first blank line is the separator;
    everything after is the summary body.
    Tolerates missing blank line (treats whole content as subject + empty body)
    and trailing whitespace.
    """
    if not text.strip():
        return ("", "")
    lines = text.splitlines()
    subject = lines[0].strip()
    blank_idx = next(
        (i for i, line in enumerate(lines) if i > 0 and line.strip() == ""),
        None,
    )
    if blank_idx is None:
        return (subject, "")
    body = "\n".join(lines[blank_idx + 1:]).strip()
    return (subject, body)


def _replace_subject(message: str, new_subject: str) -> str:
    """Replace the first non-blank, non-comment line of the COMMIT_EDITMSG
    with `new_subject`. Subsequent lines (trailers, comment block, etc.)
    are preserved verbatim. Used only for the tip commit.

    Subject is hard-capped at 50 chars per the template spec; over-length
    input is truncated rather than rejected (rejection would dead-end the
    rebase mid-flight).
    """
    new_subject = new_subject.strip()
    if len(new_subject) > 50:
        new_subject = new_subject[:50].rstrip()
    if not new_subject:
        return message  # no replacement; keep original subject
    lines = message.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines[i] = new_subject
            break
    rebuilt = "\n".join(lines)
    if message.endswith("\n") and not rebuilt.endswith("\n"):
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
        # Tip commit: parse the agent's payload, replace subject, append
        # the body as the new convo-summary trailer. Single-line payloads
        # (no blank-line separator) are treated as body-only so callers
        # passing just summary text still land a trailer.
        subject, body = _parse_payload(summary_file.read_text())
        if subject and not body:
            body = subject
            subject = ""
        with_new_subject = _replace_subject(stripped, subject) if subject else stripped
        new = _append_summary_trailer(with_new_subject, body) if body else with_new_subject
        if not new.endswith("\n"):
            new += "\n"
    else:
        # Non-tip: only strip stale convo-summary. Subject stays as-is per spec.
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
