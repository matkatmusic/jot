#!/usr/bin/env python3
"""Workspace-temp module for debate_checkResumeFeasibility migration.

Mirrors bash check_resume_feasibility (jot-plugin-orchestrator.sh ~L2317-2355).
Permissive resume check derived from r1_instructions_<agent>.txt filenames.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Workspace-fallback import shim. The production module is jot_plugin_orchestrator;
# we don't need any production helpers here (pure filesystem inspection), so no
# fallback import is required. Path insert kept for convention/future callees.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass(frozen=True)
class ResumeFeasibility:
    """Result of a resume feasibility check.

    feasible           True iff debate can be resumed.
    updated_agents     Effective agent list. Includes 'disappeared' originals
                       whose r1_*.md AND r2_*.md outputs already exist (their
                       cached outputs will be reused at synthesis).
    unusable_agents    Originals that are unavailable AND lack complete outputs.
                       Empty when feasible is True.
    reason             Human-readable block message when not feasible, else "".
    """
    feasible: bool
    updated_agents: list[str]
    unusable_agents: list[str]
    reason: str


# debate_checkResumeFeasibility — port of bash check_resume_feasibility.
#
# Derives the original debate composition from r1_instructions_<agent>.txt
# filenames in `debate_dir`. For each original agent:
#   - If still in `available_agents`: keep, no change.
#   - If 'disappeared' (missing from `available_agents`) BUT both
#     r1_<agent>.md and r2_<agent>.md exist and are non-empty: re-add to the
#     effective agent list so synthesis includes the cached outputs.
#   - If 'disappeared' AND outputs are missing/empty: mark unusable.
# 'Appeared' agents (present in available_agents but not original) are accepted
# implicitly (they remain in the returned list) — instructions are built JIT.
#
# Returns a ResumeFeasibility. Caller decides whether to emit_block + exit;
# this function performs no I/O beyond filesystem inspection. RELAXED_COVERAGE.
def debate_checkResumeFeasibility(
    debate_dir: Path,
    available_agents: list[str],
) -> ResumeFeasibility:
    debate_dir = Path(debate_dir)

    # Discover original composition from r1_instructions_<agent>.txt files.
    original: list[str] = []
    if debate_dir.is_dir():
        for path in sorted(debate_dir.glob("r1_instructions_*.txt")):
            if not path.is_file():
                continue
            agent = path.stem[len("r1_instructions_"):]
            if agent:
                original.append(agent)

    # Work on a copy so caller's list is not mutated.
    updated = list(available_agents)
    unusable: list[str] = []

    for orig in original:
        if orig in updated:
            # Still available — nothing to do.
            continue
        # Disappeared — reusable iff both R1 and R2 outputs are non-empty.
        r1 = debate_dir / f"r1_{orig}.md"
        r2 = debate_dir / f"r2_{orig}.md"
        r1_ok = r1.is_file() and r1.stat().st_size > 0
        r2_ok = r2.is_file() and r2.stat().st_size > 0
        if r1_ok and r2_ok:
            updated.append(orig)
        else:
            unusable.append(orig)

    if unusable:
        joined = "".join(f" {a}" for a in unusable)
        reason = (
            "/debate: cannot resume, these original agents are unavailable "
            "and their outputs are incomplete:"
            f"{joined}. Fix credentials/quota and re-run '/debate <topic>', "
            "or '/debate-abort' to delete."
        )
        return ResumeFeasibility(
            feasible=False,
            updated_agents=updated,
            unusable_agents=unusable,
            reason=reason,
        )

    return ResumeFeasibility(
        feasible=True,
        updated_agents=updated,
        unusable_agents=[],
        reason="",
    )
