#!/usr/bin/env python3
"""Clear stale drift alerts on session resume.

Env vars:
  INSTANCE_FILE - path to the instance JSON file
  PYTHON_DIR    - path to the python directory (for instance_rw import)
"""
import os
import sys

if __name__ == '__main__':
    sys.path.insert(0, os.environ['PYTHON_DIR'])
    from instance_rw import mutate
    from pathlib import Path

    def _clear(d):
        d.setdefault('drift_alert', {})['pending'] = False

    mutate(Path(os.environ['INSTANCE_FILE']), _clear)
