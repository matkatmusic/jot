#!/usr/bin/env python3
"""Check and clear pending drift alert for an instance.

If a drift alert is pending, prints the message and clears the flag.
Exits silently if no alert or on any error.

Env vars:
  DRIFT_INSTANCE_FILE - path to the instance JSON file
  PYTHON_DIR          - path to the python directory (for instance_rw import)
"""
import json
import os
import sys
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, os.environ.get('PYTHON_DIR', ''))
    # util_lib lives one directory above PYTHON_DIR (e.g. common/scripts/).
    sys.path.insert(0, str(Path(os.environ.get('PYTHON_DIR', '.')).parent))
    try:
        from instance_rw import mutate
        from util_lib import clearDriftAlertPending
    except Exception:
        sys.exit(0)
    path = Path(os.environ['DRIFT_INSTANCE_FILE'])
    try:
        d = json.load(open(path))
    except Exception:
        sys.exit(0)
    da = d.get('drift_alert', {}) or {}
    if da.get('pending'):
        mutate(path, clearDriftAlertPending)
        print(da.get('message', 'drift detected'))
