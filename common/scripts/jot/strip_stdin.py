#!/usr/bin/env python3
# Read stdin and print it with leading/trailing whitespace stripped.
# Shared helper — replaces inline `python3 -c 'import sys; print(sys.stdin.read().strip())'`
# across jot.sh and any sibling scripts that need the same behaviour.
import sys

print(sys.stdin.read().strip())
