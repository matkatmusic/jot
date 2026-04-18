#!/usr/bin/env python3
"""List paused plates from a single instance file.

Reads INSTANCE_FILE env var, outputs one row per paused plate:
  <convoID>|<plate_id>|<label>|<summary_action>|<pushed_at>
"""
import json
import os

if __name__ == '__main__':
    d = json.load(open(os.environ['INSTANCE_FILE']))
    convo = d.get('convo_id', '')
    label = d.get('label') or convo[:12]
    for p in d.get('stack', []):
        if p.get('state') == 'paused':
            pushed = p.get('pushed_at', '')
            action = p.get('summary_action') or '(no synopsis)'
            print(f"{convo}|{p['plate_id']}|{label}|{action}|{pushed}")
