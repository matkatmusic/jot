"""GREEN implementation of debate_findMatching (migrated from bash find_matching_debate).

Bash semantics preserved:
- Iterate Debates/*/ in repo_root.
- Skip dirs lacking topic.md.
- Match when `printf '%s\\n' "$topic"` is byte-equal to topic.md contents (cmp -s).
- Among matches, return the lexicographically-greatest dir basename (newest timestamp).
- Empty/no-match returns None (bash printed empty string; Python uses None for clarity).
"""
import sys
from pathlib import Path
from typing import Optional


def debate_findMatching(repo_root: str, topic: str) -> Optional[str]:
    """Return path to most-recent Debates/<ts>/ whose topic.md byte-equals `topic` + '\\n'.

    Args:
        repo_root: Path to repository root containing Debates/ subdir.
        topic: Topic text (function appends '\\n' before comparison, mirroring
               bash `printf '%s\\n'`).

    Returns:
        Absolute-style dir path string (no trailing slash), or None if no match.
    """
    debates = Path(repo_root) / "Debates"
    if not debates.is_dir():
        return None

    # Bash compared `printf '%s\n' "$topic"` to the file via cmp -s. Replicate
    # that by appending a single newline to the query before byte-compare.
    needle = (topic + "\n").encode("utf-8", errors="surrogateescape")

    best_ts = ""
    best_dir: Optional[str] = None
    for entry in debates.iterdir():
        if not entry.is_dir():
            continue
        topic_md = entry / "topic.md"
        if not topic_md.is_file():
            continue
        try:
            haystack = topic_md.read_bytes()
        except OSError:
            continue
        if haystack != needle:
            continue
        ts = entry.name
        # Lexicographic comparison matches bash `[[ "$ts" > "$match_ts" ]]`.
        if ts > best_ts:
            best_ts = ts
            best_dir = str(entry)

    return best_dir
