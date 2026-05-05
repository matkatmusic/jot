"""Temp migration target for `archive_debate` -> `debate_archive`.

Bash source: scripts/jot-plugin-orchestrator.sh lines 2999-3015.
This file is the workspace artifact for the RED-YELLOW-GREEN loop and is
NOT imported by jot_plugin_orchestrator.py.

RELAXED_COVERAGE: no paired bash _tests existed; tests were authored from
the function body / intent rather than ported.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


# YELLOW intent (plain English):
#   Move all "intermediate" debate scratch files from DEBATE_DIR into
#   DEBATE_DIR/archive/. The bash glob list pins exactly which files count as
#   intermediate: context.md, synthesis_instructions.txt, r1_instructions_*.txt,
#   r1_*.md, r2_instructions_*.txt, r2_*.md, and orchestrator.log. The final
#   synthesis.md and primary inputs (topic.md, invoking_transcript.txt) are
#   intentionally excluded so they remain at the debate root. mkdir -p
#   semantics: a pre-existing archive/ directory is fine and its prior
#   contents are preserved.

# Move debate intermediate scratch files into DEBATE_DIR/archive/.
# Mirrors bash `archive_debate`: creates archive subdir (idempotent),
# then moves a fixed set of patterns. synthesis.md and topic.md are
# preserved at the debate root by exclusion (not in the pattern list).
def debate_archive(debate_dir: Path | str) -> None:
    debate_dir = Path(debate_dir)
    archive_dir = debate_dir / "archive"
    # mkdir -p "$DEBATE_DIR/archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Bash for-loop expands each literal path and each glob; literal paths
    # that don't exist are kept as-is by the shell, then filtered by `[ -f ]`.
    # We mirror that with explicit literal checks plus glob expansion.
    literals = (
        debate_dir / "context.md",
        debate_dir / "synthesis_instructions.txt",
    )
    glob_patterns = (
        "r1_instructions_*.txt",
        "r1_*.md",
        "r2_instructions_*.txt",
        "r2_*.md",
    )

    candidates: list[Path] = []
    candidates.extend(p for p in literals if p.is_file())
    for pattern in glob_patterns:
        candidates.extend(p for p in debate_dir.glob(pattern) if p.is_file())

    for src in candidates:
        # Move into archive_dir using the original filename. Path.replace
        # gives atomic same-filesystem rename semantics matching `mv`.
        src.replace(archive_dir / src.name)

    # Separate orchestrator.log clause in bash (handled outside the loop).
    log = debate_dir / "orchestrator.log"
    if log.is_file():
        log.replace(archive_dir / log.name)
