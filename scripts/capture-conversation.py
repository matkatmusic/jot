#!/usr/bin/env python3
"""Extract recent conversation context from a Claude Code transcript.

Usage: capture-conversation.py <transcript_path>

Strategy: scan the transcript, then walk backwards to find the 5th-most-recent
real USER message and emit everything from that index forward (user +
assistant) in chronological order. Each message is wrapped in clearly
labeled ``=== ROLE (turn N) ===`` / ``=== END ROLE ===`` blocks so the
consumer can unambiguously tell where each turn starts and ends.

Skipped entirely (not counted as user, not included):
- Tool-only "user" entries (transcript rows whose content is just a
  ``tool_result`` and no user-typed text)
- Pure system-injected entries (``<task-notification>``,
  ``<user-prompt-submit-hook>``, or stand-alone ``<system-reminder>``
  blocks with no user-typed content alongside)

Real user messages are kept VERBATIM — system tags appended to a real user
turn are not stripped, because the surrounding context may matter.

The script never exits non-zero. On any failure it prints a fallback string
so the calling hook can keep going (the IDEA must survive enrichment errors).
"""
import json
import re
import sys

FALLBACK = "No conversation history available."
N_USER_MESSAGES = 5

# Patterns whose stand-alone presence marks a "user" entry as a pure system
# injection rather than real user input. If stripping every match leaves only
# whitespace, the entry is dropped (not counted, not emitted).
#
# NOTE: <command-*> tags are intentionally NOT in this list. A user entry
# made of nothing but <command-name>+<command-args> IS what the user typed
# (a slash command); we reconstruct it via _slash_command_text() instead of
# dropping it. The system's separate expansion entry is detected and skipped
# inside load_entries().
_SYSTEM_BLOCK_PATTERNS = [
    re.compile(r"<task-notification>.*?</task-notification>", re.DOTALL),
    re.compile(r"<user-prompt-submit-hook>.*?</user-prompt-submit-hook>", re.DOTALL),
    re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL),
]

_CMD_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
_CMD_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
_CMD_MSG_RE = re.compile(r"<command-message>.*?</command-message>", re.DOTALL)


def is_pure_system_injection(text: str) -> bool:
    """True if removing every system block leaves no real user-typed content."""
    stripped = text
    for pat in _SYSTEM_BLOCK_PATTERNS:
        stripped = pat.sub("", stripped)
    return not stripped.strip()


def _slash_command_text(text: str):
    """If `text` is a slash-command marker entry, return the reconstructed
    user-typed command (e.g. "/octo:debate review the plan"). Otherwise None.

    A marker entry is one whose only meaningful content is <command-name> and
    optionally <command-args> / <command-message>. This is what Claude Code
    records when the user invokes a /slash command — the system then injects
    a SEPARATE follow-up user entry containing the expanded skill body.
    """
    name_m = _CMD_NAME_RE.search(text)
    if not name_m:
        return None
    # Strip every command tag and confirm nothing else remains.
    leftover = _CMD_NAME_RE.sub("", text)
    leftover = _CMD_ARGS_RE.sub("", leftover)
    leftover = _CMD_MSG_RE.sub("", leftover)
    if leftover.strip():
        return None  # has other content — not a pure marker
    cmd = name_m.group(1).strip()
    args_m = _CMD_ARGS_RE.search(text)
    if args_m and args_m.group(1).strip():
        return f"{cmd} {args_m.group(1).strip()}"
    return cmd


def extract_text(content) -> str:
    """Convert a Claude Code message content (string or list of blocks) to plain text.

    Strings are returned stripped. Lists are walked and only ``type=="text"``
    blocks contribute. Tool-use / tool-result blocks are intentionally dropped.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                txt = c.get("text", "")
                if txt:
                    parts.append(txt)
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def load_entries(transcript_path: str):
    """Load (role, text) tuples from the transcript in chronological order.

    Two passes:

    1. ``raw`` collects every non-empty user/assistant row.
    2. ``entries`` walks ``raw`` and applies these transformations:
       - Pure system injections (task-notification, system-reminder, hook
         output) are dropped.
       - A slash-command marker entry (``<command-name>...`` only) is
         replaced with the reconstructed user-typed command, and the
         immediately-following user entry is skipped if present (it is the
         system's expansion of that command, not user-typed text).
       - Everything else passes through verbatim.
    """
    raw = []
    try:
        with open(transcript_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") not in ("user", "assistant"):
                    continue
                msg = entry.get("message", {}) or {}
                role = msg.get("role", entry.get("type", ""))
                text = extract_text(msg.get("content", ""))
                if not text:
                    continue
                raw.append((role, text))
    except (IOError, OSError):
        return None

    entries = []
    i = 0
    while i < len(raw):
        role, text = raw[i]
        if role == "user":
            cmd_text = _slash_command_text(text)
            if cmd_text is not None:
                # Real user-typed slash command. Keep it. Skip the next
                # entry IF it's a user-role expansion with no command tags
                # (the system-injected skill body that follows the marker).
                entries.append(("user", cmd_text))
                if i + 1 < len(raw):
                    next_role, next_text = raw[i + 1]
                    if next_role == "user" and "<command-" not in next_text:
                        i += 2
                        continue
                i += 1
                continue
            if is_pure_system_injection(text):
                i += 1
                continue
        entries.append((role, text))
        i += 1
    return entries


def find_start_index(entries, n_user: int) -> int:
    """Return the index of the n-th most recent user message, or 0 if fewer."""
    seen = 0
    for i in range(len(entries) - 1, -1, -1):
        if entries[i][0] == "user":
            seen += 1
            if seen == n_user:
                return i
    return 0


def format_window(entries) -> str:
    """Render selected entries with clearly delimited per-turn blocks."""
    lines = []
    user_turn = 0
    for role, text in entries:
        if role == "user":
            user_turn += 1
            header = f"=== USER (turn {user_turn}) ==="
            footer = "=== END USER ==="
        else:
            header = "=== ASSISTANT ==="
            footer = "=== END ASSISTANT ==="
        if lines:
            lines.append("")
        lines.append(header)
        lines.append(text)
        lines.append(footer)
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print(FALLBACK)
        return 0

    entries = load_entries(sys.argv[1])
    if entries is None or not entries:
        print(FALLBACK)
        return 0

    start = find_start_index(entries, N_USER_MESSAGES)
    print(format_window(entries[start:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
