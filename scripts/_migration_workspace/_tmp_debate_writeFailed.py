"""Migration workspace stub for debate_writeFailed (write_failed bash port)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

# Ensure workspace dir is on sys.path for symmetric import in the test file.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def debate_writeFailed(
    debate_dir: Path,
    stage: str,
    reason: str,
    agents: Iterable[str],
    *,
    pane_capture: Callable[[str], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> Path:
    """Write a `FAILED.txt` marker into ``debate_dir`` describing a debate failure.

    Bash analogue: ``write_failed`` (jot-plugin-orchestrator.sh ~L2817-2841).

    Behavior (RELAXED_COVERAGE - reconstructed from bash intent):
      * Header lines: '# debate FAILED', blank, 'stage:', 'reason:', 'timestamp:' (ISO-8601), blank.
      * Section '## missing agents' followed by one '### <agent>' subsection per agent
        whose ``<stage>_<agent>.md`` output file is missing or empty in ``debate_dir``.
      * If a lock file ``.<stage>_<agent>.lock`` exists with line ``debate:<pane_id>``,
        ``pane_capture(pane_id)`` is invoked and its result is fenced in triple backticks.
        Else writes ``(no pane captured -- lock file missing or malformed)``.
      * Atomic publish: writes to a temp file in ``debate_dir`` then renames over
        ``FAILED.txt``, so a partial file is never observable. Overwrites prior FAILED.txt.
      * Returns the final FAILED.txt path.
    """
    debate_dir = Path(debate_dir)
    if now is None:
        now = lambda: datetime.now(timezone.utc).astimezone()
    timestamp = now().replace(microsecond=0).isoformat()

    lines: list[str] = [
        "# debate FAILED",
        "",
        f"stage: {stage}",
        f"reason: {reason}",
        f"timestamp: {timestamp}",
        "",
        "## missing agents",
    ]

    for agent in agents:
        out_path = debate_dir / f"{stage}_{agent}.md"
        # Skip agents that produced non-empty output (matches bash `[ -s ... ] && continue`).
        if out_path.exists() and out_path.stat().st_size > 0:
            continue
        lines.append("")
        lines.append(f"### {agent}")
        lock_path = debate_dir / f".{stage}_{agent}.lock"
        pane_id = ""
        if lock_path.exists():
            for raw in lock_path.read_text().splitlines():
                if raw.startswith("debate:"):
                    pane_id = raw[len("debate:"):].strip()
                    break
        if pane_id:
            lines.append("```")
            capture_text = ""
            if pane_capture is not None:
                try:
                    capture_text = pane_capture(pane_id) or ""
                except Exception:
                    capture_text = ""
            if not capture_text:
                capture_text = "(pane capture unavailable)"
            # Strip trailing newline so the closing fence sits on its own line.
            lines.append(capture_text.rstrip("\n"))
            lines.append("```")
        else:
            lines.append("(no pane captured -- lock file missing or malformed)")

    body = "\n".join(lines) + "\n"

    debate_dir.mkdir(parents=True, exist_ok=True)
    # Atomic write: tempfile in same dir, then rename onto FAILED.txt.
    import tempfile
    fd, tmp_name = tempfile.mkstemp(prefix=".FAILED.txt.", dir=str(debate_dir))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        final = debate_dir / "FAILED.txt"
        tmp_path.replace(final)
        return final
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
