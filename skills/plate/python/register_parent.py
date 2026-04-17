#!/usr/bin/env python3
"""Register parent-child relationship between plate instances.

Sets child's parent_ref and adds child to parent's delegated_to[],
flipping the parent plate's state to 'delegated'.

Env vars:
  CHILD_FILE    - path to child instance JSON
  PARENT_FILE   - path to parent instance JSON
  CHILD_CONVO   - child conversation ID
  PARENT_CONVO  - parent conversation ID
  PARENT_PLATE  - parent plate ID
  PYTHON_DIR    - path to the python directory (for instance_rw import)
"""
import os
import sys

if __name__ == '__main__':
    sys.path.insert(0, os.environ['PYTHON_DIR'])
    from instance_rw import load, atomic_write
    from pathlib import Path

    # Set child's parent_ref
    child_path = Path(os.environ['CHILD_FILE'])
    child = load(child_path)
    child['parent_ref'] = {
        'convo_id': os.environ['PARENT_CONVO'],
        'plate_id': os.environ['PARENT_PLATE'],
    }
    atomic_write(child_path, child)

    # Add child to parent's delegated_to[] and flip state
    parent_path = Path(os.environ['PARENT_FILE'])
    parent = load(parent_path)
    child_id = os.environ['CHILD_CONVO']
    parent_plate = os.environ['PARENT_PLATE']
    for plate in parent.get('stack', []):
        if plate['plate_id'] == parent_plate:
            if child_id not in plate.get('delegated_to', []):
                plate.setdefault('delegated_to', []).append(child_id)
            plate['state'] = 'delegated'
            break
    atomic_write(parent_path, parent)
