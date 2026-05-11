#!/usr/bin/env python3
"""Clear stale drift alerts on session resume.

Env vars:
  INSTANCE_FILE - path to the instance JSON file
  PYTHON_DIR    - path to the python directory (for instance_rw import)
"""
import os
import sys
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, os.environ['PYTHON_DIR'])
    # util_lib lives one directory above PYTHON_DIR (e.g. common/scripts/).
    sys.path.insert(0, str(Path(os.environ['PYTHON_DIR']).parent))
    from instance_rw import mutate
    from util_lib import clearDriftAlertPending

    mutate(Path(os.environ['INSTANCE_FILE']), clearDriftAlertPending)
