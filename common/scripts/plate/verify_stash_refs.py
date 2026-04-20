#!/usr/bin/env python3
"""Verify stash refs are alive for a plate instance.

Checks that git refs and push_time_head_sha are still reachable.
Emits warnings to stderr if any refs are missing or unreachable.

Env vars:
  INSTANCE_FILE - path to the instance JSON file
  SESSION_ID    - session/convo ID
"""
import json
import os
import subprocess
import sys

if __name__ == '__main__':
    d = json.load(open(os.environ['INSTANCE_FILE']))
    session_id = os.environ['SESSION_ID']
    warnings = []
    for plate in d.get('stack', []):
        ref = f"refs/plates/{session_id}/{plate['plate_id']}"
        result = subprocess.run(['git', 'cat-file', '-t', ref], capture_output=True, text=True)
        if result.returncode != 0:
            warnings.append(f"  stash ref {ref} missing (may have been GC'd)")
        head = plate.get('push_time_head_sha', '')
        if head:
            result2 = subprocess.run(['git', 'merge-base', '--is-ancestor', head, 'HEAD'], capture_output=True)
            if result2.returncode != 0:
                warnings.append(f"  push_time_head_sha {head[:8]} not reachable from HEAD (branch rewritten?)")
    if warnings:
        print('plate freshness warnings:', file=sys.stderr)
        for w in warnings:
            print(w, file=sys.stderr)
