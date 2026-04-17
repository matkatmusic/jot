#!/usr/bin/env python3
"""Cascade completion up through parent delegation chain.

Removes child from parent's delegated_to[] and flips state back to 'paused'
if no more delegated children remain.

Env vars:
  INSTANCE_FILE - path to the child instance JSON file
  PLATE_ROOT    - root directory for plate state
  CONVO_ID      - child conversation ID
  PYTHON_DIR    - path to the python directory (for instance_rw import)
  MAX_DEPTH     - max depth to traverse (cycle protection)
"""
import os
import sys

if __name__ == '__main__':
    sys.path.insert(0, os.environ['PYTHON_DIR'])
    from instance_rw import load, atomic_write
    from pathlib import Path

    instance_file = Path(os.environ['INSTANCE_FILE'])
    data = load(instance_file)
    parent_ref = data.get('parent_ref', {})
    max_depth = int(os.environ['MAX_DEPTH'])
    convo_id = os.environ['CONVO_ID']
    plate_root = Path(os.environ['PLATE_ROOT'])
    depth = 0

    while parent_ref and parent_ref.get('convo_id') and depth < max_depth:
        parent_convo = parent_ref['convo_id']
        parent_plate_id = parent_ref.get('plate_id', '')
        parent_path = plate_root / 'instances' / f'{parent_convo}.json'
        if not parent_path.exists():
            break
        parent_data = load(parent_path)
        for plate in parent_data.get('stack', []):
            if plate['plate_id'] == parent_plate_id:
                dt = plate.get('delegated_to', [])
                if convo_id in dt:
                    dt.remove(convo_id)
                if not dt:
                    plate['state'] = 'paused'
                break
        atomic_write(parent_path, parent_data)
        # Stop at first ancestor (§9.2 step 3)
        break
