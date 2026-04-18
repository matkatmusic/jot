#!/usr/bin/env python3
"""Check if instance has live delegated children.

Prints 'yes' if any stack plate is in 'delegated' state with delegated_to,
otherwise prints 'no'.

Env vars:
  INSTANCE_FILE - path to the instance JSON file
"""
import json
import os

if __name__ == '__main__':
    d = json.load(open(os.environ['INSTANCE_FILE']))
    live = any(p.get('delegated_to') for p in d.get('stack', []) if p.get('state') == 'delegated')
    print('yes' if live else 'no')
