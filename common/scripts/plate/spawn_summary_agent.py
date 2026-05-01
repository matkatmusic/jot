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
_WATCH_SCRIPT = _PLATE_SKILL / "scripts" / "plate-summary-watch.sh"
_PLATFORM_SH = _REPO_ROOT / "common" / "scripts" / "platform.sh"

# Read-only git verbs the agent legitimately needs. NO destructive verbs
# (add, commit, branch, checkout, clean, reset, rebase, rm, update-ref,
# worktree, read-tree, write-tree, commit-tree, apply, cherry-pick, init,
# config, stash) — agent literally cannot mutate the repo.
_READ_ONLY_GIT_VERBS = (
    "log", "diff", "show", "rev-parse", "rev-list", "for-each-ref",
    "ls-tree", "ls-files", "merge-base", "status", "cat-file",
)


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
        f"bash {shlex.quote(str(_STOP_HOOK))} "
        f"{shlex.quote(str(repo))} {shlex.quote(branch)} "
        f"{shlex.quote(str(output_file))}"
    )

    # Narrow read-only allow-list: agent cwd is the repo, so plain `git
    # log` (no `-C`) inherits the repo path — keeps verb wildcards from
    # accidentally allowing destructive `git -C <repo> <anything>`.
    git_allows: list[str] = []
    for verb in _READ_ONLY_GIT_VERBS:
        git_allows.append(f"Bash(rtk git {verb}:*)")
        git_allows.append(f"Bash(git {verb}:*)")

    # Permission rule shape: Claude Code's path matcher uses a leading
    # `//` to mark an absolute path. `expand_permissions.py:28` lstrips
    # the leading `/` from REPO_ROOT before pairing it with the literal
    # `//`, producing `Read(//Users/...)` at runtime — confirmed in a
    # live capture as the working form. Single-slash `Read(/Users/...)`
    # does NOT match (the agent surfaces a permission prompt anyway).
    def _abs(p: str) -> str:
        return "//" + p.lstrip("/")
    plate_skill_dir = str(_PLATE_SKILL)                  # template + prompt
    output_dir = str(output_file.parent)                 # <repo>/.plate/summaries
    # Both Write and Edit are needed: Claude Code's diff-confirmation
    # path on first-time-creation goes through Edit, not Write — the
    # earlier live capture's "Do you want to make this edit?" prompt
    # confirms this. Mirror jot's pattern of listing both verbs.
    permissions_allow = [
        f"Read({_abs(plate_skill_dir)}/**)",
        f"Read({_abs(output_dir)}/**)",
        f"Write({_abs(output_dir)}/**)",
        f"Edit({_abs(output_dir)}/**)",
        *git_allows,
    ]
    # Restrict transcript Read to THIS conversation's project dir only —
    # not the whole ~/.claude/projects/ tree (would leak access to every
    # other session's transcripts on this machine).
    if transcript_path:
        project_dir = str(Path(transcript_path).parent)
        permissions_allow.insert(1, f"Read({_abs(project_dir)}/**)")

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
    watcher_cmd = (
        f"bash {shlex.quote(str(_WATCH_SCRIPT))} "
        f"{shlex.quote(pane_target)} {shlex.quote(str(output_file))}"
    )
    subprocess.Popen(
        ["bash", "-c", watcher_cmd],
        env=spawn_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Open a Terminal.app window attached to this session (parity with
    # /debate). No maximize — single-pane session, regular size is fine.
    if log_file:
        terminal_cmd = (
            f'source {shlex.quote(str(_PLATFORM_SH))} && '
            f'spawn_terminal_if_needed {shlex.quote(session_name)} '
            f'{shlex.quote(log_file)} plate'
        )
    else:
        terminal_cmd = (
            f'source {shlex.quote(str(_PLATFORM_SH))} && '
            f'spawn_terminal_if_needed {shlex.quote(session_name)} '
            f'/dev/null plate'
        )
    subprocess.Popen(["bash", "-c", terminal_cmd], env=spawn_env)

    return f"tmux attach -t {session_name}:{window_name}"
