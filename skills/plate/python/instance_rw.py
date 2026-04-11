#!/usr/bin/env python3
"""Atomic JSON read/write/mutate for .plate/instances/*.json."""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1

def load(path: Path) -> dict[str, Any]:
    """Load instance JSON. Returns empty dict if file missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically: tmp + fsync + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise

def mutate(path: Path, fn: Callable[[dict[str, Any]], None]) -> None:
    """Load, apply fn in-place, write back atomically."""
    data = load(path)
    fn(data)
    atomic_write(path, data)

def new_instance(convo_id: str, cwd: str, branch: str) -> dict[str, Any]:
    """Create a blank instance dict with schema_version."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "convo_id": convo_id,
        "label": "",
        "label_source": "auto",
        "branch_at_registration": branch,
        "cwd": cwd,
        "created_at": now,
        "last_touched": now,
        "parent_ref": {"convo_id": None, "plate_id": None},
        "rolling_intent": {"text": "", "snapshot_at": None, "confidence": "low"},
        "drift_alert": {"pending": False, "message": "", "generated_at": None},
        "stack": [],
        "completed": [],
    }

def new_plate(plate_id: str, head_sha: str, stash_sha: str, branch: str) -> dict[str, Any]:
    """Create a blank plate entry for stack[]."""
    from datetime import datetime, timezone
    return {
        "plate_id": plate_id,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
        "state": "paused",
        "delegated_to": [],
        "push_time_head_sha": head_sha,
        "stash_sha": stash_sha,
        "branch": branch,
        "summary_action": "",
        "summary_goal": "",
        "summary_goal_hedge": {"confidence": "low", "reason": ""},
        "hypothesis": "",
        "hypothesis_hedge": {"confidence": "low", "reason": ""},
        "files": [],
        "errors": [],
        "completed_at": None,
        "commit_sha": None,
    }

# ── CLI interface for shell scripts ──────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1]
    path = Path(sys.argv[2])

    if cmd == "stack-oldest":
        for plate in load(path).get("stack", []):
            print(json.dumps(plate))
    elif cmd == "stack-newest":
        for plate in reversed(load(path).get("stack", [])):
            print(json.dumps(plate))
    elif cmd == "top":
        stack = load(path).get("stack", [])
        print(json.dumps(stack[-1] if stack else {}))
    elif cmd == "drop-top":
        def _pop(d: dict) -> None:
            if d.get("stack"):
                d["stack"].pop()
        mutate(path, _pop)
    elif cmd == "complete":
        plate_id, commit_sha, completed_at = sys.argv[3:6]
        def op(d: dict) -> None:
            stack = d.get("stack", [])
            idx = next(i for i, p in enumerate(stack) if p["plate_id"] == plate_id)
            plate = stack.pop(idx)
            plate["completed_at"] = completed_at
            plate["commit_sha"] = commit_sha
            d.setdefault("completed", []).append(plate)
        mutate(path, op)
    elif cmd == "touch":
        from datetime import datetime, timezone
        def _touch(d: dict) -> None:
            d["last_touched"] = datetime.now(timezone.utc).isoformat()
        mutate(path, _touch)
    elif cmd == "create-instance":
        # Args: path convo_id cwd branch
        convo_id, cwd_arg, branch = sys.argv[3], sys.argv[4], sys.argv[5]
        atomic_write(path, new_instance(convo_id, cwd_arg, branch))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
