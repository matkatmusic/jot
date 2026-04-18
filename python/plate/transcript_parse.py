#!/usr/bin/env python3
"""JSONL transcript parser with parentUuid-based dedup (§12).

"Consecutive user messages" means consecutive AFTER filtering to user-type
records only — not adjacent raw .jsonl lines. Tool calls, system messages,
and assistant responses between two user messages do not break the
"consecutive" relationship.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Iterator

def is_user_message(rec: dict) -> bool:
    """Check if a transcript record is a user message."""
    return (
        rec.get("type") == "user"
        or rec.get("role") == "user"
        or rec.get("message", {}).get("role") == "user"
    )

def deduped_user_turns(path: Path) -> Iterator[dict]:
    """Yield deduplicated user turns from a .jsonl transcript.

    For each parentUuid, only the LAST user message is kept.
    Earlier messages with the same parentUuid were cancelled/superseded.
    """
    pending: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not is_user_message(rec):
            continue
        if pending and rec.get("parentUuid") == pending.get("parentUuid"):
            # Same parent → this supersedes the pending message
            pending = rec
            continue
        if pending:
            yield pending
        pending = rec
    if pending:
        yield pending

def extract_recent_turns(path: Path, n: int = 50) -> list[dict]:
    """Return the last N deduplicated user turns."""
    turns = list(deduped_user_turns(path))
    return turns[-n:]

def extract_errors(path: Path, since_ts: str | None = None, max_count: int = 10) -> list[str]:
    """Extract error messages from transcript since a given timestamp.

    Scans both user messages (pasted errors) and tool results (runtime errors).
    Returns up to max_count most recent errors.
    """
    errors: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Skip if before the cutoff timestamp
        if since_ts and rec.get("timestamp", "") < since_ts:
            continue
        # Check for error patterns in content
        content = ""
        if isinstance(rec.get("message"), dict):
            content = rec["message"].get("content", "")
        elif isinstance(rec.get("content"), str):
            content = rec["content"]
        if not isinstance(content, str):
            content = json.dumps(content)
        # Heuristic: lines containing known error keywords
        if any(kw in content for kw in ("Error:", "error:", "ERROR", "FAIL", "failed", "panic:", "Traceback")):
            # Truncate to first 200 chars
            errors.append(content[:200])
    return errors[-max_count:]

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: transcript_parse.py <dedup|errors|recent> <path> [args...]", file=sys.stderr)
        sys.exit(1)
    cmd, path = sys.argv[1], Path(sys.argv[2])
    if cmd == "dedup":
        for rec in deduped_user_turns(path):
            print(json.dumps(rec))
    elif cmd == "recent":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        for rec in extract_recent_turns(path, n):
            print(json.dumps(rec))
    elif cmd == "errors":
        since = sys.argv[3] if len(sys.argv) > 3 else None
        for err in extract_errors(path, since):
            print(err)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
