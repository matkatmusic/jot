#!/usr/bin/env python3
"""Print resume command for parent instance if one exists.

Env vars:
  INSTANCE_FILE - path to the instance JSON file
  PLATE_ROOT    - root directory for plate state
"""
import json
import os
from pathlib import Path

if __name__ == '__main__':
    d = json.load(open(os.environ['INSTANCE_FILE']))
    pr = d.get('parent_ref', {})
    if pr.get('convo_id'):
        parent_path = Path(os.environ['PLATE_ROOT']) / 'instances' / f'{pr["convo_id"]}.json'
        if parent_path.exists():
            pd = json.load(open(parent_path))
            cwd = pd.get('cwd', '.')
            print(f'\nTo resume parent, run:\n  cd {cwd} && claude --resume {pr["convo_id"]}')
