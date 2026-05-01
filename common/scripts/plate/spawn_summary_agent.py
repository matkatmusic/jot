"""spawn_summary_agent.py — fire a background tmux pane running a claude
agent that writes a recovery summary for the just-pushed plate.

Mirrors the shape of `skills/jot/scripts/jot.sh::phase2_launch_window`:
build a per-invocation tmpdir with a custom hooks.json, compose the agent
prompt + job payload as the first user message, launch claude in a tmux
window. The agent runs synchronously inside its pane, writes a single
output file, and exits. The per-invocation Stop hook (referenced from
the custom hooks.json) reads the file and calls back into `cli.py
set-plate-summary` to commit the trailer rewrite.

PLATE_SKIP_LAUNCH=1 env var short-circuits this entire function (mirror
of /jot's JOT_SKIP_LAUNCH escape hatch). Used by tests + dry-runs.

PLATE_SKIP_AUTO=1 is exported into the spawned agent's env as a belt-
and-suspenders against re-entrant /plate firing on the agent's own
SessionEnd. The plugin-level hooks.json's SessionEnd command checks
for it.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLATE_SKILL = _REPO_ROOT / "skills" / "plate"
_PROMPT_FILE = _PLATE_SKILL / "scripts" / "prompts" / "summary-agent.md"
_TEMPLATE_FILE = _PLATE_SKILL / "summary-template.md"
_STOP_HOOK = _PLATE_SKILL / "scripts" / "plate-summary-stop.sh"


def spawn(
    repo: Path,
    branch: str,
    tip_sha: str,
    transcript_path: Optional[str],
) -> Optional[str]:
    """Launch the summary agent in a background tmux pane.

    Returns the tmpdir path on launch, None when skipped (PLATE_SKIP_LAUNCH
    set, or claude/tmux missing). Always returns without blocking.
    """
    if os.environ.get("PLATE_SKIP_LAUNCH") == "1":
        return None
    if not shutil.which("tmux") or not shutil.which("claude"):
        return None

    tmpdir = Path(tempfile.mkdtemp(prefix="plate-summary-"))
    output_file = tmpdir / "summary.txt"

    # Per-invocation hooks.json: only SessionEnd fires our stop hook.
    # Crucially, the plugin-level hooks.json (with /plate auto-fire) is
    # NOT loaded by the spawned claude — the per-invocation settings.json
    # supplies its own hooks block.
    hooks_path = tmpdir / "hooks.json"
    hooks_path.write_text(json.dumps({
        "SessionEnd": [{
            "hooks": [{
                "type": "command",
                "command": (
                    f"bash {shlex.quote(str(_STOP_HOOK))} "
                    f"{shlex.quote(str(repo))} {shlex.quote(branch)} "
                    f"{shlex.quote(str(output_file))}"
                ),
            }],
        }],
    }, indent=2))

    settings_path = tmpdir / "settings.json"
    settings_path.write_text(json.dumps({
        "hooks": str(hooks_path),
    }, indent=2))

    payload = {
        "repo": str(repo),
        "branch": branch,
        "tip_sha": tip_sha,
        "transcript_path": transcript_path or "",
        "output_file": str(output_file),
        "template_path": str(_TEMPLATE_FILE),
    }

    prompt_body = _PROMPT_FILE.read_text()
    input_file = tmpdir / "input.txt"
    input_file.write_text(
        prompt_body
        + "\n\n## Job Payload\n\n```json\n"
        + json.dumps(payload, indent=2)
        + "\n```\n"
    )

    # Spawn in a tmux pane. Read input.txt as the first user message.
    window_name = f"plate-summary-{tip_sha[:8]}"
    claude_cmd = (
        f"cat {shlex.quote(str(input_file))} | "
        f"claude --settings {shlex.quote(str(settings_path))} "
        f"--add-dir {shlex.quote(str(repo))}"
    )
    spawn_env = {**os.environ, "PLATE_SKIP_AUTO": "1"}
    if not _tmux_has_session("plate-summary"):
        subprocess.Popen(
            ["tmux", "new-session", "-d", "-s", "plate-summary",
             "-n", window_name, "-c", str(repo), claude_cmd],
            env=spawn_env,
        )
    else:
        subprocess.Popen(
            ["tmux", "new-window", "-t", "=plate-summary:",
             "-n", window_name, "-c", str(repo), claude_cmd],
            env=spawn_env,
        )

    return str(tmpdir)


def _tmux_has_session(name: str) -> bool:
    rc = subprocess.run(
        ["tmux", "has-session", "-t", f"={name}"],
        capture_output=True,
    ).returncode
    return rc == 0
