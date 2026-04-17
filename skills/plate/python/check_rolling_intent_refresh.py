#!/usr/bin/env python3
"""Check if rolling intent needs refresh.

Prints 'yes' if snapshot is missing or older than 5 minutes, 'no' otherwise.

Env vars:
  INSTANCE_FILE - path to the instance JSON file
"""
import json
import os
from datetime import datetime, timezone, timedelta

if __name__ == '__main__':
    try:
        d = json.load(open(os.environ['INSTANCE_FILE']))
    except Exception:
        print('yes')
        raise SystemExit
    ri = d.get('rolling_intent', {}) or {}
    snap = ri.get('snapshot_at')
    if not snap:
        print('yes')
    else:
        try:
            snap_dt = datetime.fromisoformat(snap.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) - snap_dt > timedelta(minutes=5):
                print('yes')
            else:
                print('no')
        except Exception:
            print('yes')
