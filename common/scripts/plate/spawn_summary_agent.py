"""spawn_summary_agent.py — fire a background tmux pane running a claude
agent that writes a recovery summary for the just-pushed plate.

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

from common.scripts.bg_permissions_lib import bgPermissions_loadClaude
from common.scripts.util_lib import terminal_spawnIfNeeded

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLATE_SKILL = _REPO_ROOT / "skills" / "plate"
_PROMPT_FILE = _PLATE_SKILL / "scripts" / "prompts" / "summary-agent.md"
_TEMPLATE_FILE = _PLATE_SKILL / "summary-template.md"
_ORCHESTRATOR = _REPO_ROOT / "scripts" / "jot_plugin_orchestrator.py"
# Read-only git verbs and text-tool allowlists live in
# assets/bg_agent_permissions.json under plate_permissions.claude.allow.
# Per-invocation dynamic paths (plate_skill_dir, output_dir, transcript
# project_dir) are appended via extra_allow at spawn() time.


def _next_session_index() -> int:
    """Atomically increment a counter file and return the new value.

    Mirrors jot's pane-counter.txt pattern. Wraps at 999 to keep tmux
    session names short. Falls back to a tmpdir-based counter when
    CLAUDE_PLUGIN_DATA is unset (e.g. test environments).
    """
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    counter_file = (
        Path(base) / "plate-summary-counter.txt"
        if base
        else Path(tempfile.gettempdir()) / "plate-summary-counter.txt"
    )
    counter_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        n = int(counter_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        n = 0
    n = (n % 999) + 1
    counter_file.write_text(f"{n}\n")
    return n


def spawn(
    repo: Path,
    branch: str,
    tip_sha: str,
    transcript_path: Optional[str],
) -> Optional[str]:
    """Launch the summary agent in a background tmux pane.

    Returns the tmux attach hint on launch, None when skipped
    (PLATE_SKIP_LAUNCH set, or claude/tmux missing). Always returns
    without blocking.
    """
    if os.environ.get("PLATE_SKIP_LAUNCH") == "1":
        return None
    if not shutil.which("tmux") or not shutil.which("claude"):
        return None

    # Per-invocation tmpdir holds settings.json + input.txt + the agent's
    # `output_file` (summary.txt). Keeping the output OUTSIDE the repo is
    # essential: any path under <repo>/ that isn't gitignored marks the
    # WT dirty, and the SessionEnd auto-/plate fired on conversation
    # reload would see the new WT-tree, treat it as real work, and
    # spawn a second summary agent. /var/folders/ side-steps that.
    tmpdir = Path(tempfile.mkdtemp(prefix="plate-summary-"))
    output_file = tmpdir / "summary.txt"

    # Per-invocation settings.json with inlined hooks block. Claude Code
    # expects `hooks` to be an OBJECT mapping event names → matcher
    # arrays, NOT a path string — that mistake produces a "Settings
    # Warning" prompt at agent startup and silently disables the hook.
    # Mirrors jot's pattern in claude-launcher.sh::build_claude_cmd.
    #
    # The plugin-level hooks.json (with /plate auto-fire) is NOT loaded
    # by the spawned claude because this per-invocation settings.json
    # supplies its own hooks block.
    stop_command = (
        f"python3 {shlex.quote(str(_ORCHESTRATOR))} plate-summary-stop "
        f"{shlex.quote(str(repo))} {shlex.quote(branch)} "
        f"{shlex.quote(str(output_file))}"
    )

    # Permission rule shape: Claude Code's path matcher uses a leading
    # `//` to mark an absolute path. Both Write and Edit are needed:
    # Claude Code's diff-confirmation path on first-time creation goes
    # through Edit, not Write — confirmed in an earlier live capture.
    def _abs(p: str) -> str:
        return "//" + p.lstrip("/")
    plate_skill_dir = str(_PLATE_SKILL)                  # template + prompt
    output_dir = str(output_file.parent)                 # <repo>/.plate/summaries
    extra_allow = [
        f"Read({_abs(plate_skill_dir)}/**)",
        f"Read({_abs(output_dir)}/**)",
        f"Write({_abs(output_dir)}/**)",
        f"Edit({_abs(output_dir)}/**)",
    ]
    # Restrict transcript Read to THIS conversation's project dir only —
    # not the whole ~/.claude/projects/ tree (would leak access to every
    # other session's transcripts on this machine).
    if transcript_path:
        project_dir = str(Path(transcript_path).parent)
        extra_allow.append(f"Read({_abs(project_dir)}/**)")

    # The static read-only-git + read-only-text floor is sourced from
    # assets/bg_agent_permissions.json (plate_permissions.claude.allow);
    # extra_allow is the per-invocation dynamic portion.
    permissions_allow = json.loads(bgPermissions_loadClaude(
        "plate",
        env={
            "CWD": str(repo),
            "HOME": os.environ.get("HOME", ""),
            "REPO_ROOT": str(repo),
        },
        extra_allow=extra_allow,
    ))

    settings_path = tmpdir / "settings.json"
    settings_path.write_text(json.dumps({
        "permissions": {
            "allow": permissions_allow,
        },
        "hooks": {
            # No Stop hook: Claude Code's `decision:"block"` for Stop
            # means "BLOCK the stop, force agent to continue" (opposite
            # of PreToolUse). The earlier exit-when-done hook had this
            # backwards — emitting block on file-written kept the agent
            # alive, producing an infinite "Exiting." → Stop → block →
            # "Exiting." loop. The agent's prompt instruction to exit
            # after writing the file is enough on its own; SessionEnd
            # below picks up after the natural stop.
            "SessionEnd": [{
                "hooks": [{
                    "type": "command",
                    "command": stop_command,
                }],
            }],
        },
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

    # Counter-based session naming so concurrent /plate invocations
    # across worktrees/repos land in distinct tmux sessions and don't
    # accidentally share a window list.
    session_index = _next_session_index()
    session_name = f"plate-summary-{session_index}"
    window_name = f"plate-summary-{tip_sha[:8]}"
    claude_cmd = (
        f"cat {shlex.quote(str(input_file))} | "
        f"claude --settings {shlex.quote(str(settings_path))} "
        f"--add-dir {shlex.quote(str(repo))}"
    )

    # Forward the per-repo log path so the spawned agent's SessionEnd
    # hook writes to the same file as the parent /plate invocation.
    log_file = os.environ.get("PLATE_LOG_FILE", "")
    spawn_env = {**os.environ, "PLATE_SKIP_AUTO": "1"}
    if log_file:
        spawn_env["PLATE_LOG_FILE"] = log_file

    subprocess.Popen(
        ["tmux", "new-session", "-d", "-s", session_name,
         "-n", window_name, "-c", str(repo), claude_cmd],
        env=spawn_env,
    )

    # Fire-and-forget watcher. Polls the agent's output_file; once it's
    # non-empty (Claude's Write tool is atomic temp-then-rename, so a
    # non-empty read means the write completed), sends `/exit\n` into
    # the pane to trigger graceful shutdown. The SessionEnd hook fires
    # after the shutdown and runs the trailer-rewrite. Mirrors the
    # `/debate` orchestrator's `wait_for_outputs` → `tmux_kill_pane`
    # pattern, but uses `/exit` instead of kill-pane so SessionEnd has
    # a chance to fire normally.
    pane_target = f"{session_name}:{window_name}"
    # start_new_session=True detaches the watcher from this process's
    # group so it survives parent exit. /plate runs as a UserPromptSubmit
    # hook and this orchestrator process returns within milliseconds; once
    # Claude Code reaps the hook PID, the kernel delivers SIGHUP to the
    # hook's process group. Without detachment the watcher dies before
    # its first poll and the tmux pane stays alive forever. Same pattern
    # as terminal_spawnIfNeeded (util_lib.py:200-206).
    subprocess.Popen(
        ["python3", str(_ORCHESTRATOR), "plate-summary-watch",
         pane_target, str(output_file)],
        env=spawn_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Open a Terminal.app window attached to this session (parity with
    # /debate). `compact` clamps the new window to a centered 1000x700
    # rect so the plate window doesn't inherit a maximized bound from
    # a previous /debate run. terminal_spawnIfNeeded is non-blocking:
    # it Popens osascript with start_new_session=True so the spawned
    # process is detached from this process group and survives parent
    # exit (critical when /plate runs as a UserPromptSubmit hook and
    # the orchestrator returns within milliseconds — a daemon thread
    # here would be killed before it could even reach the Popen call).
    terminal_log_arg = log_file if log_file else "/dev/null"
    try:
        terminal_spawnIfNeeded(session_name, terminal_log_arg, "plate", "compact")
    except Exception:
        # Best-effort: terminal launch must never block /plate push.
        pass

    return f"tmux attach -t {session_name}:{window_name}"
