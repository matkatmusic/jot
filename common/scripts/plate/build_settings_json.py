#!/usr/bin/env python3
"""Build per-invocation settings.json for bg-agent tmux window.

Expands permission placeholders, adds transcript read rule, and writes
hooks for SessionStart/Stop/SessionEnd.

Env vars:
  PERM_INSTALLED  - path to installed permissions template
  SETTINGS_FILE   - output path for generated settings.json
  PLATE_ROOT      - plate root directory (for placeholder expansion)
  TRANSCRIPT_PATH - transcript file path (optional)
  TMPDIR_INV      - per-invocation temp directory
  INPUT_FILE      - bg-agent input file path
  TMUX_TARGET     - tmux target for worker scripts
"""
import json
import os
from pathlib import Path

if __name__ == '__main__':
    perm_src = Path(os.environ['PERM_INSTALLED'])
    out = Path(os.environ['SETTINGS_FILE'])
    plate_root = os.environ['PLATE_ROOT']
    transcript = os.environ.get('TRANSCRIPT_PATH', '') or ''
    tmpdir = os.environ['TMPDIR_INV']
    input_file = os.environ['INPUT_FILE']
    tmux_target = os.environ['TMUX_TARGET']

    # Load template (user-editable or freshly-seeded default)
    template = json.loads(perm_src.read_text(encoding='utf-8')) if perm_src.exists() else {}
    perms = template.get('permissions', {}) or {}

    def expand(s: str) -> str:
        # Substitute placeholders. lstrip leading '/' on PLATE_ROOT so that
        # '//${PLATE_ROOT}/**' -> '//<absolute-path>/**' without collapsing to '/'.
        return (s
                .replace('${PLATE_ROOT}', plate_root.lstrip('/'))
                .replace('${HOME}', os.environ.get('HOME', '')))

    def expand_list(xs):
        return [expand(x) for x in xs or []]

    allow = expand_list(perms.get('allow'))
    deny = expand_list(perms.get('deny'))

    # Always add the transcript read rule so bg-agent can actually read the
    # conversation. Transcripts are under ~/.claude/projects/<hash>/...
    if transcript:
        allow.append(f'Read({transcript})')

    settings = {
        'permissions': {
            'allow': allow,
            **({'deny': deny} if deny else {}),
        },
        'hooks': {
            'SessionStart': [{'hooks': [{'type': 'command', 'command': f"bash {tmpdir}/plate-worker-start.sh '{input_file}' '{tmux_target}'"}]}],
            'Stop': [{'hooks': [{'type': 'command', 'command': f"bash {tmpdir}/plate-worker-stop.sh '{input_file}' '{tmux_target}'"}]}],
            'SessionEnd': [{'hooks': [{'type': 'command', 'command': f"bash {tmpdir}/plate-worker-end.sh '{tmpdir}'"}]}],
        },
    }
    out.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
