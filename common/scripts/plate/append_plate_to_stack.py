#!/usr/bin/env python3
"""Append a new plate to an instance JSON stack[].

Creates the instance if it doesn't exist yet.

Env vars:
  CONVO_ID      - conversation ID
  CWD           - working directory
  BRANCH        - git branch name
  PLATE_ID      - plate identifier
  HEAD_SHA       - HEAD commit SHA at push time
  STASH_SHA      - stash commit SHA
  ALL_FILES      - newline-separated list of changed files
  INSTANCE_FILE  - path to the instance JSON file
  PYTHON_DIR     - path to the python directory (for instance_rw import)
"""
import json
import os
import sys
from datetime import datetime, timezone

if __name__ == '__main__':
    sys.path.insert(0, os.environ['PYTHON_DIR'])
    from instance_rw import load, atomic_write, new_instance, new_plate
    from pathlib import Path

    path = Path(os.environ['INSTANCE_FILE'])
    data = load(path)
    if not data:
        data = new_instance(os.environ['CONVO_ID'], os.environ['CWD'], os.environ['BRANCH'])

    plate = new_plate(
        os.environ['PLATE_ID'],
        os.environ['HEAD_SHA'],
        os.environ['STASH_SHA'],
        os.environ['BRANCH'],
    )
    plate['files'] = [f for f in os.environ.get('ALL_FILES', '').strip().split('\n') if f]
    data.setdefault('stack', []).append(plate)
    data['last_touched'] = datetime.now(timezone.utc).isoformat()
    data['cwd'] = os.environ['CWD']

    atomic_write(path, data)
