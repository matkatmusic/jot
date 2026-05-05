"""GREEN: debate_buildClaudeCmd — Python port of bash debate_build_claude_cmd.

Bash source: jot-plugin-orchestrator.sh:2245-2265.
RELAXED_COVERAGE — no paired bash _tests; intent test from docstring.
"""
import os
import sys
import tempfile
from pathlib import Path

# sys.path so we can import the Python monolith for claude_buildCmd.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from jot_plugin_orchestrator import *  # noqa: F401,F403  (provides claude_buildCmd)


# Provisions a fresh /tmp/debate.* dir, seeds permissions, expands them via the
# injected expand_permissions_fn, then calls claude_buildCmd to write
# settings.json and produce the launch cmd. Returns dict with tmpdir_inv,
# settings_file, cmd. permissions_seed_fn / expand_permissions_fn are injected
# so tests do not require the bash helpers or expand_permissions.py subprocess.
def debate_buildClaudeCmd(
    cwd: str,
    repo_root: str,
    log_file: str,
    permissions_seed_fn,
    expand_permissions_fn,
) -> dict:
    plugin_data = os.environ["CLAUDE_PLUGIN_DATA"]
    plugin_root = os.environ["CLAUDE_PLUGIN_ROOT"]

    # YELLOW intent: mirror bash mktemp -d /tmp/debate.XXXXXX, then build
    # settings_file path inside it.
    tmpdir_inv = tempfile.mkdtemp(prefix="debate.", dir="/tmp")
    settings_file = str(Path(tmpdir_inv) / "settings.json")

    permissions_file = str(Path(plugin_data) / "debate-permissions.local.json")
    default_file = str(
        Path(plugin_root) / "skills/debate/scripts/assets/permissions.default.json"
    )
    default_sha_file = str(
        Path(plugin_root) / "skills/debate/scripts/assets/permissions.default.json.sha256"
    )
    prior_sha_file = str(Path(plugin_data) / "debate-permissions.default.sha256")

    # mkdir -p "$CLAUDE_PLUGIN_DATA"
    Path(plugin_data).mkdir(parents=True, exist_ok=True)

    permissions_seed_fn(
        permissions_file,
        default_file,
        default_sha_file,
        prior_sha_file,
        log_file,
        "debate",
    )

    allow_json = expand_permissions_fn(
        permissions_file, cwd, repo_root, os.environ.get("HOME", "")
    )

    # Empty hooks JSON file — claude_buildCmd needs a path.
    hooks_json_file = str(Path(tmpdir_inv) / "hooks.json")
    Path(hooks_json_file).write_text("{}\n")

    cmd = claude_buildCmd(  # noqa: F405  (star import from monolith)
        settings_file, allow_json, hooks_json_file, cwd, repo_root
    )

    return {
        "tmpdir_inv": tmpdir_inv,
        "settings_file": settings_file,
        "cmd": cmd,
    }
