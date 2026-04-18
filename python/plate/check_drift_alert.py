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

if __name__ == '__main__':
    sys.path.insert(0, os.environ.get('PYTHON_DIR', ''))
    try:
        from instance_rw import mutate
        from pathlib import Path
    except Exception:
        sys.exit(0)
    path = Path(os.environ['DRIFT_INSTANCE_FILE'])
    try:
        d = json.load(open(path))
    except Exception:
        sys.exit(0)
    da = d.get('drift_alert', {}) or {}
    if da.get('pending'):
        def _clear(x):
            x.setdefault('drift_alert', {})['pending'] = False
        mutate(path, _clear)
        print(da.get('message', 'drift detected'))
