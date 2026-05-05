#!/bin/bash
exec python3 "$(dirname "${BASH_SOURCE[0]}")/jot-plugin-orchestrator.py" "$@"
