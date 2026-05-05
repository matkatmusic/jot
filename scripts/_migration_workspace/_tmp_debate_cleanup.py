"""debate_cleanup — Python port of cleanup() from jot-plugin-orchestrator.sh.

Bash original (lines 2713-2719):
    cleanup() {
      local settings_dir
      settings_dir=$(dirname "$SETTINGS_FILE")
      case "$settings_dir" in
        /tmp/debate.*) rm -rf "$settings_dir" ;;
      esac
    }

Contract:
  - Derives the parent directory of settings_file.
  - If that directory matches /tmp/debate.* (basename starts with "debate."),
    recursively removes it.
  - All other paths are left untouched (safe no-op).
  - settings_file may be a str or Path; missing file is allowed (parent only
    needs to exist for removal to make sense — but we guard with exists()).
"""
from __future__ import annotations

import shutil
from pathlib import Path


def debate_cleanup(settings_file: str | Path) -> None:
    """Remove the debate temp-settings directory when it lives under /tmp.

    Args:
        settings_file: Path to the settings JSON file (e.g.
            /tmp/debate.XYZ/settings.json).  Only the *parent* directory is
            examined; the file itself need not exist.

    Side effects:
        If settings_file.parent matches the pattern /tmp/debate.* the entire
        parent directory is deleted with shutil.rmtree.  All other locations
        are left untouched.
    """
    settings_path = Path(settings_file)
    settings_dir = settings_path.parent

    # Mirror bash case pattern: /tmp/debate.*
    # Condition: parent is /tmp AND directory name starts with "debate."
    if settings_dir.parent == Path("/tmp") and settings_dir.name.startswith("debate."):
        if settings_dir.exists():
            shutil.rmtree(settings_dir)
