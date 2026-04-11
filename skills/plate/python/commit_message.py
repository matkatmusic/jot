#!/usr/bin/env python3
"""Format a plate's commit message per §7.3."""
import json, sys

def format_commit_message(plate: dict) -> str:
    lines = [f"[plate] {plate.get('summary_action', 'untitled plate')}"]
    goal = plate.get("summary_goal", "")
    if goal:
        lines.append(f"\nGoal: {goal}")
    hyp = plate.get("hypothesis", "")
    if hyp:
        hedge = plate.get("hypothesis_hedge", {})
        conf = hedge.get("confidence", "")
        reason = hedge.get("reason", "")
        lines.append(f"\nHypothesis: {hyp}")
        if conf:
            lines.append(f"  (confidence: {conf}; reason: {reason})")
    errors = plate.get("errors", [])
    if errors:
        lines.append("\nErrors encountered during this plate:")
        for e in errors:
            lines.append(f"  - {e}")
    lines.append(f"\nplate-id: {plate.get('plate_id', '')}")
    lines.append(f"pushed-at: {plate.get('pushed_at', '')}")
    return "\n".join(lines)

if __name__ == "__main__":
    plate = json.loads(sys.stdin.read())
    print(format_commit_message(plate))
