

from __future__ import annotations

import glob
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable, IO, Iterable, List, Mapping, Optional, Sequence, TypedDict

from common.scripts.bg_permissions_lib import (
    bgPermissions_loadClaude,
    bgPermissions_loadCodex,
    bgPermissions_loadGemini,
)
from common.scripts.claude_lib import (
    claude_buildCmd
)
from common.scripts.hookjson_lib import (
    hookjson_checkRequirements,
    hookjson_emitBlock,
)
from common.scripts.tmux_lib import (
    _tmux_default_runner,
    _tmux_kill_pane,
    _tmux_listLivePaneIds,
    _tmux_live_pane_ids,
    _tmux_paneCurrentCommand,
    tmux_capturePane,
    tmux_killPane,
    tmux_retile,
    tmux_sendAndSubmit,
    tmux_splitWorkerPane,
)
from common.scripts.util_lib import (
    _util_slugify,
    shell_waitForFile,
    terminal_spawnIfNeeded,
)

_MAX_SESSIONS = 999

_LOCK_PANE_RE = re.compile(r"^debate:(%\d+)$", re.MULTILINE)

_LOCK_LINE_RE = re.compile(r"^debate:(%[0-9]+)$", re.MULTILINE)

# Agents in the order the bash loop initializes them.
_AGENTS = ("gemini", "codex", "claude")

# Map agent -> env var name that seeds CURRENT_MODEL/TRIED_MODELS.
# claude has no seed env var (matches bash, which only stashes "" for it).
_AGENT_ENV_VAR = {"gemini": "GEMINI_MODEL", "codex": "CODEX_MODEL"}


def debate_agentReadyMarker(agent: str) -> str:
    # GREEN: mirror bash `agent_ready_marker` case statement verbatim.
    if agent == "gemini":
        return "Type your message or @path/to/file"
    if agent == "codex":
        return "/model to change"
    if agent == "claude":
        return "Claude Code v"
    # Bash `case` with no default leaves stdout empty.
    return ""


# Frozen tuples used as the source of truth; copied into a fresh list per
# call so callers cannot mutate shared state.
_MARKERS: dict[str, tuple[str, ...]] = {
    "codex": (
        "Selected model is at capacity",
        "model is overloaded",
    ),
    "gemini": (
        "RESOURCE_EXHAUSTED",
        "Quota exceeded",
        "You exceeded your current quota",
    ),
    "claude": (
        "API Error: 529",
        "overloaded_error",
    ),
}


def debate_agentErrorMarkers(agent: str) -> list[str]:
    """Return capacity/quota/overload error markers for ``agent``.

    Mirrors bash `agent_error_markers`: a case statement over
    ``codex|gemini|claude`` printing one marker per line. Unknown agent
    names yield an empty list (bash printed nothing).

    Args:
        agent: Agent identifier (``codex``, ``gemini``, or ``claude``).

    Returns:
        Ordered list of marker substrings. Empty list for unknown agents.
    """
    return list(_MARKERS.get(agent, ()))


# YELLOW intent: build the per-agent shell command string used by tmux to start
# the debate agent CLI. Looks up the current model from a stash dict (empty
# string => omit --model). For claude, dedupe --add-dir entries so the same
# directory isn't passed twice when CWD/REPO_ROOT/$HOME/.claude/plans collide.
def debate_agentLaunchCmd(
    *,
    agent: str,
    current_model: dict[str, str],
    debate_dir: str,
    cwd: str,
    repo_root: str,
    home: str,
    settings_file: str,
) -> str:
    # Lookup model from stash; bash _lookup CURRENT_MODEL "$a" returns "" when unset.
    m = current_model.get(agent, "")

    if agent == "gemini":
        # --allowed-tools sourced from assets/bg_agent_permissions.json
        # (debate_permissions.gemini.allowed_tools). Per-invocation --model
        # stays in Python because it's resolved from the runtime model stash.
        allowed = bgPermissions_loadGemini()
        base = f"gemini --allowed-tools '{allowed}'"
        if m:
            return f"{base} --model '{m}'"
        return base

    if agent == "codex":
        # approval/sandbox sourced from debate_permissions.codex; --add-dir
        # and --model are per-invocation and stay in Python.
        codex_cfg = bgPermissions_loadCodex()
        approval = codex_cfg["approval"]
        sandbox_mode = codex_cfg["sandbox_mode"]
        base = f"codex -a {approval} -s {sandbox_mode} --add-dir '{debate_dir}'"
        for flag in codex_cfg.get("extra_flags", []):
            base += f" {flag}"
        if m:
            return f"{base} --model '{m}'"
        return base

    if agent == "claude":
        # Mirror bash dedupe logic exactly:
        #   dirs="--add-dir '$CWD'"
        #   [ -n "$REPO_ROOT" ] && [ "$REPO_ROOT" != "$CWD" ] && dirs+=" --add-dir '$REPO_ROOT'"
        #   [ "$HOME/.claude/plans" != "$CWD" ] && [ "$HOME/.claude/plans" != "$REPO_ROOT" ] \
        #       && dirs+=" --add-dir '$HOME/.claude/plans'"
        plans = f"{home}/.claude/plans"
        dirs = f"--add-dir '{cwd}'"
        if repo_root and repo_root != cwd:
            dirs += f" --add-dir '{repo_root}'"
        if plans != cwd and plans != repo_root:
            dirs += f" --add-dir '{plans}'"
        return f"claude --settings '{settings_file}' {dirs}"

    # Bash case statement falls through silently for unknown agent.
    return ""


# YELLOW intent (plain English):
#   Move all "intermediate" debate scratch files from DEBATE_DIR into
#   DEBATE_DIR/archive/. The bash glob list pins exactly which files count as
#   intermediate: context.md, synthesis_instructions.txt, r1_instructions_*.txt,
#   r1_*.md, r2_instructions_*.txt, r2_*.md, and orchestrator.log. The final
#   synthesis.md and primary inputs (topic.md, invoking_transcript.txt) are
#   intentionally excluded so they remain at the debate root. mkdir -p
#   semantics: a pre-existing archive/ directory is fine and its prior
#   contents are preserved.

# Move debate intermediate scratch files into DEBATE_DIR/archive/.
# Mirrors bash `archive_debate`: creates archive subdir (idempotent),
# then moves a fixed set of patterns. synthesis.md and topic.md are
# preserved at the debate root by exclusion (not in the pattern list).
def debate_archive(debate_dir: Path | str) -> None:
    debate_dir = Path(debate_dir)
    archive_dir = debate_dir / "archive"
    # mkdir -p "$DEBATE_DIR/archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Bash for-loop expands each literal path and each glob; literal paths
    # that don't exist are kept as-is by the shell, then filtered by `[ -f ]`.
    # We mirror that with explicit literal checks plus glob expansion.
    literals = (
        debate_dir / "context.md",
        debate_dir / "synthesis_instructions.txt",
    )
    glob_patterns = (
        "r1_instructions_*.txt",
        "r1_*.md",
        "r2_instructions_*.txt",
        "r2_*.md",
    )

    candidates: list[Path] = []
    candidates.extend(p for p in literals if p.is_file())
    for pattern in glob_patterns:
        candidates.extend(p for p in debate_dir.glob(pattern) if p.is_file())

    for src in candidates:
        # Move into archive_dir using the original filename. Path.replace
        # gives atomic same-filesystem rename semantics matching `mv`.
        src.replace(archive_dir / src.name)

    # Separate orchestrator.log clause in bash (handled outside the loop).
    log = debate_dir / "orchestrator.log"
    if log.is_file():
        log.replace(archive_dir / log.name)


# Provisions a fresh /tmp/debate.* dir, seeds permissions, expands them via the
# injected expand_permissions_fn, then calls claude_buildCmd to write
# settings.json and produce the launch cmd. Returns dict with tmpdir_inv,
# settings_file, cmd. permissions_seed_fn / expand_permissions_fn are injected
# so tests do not require the bash helpers or expand_permissions.py subprocess.
def debate_buildClaudeCmd(
    cwd: str,
    repo_root: str,
    log_file: str,
) -> dict:
    plugin_data = os.environ["CLAUDE_PLUGIN_DATA"]

    tmpdir_inv = tempfile.mkdtemp(prefix="debate.", dir="/tmp")
    settings_file = str(Path(tmpdir_inv) / "settings.json")

    Path(plugin_data).mkdir(parents=True, exist_ok=True)

    allow_json = bgPermissions_loadClaude(
        "debate",
        env={"CWD": cwd, "HOME": os.environ.get("HOME", ""), "REPO_ROOT": repo_root},
        log_file=log_file,
    )

    # Empty hooks JSON file — claude_buildCmd needs a path.
    hooks_json_file = str(Path(tmpdir_inv) / "hooks.json")
    Path(hooks_json_file).write_text("{}\n")

    cmd = claude_buildCmd(
        settings_file, allow_json, hooks_json_file, cwd, repo_root
    )

    return {
        "tmpdir_inv": tmpdir_inv,
        "settings_file": settings_file,
        "cmd": cmd,
    }


def debate_buildClaudePrompts(
    stage: str,
    debate_dir: Path,
    plugin_root: Path,
    agents: list[str],
    agent_filter: str = "",
) -> None:
    """Build debate instruction files for the given stage.

    Args:
        stage:        One of "r1", "r2", "synthesis".
        debate_dir:   Path to the debate working directory.
        plugin_root:  Path to the plugin root (CLAUDE_PLUGIN_ROOT).
        agents:       List of active agent names. If empty, read from
                      debate_dir/agents.txt (mirrors DEBATE_AGENTS env var).
        agent_filter: When non-empty, emit only that agent's file (mirrors
                      AGENT_FILTER env var).

    Raises:
        ValueError: If stage is not one of the three recognised values.
    """
    debate_dir = Path(debate_dir)
    plugin_root = Path(plugin_root)

    # Resolve agent list -- fall back to agents.txt when list is empty.
    if not agents:
        agents_file = debate_dir / "agents.txt"
        agents = [
            line
            for line in agents_file.read_text().splitlines()
            if line.strip()
        ]

    if stage == "r1":
        _debate_build_r1(stage, debate_dir, plugin_root, agents, agent_filter)
    elif stage == "r2":
        _debate_build_r2(debate_dir, agents, agent_filter)
    elif stage == "synthesis":
        _debate_build_synthesis(debate_dir, agents)
    else:
        raise ValueError(f"Unknown stage: {stage!r}")


def _debate_build_r1(
    stage: str,
    debate_dir: Path,
    plugin_root: Path,
    agents: list[str],
    agent_filter: str,
) -> None:
    """Render r1.template.md for each agent and write r1_instructions_<agent>.txt.

    The bash original delegated to render_template.py with two var overrides:
        DEBATE_DIR=<debate_dir>  OUTPUT_FILE=<debate_dir>/r1_<agent>.md
    We call the same script via subprocess to stay faithful to the original.
    """
    render = plugin_root / "common" / "scripts" / "jot" / "render_template.py"
    template = plugin_root / "skills" / "debate" / "prompts" / "r1.template.md"

    for agent in agents:
        if agent_filter and agent_filter != agent:
            continue
        output_file = debate_dir / f"r1_{agent}.md"
        instructions_file = debate_dir / f"r1_instructions_{agent}.txt"

        if render.exists():
            # Call render_template.py exactly as bash did.
            env_overrides = {
                "DEBATE_DIR": str(debate_dir),
                "OUTPUT_FILE": str(output_file),
            }
            import os
            env = os.environ.copy()
            env.update(env_overrides)
            result = subprocess.run(
                [sys.executable, str(render), str(template), "DEBATE_DIR", "OUTPUT_FILE"],
                capture_output=True,
                text=True,
                env=env,
            )
            instructions_file.write_text(result.stdout)
        else:
            # Fallback: minimal template substitution for testing without
            # the real render_template.py on disk.
            raw = template.read_text()
            rendered = raw.replace("{{DEBATE_DIR}}", str(debate_dir))
            rendered = rendered.replace("{{OUTPUT_FILE}}", str(output_file))
            instructions_file.write_text(rendered)


def _debate_build_r2(
    debate_dir: Path,
    agents: list[str],
    agent_filter: str,
) -> None:
    """Build r2 cross-critique instruction files inline (mirrors bash printf block)."""
    for agent in agents:
        if agent_filter and agent_filter != agent:
            continue
        others = [a for a in agents if a != agent]
        buf = StringIO()
        buf.write("# Debate -- Round 2: Cross-Critique\n\n")
        buf.write(f"## Your Round 1 Response\nRead from: {debate_dir}/r1_{agent}.md\n\n")
        buf.write("## Other Agents' Round 1 Responses\n")
        for other in others:
            buf.write(f"Read {other}'s response from: {debate_dir}/r1_{other}.md\n")
        buf.write("\n## Instructions\n")
        buf.write("- Identify agreement and disagreement across responses\n")
        buf.write("- Validate or challenge claims with evidence\n")
        buf.write("- Concede where others made stronger arguments\n")
        buf.write("- Raise new considerations from reading their perspectives\n")
        buf.write(
            f"\n## Output\nWrite your critique as markdown to: {debate_dir}/r2_{agent}.md\n"
            "Do not write to any other file.\n"
        )
        (debate_dir / f"r2_instructions_{agent}.txt").write_text(buf.getvalue())


def _debate_build_synthesis(debate_dir: Path, agents: list[str]) -> None:
    """Build synthesis instruction file inline (mirrors bash printf block)."""
    agents_str = " ".join(agents)
    buf = StringIO()
    buf.write("# Debate -- Round 3: Synthesis\n\n")
    buf.write(
        f"{len(agents)} agents ({agents_str}) debated across two rounds. "
        "Produce a balanced assessment.\n\n"
    )
    buf.write("## Round 1 Responses\n")
    for agent in agents:
        buf.write(f"Read {agent} R1 from: {debate_dir}/r1_{agent}.md\n")
    buf.write("\n## Round 2 Responses\n")
    for agent in agents:
        buf.write(f"Read {agent} R2 from: {debate_dir}/r2_{agent}.md\n")
    buf.write("\n## Structure\n")
    buf.write("1. **Topic**: One-line restatement\n")
    buf.write("2. **Agreement**: Where agents align\n")
    buf.write("3. **Disagreement**: Where they diverge, strongest argument per side\n")
    buf.write("4. **Strongest Arguments**: Most compelling points, attributed\n")
    buf.write("5. **Weaknesses**: Arguments successfully challenged in R2\n")
    buf.write("6. **Path Forward**: Synthesized recommendation\n")
    buf.write("7. **Confidence**: High/Medium/Low with reasoning\n")
    buf.write("8. **Open Questions**: Unresolved issues\n")
    buf.write(
        f"\n## Output\nWrite synthesis as markdown to: {debate_dir}/synthesis.md\n"
        "Do not write to any other file.\n"
    )
    (debate_dir / "synthesis_instructions.txt").write_text(buf.getvalue())


@dataclass
class ResumeFeasibility:
    """Result of a resume feasibility check.

    feasible           True iff debate can be resumed.
    updated_agents     Effective agent list. Includes 'disappeared' originals
                       whose r1_*.md AND r2_*.md outputs already exist (their
                       cached outputs will be reused at synthesis).
    unusable_agents    Originals that are unavailable AND lack complete outputs.
                       Empty when feasible is True.
    reason             Human-readable block message when not feasible, else "".
    """
    feasible: bool
    updated_agents: list[str]
    unusable_agents: list[str]
    reason: str


# debate_checkResumeFeasibility — port of bash check_resume_feasibility.
#
# Derives the original debate composition from r1_instructions_<agent>.txt
# filenames in `debate_dir`. For each original agent:
#   - If still in `available_agents`: keep, no change.
#   - If 'disappeared' (missing from `available_agents`) BUT both
#     r1_<agent>.md and r2_<agent>.md exist and are non-empty: re-add to the
#     effective agent list so synthesis includes the cached outputs.
#   - If 'disappeared' AND outputs are missing/empty: mark unusable.
# 'Appeared' agents (present in available_agents but not original) are accepted
# implicitly (they remain in the returned list) — instructions are built JIT.
#
# Returns a ResumeFeasibility. Caller decides whether to emit_block + exit;
# this function performs no I/O beyond filesystem inspection. RELAXED_COVERAGE.
def debate_checkResumeFeasibility(
    debate_dir: Path,
    available_agents: list[str],
) -> ResumeFeasibility:
    debate_dir = Path(debate_dir)

    # Discover original composition from r1_instructions_<agent>.txt files.
    original: list[str] = []
    if debate_dir.is_dir():
        for path in sorted(debate_dir.glob("r1_instructions_*.txt")):
            if not path.is_file():
                continue
            agent = path.stem[len("r1_instructions_"):]
            if agent:
                original.append(agent)

    # Work on a copy so caller's list is not mutated.
    updated = list(available_agents)
    unusable: list[str] = []

    for orig in original:
        if orig in updated:
            # Still available — nothing to do.
            continue
        # Disappeared — reusable iff both R1 and R2 outputs are non-empty.
        r1 = debate_dir / f"r1_{orig}.md"
        r2 = debate_dir / f"r2_{orig}.md"
        r1_ok = r1.is_file() and r1.stat().st_size > 0
        r2_ok = r2.is_file() and r2.stat().st_size > 0
        if r1_ok and r2_ok:
            updated.append(orig)
        else:
            unusable.append(orig)

    if unusable:
        joined = "".join(f" {a}" for a in unusable)
        reason = (
            "/debate: cannot resume, these original agents are unavailable "
            "and their outputs are incomplete:"
            f"{joined}. Fix credentials/quota and re-run '/debate <topic>', "
            "or '/debate-abort' to delete."
        )
        return ResumeFeasibility(
            feasible=False,
            updated_agents=updated,
            unusable_agents=unusable,
            reason=reason,
        )

    return ResumeFeasibility(
        feasible=True,
        updated_agents=updated,
        unusable_agents=[],
        reason="",
    )


def debate_claimSession(
    keepalive_cmd: str,
    *,
    tmux_runner: Callable[[List[str]], int] = _tmux_default_runner,
) -> str:
    """Atomically claim the lowest-unused `debate-N` tmux session.

    Args:
        keepalive_cmd: Shell command that becomes the argv of the new session's
            first window (named `main`). Typically a long-lived no-op like
            `sleep 86400` so the session persists for daemon attachment.
        tmux_runner: Injectable runner that takes argv and returns rc. The
            default invokes real tmux; tests pass a fake.

    Returns:
        The claimed session name, e.g. ``"debate-7"``.

    Raises:
        RuntimeError: If no slot in ``debate-1`` .. ``debate-999`` is free.
    """
    for n in range(1, _MAX_SESSIONS + 1):
        session = f"debate-{n}"
        argv = [
            "tmux", "new-session", "-d",
            "-s", session,
            "-x", "200",
            "-y", "60",
            "-n", "main",
            keepalive_cmd,
        ]
        if tmux_runner(argv) == 0:
            return session
    raise RuntimeError(
        f"debate_claimSession: exhausted {_MAX_SESSIONS} session slots"
    )


# YELLOW intent: scan DEBATE_DIR/.{stage}_*.lock; for each lock parse "debate:%N";
# remove the lock if the pane id is missing/malformed, the pane no longer exists in
# the tmux window, or the pane's current command differs from the agent name.

_PANE_ID_RE = re.compile(r"^debate:(%\d+)$", re.MULTILINE)


# Remove stale per-agent lock files for `stage` under `debate_dir`. A lock is stale
# when its recorded pane id is unparseable, no longer present in `window_target`,
# or whose pane is running a command other than the lock's agent name.
def debate_cleanStaleLocks(
    debate_dir: Path,
    stage: str,
    window_target: str = "",
) -> None:
    debate_dir = Path(debate_dir)
    prefix = f".{stage}_"
    locks = sorted(debate_dir.glob(f"{prefix}*.lock"))
    if not locks:
        return
    live_panes: set[str] | None = None  # lazily fetched on first lock that needs it
    for lock in locks:
        if not lock.is_file():
            continue
        # Derive agent name from filename: ".<stage>_<agent>.lock"
        agent = lock.name[len(prefix):-len(".lock")]
        # Parse "debate:%N" payload (matches bash sed regex exactly).
        try:
            payload = lock.read_text()
        except OSError:
            payload = ""
        match = _PANE_ID_RE.search(payload)
        if match is None:
            lock.unlink(missing_ok=True)
            continue
        pane_id = match.group(1)
        if live_panes is None:
            live_panes = _tmux_listLivePaneIds(window_target)
        if pane_id not in live_panes:
            lock.unlink(missing_ok=True)
            continue
        current = _tmux_paneCurrentCommand(pane_id)
        if current != agent:
            lock.unlink(missing_ok=True)


# Reads launch-time (index 0) model name for `agent` from
# ${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/models.json.
# Returns "" when the agent key is absent or its model list is empty.
# Raises KeyError if CLAUDE_PLUGIN_ROOT is unset (mirrors bash `:?` guard).
def debate_defaultModel(agent: str) -> str:
    plugin_root = os.environ["CLAUDE_PLUGIN_ROOT"]
    models_json = Path(plugin_root) / "skills" / "debate" / "scripts" / "assets" / "models.json"
    try:
        data = json.loads(models_json.read_text())
    except (OSError, json.JSONDecodeError):
        # Bash wraps jq with `hide_errors`; an unreadable/invalid file
        # surfaces as empty stdout, which probes treat as "unavailable".
        return ""
    entry = data.get(agent)
    if not isinstance(entry, list) or not entry:
        return ""
    first = entry[0]
    return first if isinstance(first, str) else ""


class DetectResult(TypedDict):
    """Aggregate result of agent detection.

    Attributes:
        available: Ordered list of usable agent names (claude always first).
        gemini_model: Model string for gemini, or "" if unavailable / sentinel.
        codex_model: Model string for codex, or "" if unavailable / sentinel.
    """
    available: list[str]
    gemini_model: str
    codex_model: str


# Sentinel returned by probes when binary+credentials exist but no model is
# configured. Marks the agent as available without populating a model name.
_PRESENT_SENTINEL = "present"


def debate_detectAvailableAgents() -> DetectResult:
    """Detect which debate agents are usable; return aggregate dict.

    Probes gemini and codex concurrently (I/O-bound: PATH + filesystem).
    Claude is always treated as available — no probe required.

    Returns:
        DetectResult with `available` list and per-agent model fields.

    Behavior parity with bash `detect_available_agents`:
        AVAILABLE_AGENTS starts with [claude]; gemini/codex appended only
        when their probe returns non-empty. Model fields stay "" if probe
        returned "" OR the "present" sentinel.
    """
    # Run both probes in parallel; ThreadPoolExecutor matches bash's two
    # backgrounded subshells joined by `wait`.
    with ThreadPoolExecutor(max_workers=2) as pool:
        gemini_future = pool.submit(debate_probeGemini)
        codex_future = pool.submit(debate_probeCodex)
        gemini_out = gemini_future.result()
        codex_out = codex_future.result()

    # Claude is always available — no probe.
    available: list[str] = ["claude"]
    gemini_model = ""
    codex_model = ""

    # Non-empty probe output ⇒ agent is usable. Capture model only when
    # the output is a real model name (not the "present" sentinel).
    if gemini_out:
        available.append("gemini")
        if gemini_out != _PRESENT_SENTINEL:
            gemini_model = gemini_out

    if codex_out:
        available.append("codex")
        if codex_out != _PRESENT_SENTINEL:
            codex_model = codex_out

    return {
        "available": available,
        "gemini_model": gemini_model,
        "codex_model": codex_model,
    }


def debate_findMatching(repo_root: str, topic: str) -> Optional[str]:
    """Return path to most-recent Debates/<ts>/ whose topic.md byte-equals `topic` + '\\n'.

    Args:
        repo_root: Path to repository root containing Debates/ subdir.
        topic: Topic text (function appends '\\n' before comparison, mirroring
               bash `printf '%s\\n'`).

    Returns:
        Absolute-style dir path string (no trailing slash), or None if no match.
    """
    debates = Path(repo_root) / "Debates"
    if not debates.is_dir():
        return None

    # Bash compared `printf '%s\n' "$topic"` to the file via cmp -s. Replicate
    # that by appending a single newline to the query before byte-compare.
    needle = (topic + "\n").encode("utf-8", errors="surrogateescape")

    best_ts = ""
    best_dir: Optional[str] = None
    for entry in debates.iterdir():
        if not entry.is_dir():
            continue
        topic_md = entry / "topic.md"
        if not topic_md.is_file():
            continue
        try:
            haystack = topic_md.read_bytes()
        except OSError:
            continue
        if haystack != needle:
            continue
        ts = entry.name
        # Lexicographic comparison matches bash `[[ "$ts" > "$match_ts" ]]`.
        if ts > best_ts:
            best_ts = ts
            best_dir = str(entry)

    return best_dir


def debate_initAgentModels(env: Mapping[str, str] | None = None) -> dict[str, dict[str, str]]:
    """Build initial agent-model state for a debate.

    Returns a fresh mapping of:
        {
            "CURRENT_MODEL": {agent: model_or_empty, ...},
            "TRIED_MODELS":  {agent: model_or_empty, ...},
        }
    seeded from `env` (defaults to os.environ). Mirrors bash ${VAR:-}: an
    unset env var becomes "".
    """
    # Read os.environ lazily so monkeypatch.setenv works for callers omitting env.
    src: Mapping[str, str] = os.environ if env is None else env

    state: dict[str, dict[str, str]] = {
        "CURRENT_MODEL": {a: "" for a in _AGENTS},
        "TRIED_MODELS": {a: "" for a in _AGENTS},
    }

    for agent, var in _AGENT_ENV_VAR.items():
        seed = src.get(var, "") or ""
        state["CURRENT_MODEL"][agent] = seed
        state["TRIED_MODELS"][agent] = seed

    return state


def debate_initHookContext(stdin: IO[str] | None = None) -> dict[str, Any]:
    """Initialise the debate hook context.

    Reads hook JSON from `stdin` (or `sys.stdin` if not provided) and returns
    a dict with the following keys (matching the bash globals):

        SCRIPTS_DIR     - $CLAUDE_PLUGIN_ROOT/skills/debate/scripts
        LOG_FILE        - $DEBATE_LOG_FILE or $CLAUDE_PLUGIN_DATA/debate-log.txt
        INPUT           - raw stdin text
        CWD             - JSON .cwd, fallback to os.getcwd()
        TRANSCRIPT_PATH - JSON .transcript_path, "" if absent
        REPO_ROOT       - git toplevel for CWD, "" if not in a repo

    Raises RuntimeError if CLAUDE_PLUGIN_ROOT or CLAUDE_PLUGIN_DATA is unset
    (mirrors bash `: "${VAR:?...}"` guard).
    """
    # Required env vars (bash `:?` semantics).
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        raise RuntimeError("debate plugin env not set: CLAUDE_PLUGIN_ROOT")
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data:
        raise RuntimeError("debate plugin env not set: CLAUDE_PLUGIN_DATA")

    scripts_dir = str(Path(plugin_root) / "skills" / "debate" / "scripts")

    # LOG_FILE: env override wins; otherwise default under plugin data dir.
    log_file = os.environ.get("DEBATE_LOG_FILE") or str(
        Path(plugin_data) / "debate-log.txt"
    )
    # `mkdir -p "$(dirname "$LOG_FILE")"` (errors hidden in bash; we ignore).
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Read raw stdin (preserve exactly, matches bash $(cat) semantics).
    src = stdin if stdin is not None else sys.stdin
    raw_input = src.read()

    # Parse JSON; tolerate empty / malformed input by treating as no fields.
    try:
        payload = json.loads(raw_input) if raw_input.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    cwd = payload.get("cwd") or os.getcwd()
    transcript_path = payload.get("transcript_path") or ""

    # `git -C "$CWD" rev-parse --show-toplevel`, swallow failure -> "".
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        repo_root = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, FileNotFoundError):
        repo_root = ""

    return {
        "SCRIPTS_DIR": scripts_dir,
        "LOG_FILE": log_file,
        "INPUT": raw_input,
        "CWD": str(cwd),
        "TRANSCRIPT_PATH": str(transcript_path),
        "REPO_ROOT": repo_root,
    }


def debate_launch(
    *,
    scripts_dir: Path | None = None,
    plugin_root: Path | None = None,
    _debate_main_fn: object = None,
    _is_darwin: bool | None = None,
    _terminal_running_fn: object = None,
    _launch_terminal_fn: object = None,
) -> None:
    """Entry point for the debate-orchestrator subcommand.

    Resolves SCRIPTS_DIR and PLUGIN_ROOT, optionally ensures Terminal.app is
    running on Darwin (fire-and-forget), then delegates to debate_main().

    Args:
        scripts_dir: Override for the directory containing this script.
            Defaults to the real __file__ parent.
        plugin_root: Override for the plugin root (three levels up from
            scripts_dir). Defaults to computed value.
        _debate_main_fn: Injectable debate_main for testing.
        _is_darwin: Injectable OS check for testing (None = use platform).
        _terminal_running_fn: Injectable pgrep probe for testing.
        _launch_terminal_fn: Injectable Terminal.app launch for testing.
    """
    # Step 1: resolve paths (mirrors bash SCRIPTS_DIR / PLUGIN_ROOT logic).
    if scripts_dir is None:
        scripts_dir = Path(__file__).resolve().parent
    if plugin_root is None:
        plugin_root = (scripts_dir / ".." / ".." / "..").resolve()

    # Export to environment so debate_main and its callees can read them.
    os.environ.setdefault("PLUGIN_ROOT", str(plugin_root))

    # Step 2: Darwin Terminal.app guard (no-op on non-Darwin or already running).
    # DEBATE_SKIP_TERMINAL_CHECK=1 short-circuits the entire macOS guard so
    # tests / dry-runs never spawn Terminal.app or pgrep. Mirrors JOT_SKIP_LAUNCH.
    skip_terminal_check = os.environ.get("DEBATE_SKIP_TERMINAL_CHECK") == "1"
    is_darwin = (platform.system() == "Darwin") if _is_darwin is None else _is_darwin

    if is_darwin and not skip_terminal_check:
        from common.scripts.util_lib import (
            _terminal_launchBackground as _default_launch_terminal,
            _terminal_running as _default_terminal_running,
        )
        terminal_running_fn = _terminal_running_fn or _default_terminal_running
        launch_terminal_fn = _launch_terminal_fn or _default_launch_terminal
        if not terminal_running_fn():
            launch_terminal_fn()

    # Step 3: delegate all real work.
    main_fn = _debate_main_fn or debate_main
    main_fn()


def debate_launchAgent(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    launch_cmd: str,
    ready_marker: str,
    debate_dir: str,
    timeout: int = 120,
) -> bool:
    """Launch a debate agent inside *pane_id* and wait for it to become ready.

    Mirrors bash ``launch_agent pane_id stage agent launch_cmd ready_marker [timeout]``.

    Args:
        pane_id:      tmux pane id (e.g. ``%7``).
        stage:        Debate stage label (``r1``, ``r2``, ``synthesis``).
        agent:        Agent name (``gemini``, ``codex``, ``claude``).
        launch_cmd:   Shell command string sent to the pane.
        ready_marker: Substring that signals the agent CLI is ready.
        debate_dir:   Path to the debate working directory.
        timeout:      Max iterations (seconds) to wait. Default 120.

    Returns:
        ``True`` on success; ``False`` on timeout (write_failed also called).
    """
    # Step 1: claim the lock file (bash: printf 'debate:%s\\n' "$pane_id" > lock)
    lock_path = Path(debate_dir) / f".{stage}_{agent}.lock"
    lock_path.write_text(f"debate:{pane_id}\n")

    # Step 2: send the launch command (bash: tmux_send_and_submit "$pane_id" "$launch_cmd")
    tmux_sendAndSubmit(pane_id, launch_cmd)

    # Step 3: poll for ready_marker (bash: while [ "$elapsed" -lt "$timeout" ])
    elapsed = 0
    while elapsed < timeout:
        # Bash: tmux capture-pane -t "$pane_id" -p -S -2000 | tr -d '\033'
        capture = tmux_capturePane(pane_id, scrollback_lines=2000)
        capture = capture.replace("\033", "")
        if ready_marker in capture:
            print(f"[orch] {stage}/{agent} ready after {elapsed}s (pane {pane_id})")
            return True
        time.sleep(1)
        elapsed += 1

    # Step 4: timeout path (bash: echo TIMEOUT >&2; write_failed ...)
    print(
        f"[orch] TIMEOUT: {stage}/{agent} not ready within {timeout}s",
        file=sys.stderr,
    )
    debate_writeFailed(stage, f"launch_agent timeout for {agent} after {timeout}s")
    return False

def debate_liveSession(debate_dir: str) -> str:
    """Return the tmux session name currently hosting the debate's panes.

    Recovers the session by reading still-live lock-file pane IDs and querying
    tmux. Self-heals across session renames; no separate session-name artifact
    to maintain. Returns empty string when no live session is found.

    Args:
        debate_dir: Path to the debate directory (e.g. Debates/<ts>_<slug>/).

    Returns:
        Session name string (e.g. "debate-1") or "" on failure.
    """
    # Glob for hidden lock files: .*.lock
    pattern = str(Path(debate_dir) / ".*.lock")
    lock_files = sorted(glob.glob(pattern))

    for lock_path in lock_files:
        # Read lock content; skip if file disappeared (TOCTOU)
        try:
            content = Path(lock_path).read_text()
        except OSError:
            continue

        # Extract pane_id from line matching "debate:%NNN"
        match = _LOCK_PANE_RE.search(content)
        if not match:
            continue
        pane_id = match.group(1)

        # Ask tmux for the session name owning this pane
        try:
            proc = subprocess.run(
                ["tmux", "display-message", "-p", "-t", pane_id, "#{session_name}"],
                capture_output=True,
                text=True,
            )
        except OSError:
            continue

        if proc.returncode != 0:
            continue

        session = proc.stdout.strip()
        if session:
            return session

    return ""


# YELLOW intent: read the models JSON, list candidate models for `agent`,
# return the first model whose name does not appear in the agent's tried
# list (comma-separated string mirroring the bash _stash format). If none
# remain, or the file/agent is missing, return None.

def debate_nextModel(
    agent: str,
    tried_models: dict[str, str],
    models_json_path: str,
) -> str | None:
    """Return the next untried model name for `agent`, or None if exhausted.

    Args:
        agent: agent key (e.g. "gemini", "codex", "claude").
        tried_models: dict mapping agent name -> comma-separated tried list
            (e.g. {"gemini": "gem-pro,gem-flash"}). Mirrors the bash
            TRIED_MODELS stash that this migration absorbs.
        models_json_path: path to assets/models.json (agent -> [models]).

    Returns:
        First model in the JSON list for `agent` not present in
        `tried_models[agent]`, or None when no untried model exists,
        the file is missing/unreadable, or the agent has no entry.
    """
    # GREEN: load JSON tolerantly; bash used `hide_errors jq` which yields
    # empty stdin on failure -> the while-read loop produced rc=1.
    try:
        with open(models_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    candidates = data.get(agent) or []
    # bash matched ",$tried," against ",$m," — i.e. exact whole-token match
    # within a comma-delimited string. Splitting and using a set replicates
    # that with O(1) membership and tolerates leading/trailing commas.
    tried_raw = tried_models.get(agent, "") or ""
    tried_set = {t for t in tried_raw.split(",") if t}

    for m in candidates:
        if not m:
            continue
        if m in tried_set:
            continue
        return m
    return None


# Probes pane scrollback for an agent-specific capacity / overload marker.
# Returns the matched marker string (truthy) on hit, or "" (falsy) when no
# marker matches or the agent is unknown. Strips ANSI ESC bytes before
# matching to mirror `tr -d '\033'` in the bash original.
def debate_paneHasCapacityError(pane_id: str, agent: str) -> str:
    markers = _MARKERS.get(agent, ())
    if not markers:
        return ""
    capture = tmux_capturePane(pane_id, scrollback_lines=200)
    # Bash strips raw ESC (\033) bytes before grep -F.
    capture = capture.replace("\033", "")
    for marker in markers:
        if not marker:
            continue
        if marker in capture:
            return marker
    return ""


def debate_probeCodex() -> str:
    """Probe codex CLI availability for the debate engine.

    Returns:
        - "" if codex is unusable (missing binary OR missing credentials).
        - The configured model name from models.json if available.
        - The literal "present" sentinel if codex is available but no model
          is configured for it in models.json.

    Behavior parity with bash `_probe_codex`:
        * `command -v codex`           -> shutil.which("codex")
        * `[[ -f $HOME/.codex/auth.json ]]` -> os.path.isfile(...)
        * `[[ -n $OPENAI_API_KEY ]]`   -> truthy env-var check
        * `_default_model codex`       -> _default_model("codex")
        * `printf '%s\\n' "${m:-present}"` -> return m or "present"
    """
    # Gate 1: binary must be on PATH.
    if shutil.which("codex") is None:
        return ""

    # Gate 2: at least one credential source must be present.
    home = os.environ.get("HOME", "")
    auth_path = os.path.join(home, ".codex", "auth.json")
    has_auth_file = bool(home) and os.path.isfile(auth_path)
    has_api_key = bool(os.environ.get("OPENAI_API_KEY", ""))
    if not (has_auth_file or has_api_key):
        return ""

    # Gate 3: resolve model name; fall back to "present" sentinel if empty.
    model: Optional[str] = debate_defaultModel("codex")
    return model if model else "present"


def debate_retryPaneWithNextModel(
    *,
    pane_index: int,
    agent: str,
    stage: str,
    current_pane_id: str,
    current_model: dict[str, str],
    tried_models: dict[str, str],
    window_target: str,
    cwd: str,
    repo_root: str,
    home: str,
    settings_file: str,
    debate_dir: str,
    models_json_path: str,
) -> str | None:
    """Rotate a capacity-exhausted agent pane to the next available model.

    Mirrors bash retry_pane_with_next_model (L2896-2919).

    Steps:
    1. Ask debate_nextModel for the next untried model for `agent`.
       If none remain, log and return None (bash return 1).
    2. Mutate `current_model` and `tried_models` dicts in-place.
    3. Kill the stale pane; open a fresh empty pane via debate_newEmptyPane.
    4. Launch the agent in the new pane; send it the stage instructions.
    5. Return the new pane id on success; None on any failure.

    Args:
        pane_index: position of this agent in the PANES array (informational).
        agent: "gemini" | "codex" | "claude".
        stage: "r1" | "r2" | "synthesis".
        current_pane_id: tmux pane id being replaced (e.g. "%10").
        current_model: mutable dict agent->current model string (mutated in-place).
        tried_models: mutable dict agent->comma-separated tried model string (mutated).
        window_target: tmux window target for retiling (e.g. "debate:0").
        cwd: working directory for the new pane.
        repo_root: repository root path.
        home: $HOME used for claude --add-dir dedup.
        settings_file: path to claude settings JSON.
        debate_dir: absolute path to the debate working directory.
        models_json_path: path to assets/models.json.

    Returns:
        New pane id string on success; None if no models left or launch failed.
    """
    # YELLOW: ask for next untried model; bail early if list exhausted.
    next_model = debate_nextModel(
        agent=agent,
        tried_models=tried_models,
        models_json_path=models_json_path,
    )
    if next_model is None:
        print(
            f"[orch] {stage}/{agent}: no remaining models; giving up",
            file=sys.stderr,
        )
        return None

    print(f"[orch] {stage}/{agent}: capacity hit -- rotating to model '{next_model}'")

    # YELLOW: update stash dicts in-place (replaces bash _stash calls).
    current_model[agent] = next_model
    existing_tried = tried_models.get(agent, "")
    tried_models[agent] = f"{existing_tried},{next_model}" if existing_tried else next_model

    # YELLOW: kill stale pane; open fresh replacement.
    _tmux_kill_pane(current_pane_id)
    new_pane = debate_newEmptyPane(window_target=window_target, cwd=cwd)
    if new_pane is None:
        print(
            f"[orch] {stage}/{agent}: debate_newEmptyPane returned None",
            file=sys.stderr,
        )
        return None

    # YELLOW: settle time after retile (mirrors bash `sleep 1`).
    time.sleep(1)

    # YELLOW: build launch command string for the updated model.
    launch_cmd = debate_agentLaunchCmd(
        agent=agent,
        current_model=current_model,
        debate_dir=debate_dir,
        cwd=cwd,
        repo_root=repo_root,
        home=home,
        settings_file=settings_file,
    )

    # YELLOW: launch agent; propagate failure as None.
    if not _debate_launch_agent(
        pane_id=new_pane,
        stage=stage,
        agent=agent,
        launch_cmd=launch_cmd,
        debate_dir=debate_dir,
    ):
        return None

    # YELLOW: send instructions file; propagate failure as None.
    if not _debate_send_prompt(
        pane_id=new_pane,
        stage=stage,
        agent=agent,
        debate_dir=debate_dir,
    ):
        return None

    return new_pane


def _debate_daemon_main_default(ctx: "DebateContext") -> None:
    """Placeholder daemon entrypoint used when debate_tmuxOrchestrator caller does not inject daemon_main_fn.

    Production callers always inject; tests inject mocks. Raising here keeps
    accidental misuse loud rather than silently no-op'ing the orchestrator.
    """
    raise NotImplementedError(
        "debate_tmuxOrchestrator requires daemon_main_fn or a migrated daemon implementation"
    )


class DebateContext:
    """Holds all mutable orchestrator state, replacing bash globals."""

    __slots__ = (
        "debate_dir",
        "session",
        "window_name",
        "settings_file",
        "cwd",
        "repo_root",
        "plugin_root",
        "window_target",
        "stage_timeout",
        "agents",
    )

    def __init__(
        self,
        debate_dir: str,
        session: str,
        window_name: str,
        settings_file: str,
        cwd: str,
        repo_root: str,
        plugin_root: str,
        debate_agents: str,
    ) -> None:
        self.debate_dir = debate_dir
        self.session = session
        self.window_name = window_name
        self.settings_file = settings_file
        self.cwd = cwd
        self.repo_root = repo_root
        self.plugin_root = plugin_root
        # Derived fields — set unconditionally, matching bash behaviour.
        self.window_target: str = f"{session}:{window_name}"
        self.stage_timeout: int = 15 * 60
        self.agents: list[str] = debate_agents.split()


def debate_tmuxOrchestrator(
    debate_dir: str,
    session: str,
    window_name: str,
    settings_file: str,
    cwd: str,
    repo_root: str,
    plugin_root: str,
    *,
    debate_agents: str = "",
    cleanup_fn: object = None,
    daemon_main_fn: object = None,
) -> int:
    """Run the debate tmux orchestrator daemon.

    Mirrors debate_tmux_orchestrator() from jot-plugin-orchestrator.sh (lines 3150-3165).

    Args:
        debate_dir: Path to the debate working directory.
        session: tmux session name.
        window_name: tmux window name within *session*.
        settings_file: Path to the debate settings JSON file.
        cwd: Working directory for agent sub-processes.
        repo_root: Absolute path to the repository root.
        plugin_root: Absolute path to the plugin root.
        debate_agents: Space-separated list of agent names (replaces $DEBATE_AGENTS env var).
            Falls back to os.environ["DEBATE_AGENTS"] when empty.
        cleanup_fn: Injectable cleanup callable (defaults to monolith/workspace cleanup).
        daemon_main_fn: Injectable daemon_main callable (defaults to monolith/workspace daemon_main).

    Returns:
        0 on success. daemon_main is expected to raise or sys.exit on fatal errors.

    Raises:
        ValueError: If session or debate_agents is empty (mirrors bash `:?` guards).
    """
    # --- Resolve injected callees (test seam) ---
    _cleanup_fn = cleanup_fn if cleanup_fn is not None else debate_cleanup
    _daemon_fn = daemon_main_fn if daemon_main_fn is not None else _debate_daemon_main_default

    # --- Guard: SESSION required (mirrors `: "${SESSION:?SESSION required}"`) ---
    if not session:
        raise ValueError("SESSION required")

    # --- Resolve DEBATE_AGENTS (env fallback mirrors bash caller convention) ---
    resolved_agents = debate_agents or os.environ.get("DEBATE_AGENTS", "")
    if not resolved_agents:
        raise ValueError("DEBATE_AGENTS env var required")

    # --- Build context (replaces bash globals) ---
    ctx = DebateContext(
        debate_dir=debate_dir,
        session=session,
        window_name=window_name,
        settings_file=settings_file,
        cwd=cwd,
        repo_root=repo_root,
        plugin_root=plugin_root,
        debate_agents=resolved_agents,
    )

    # --- Register cleanup and run daemon (mirrors `trap cleanup EXIT; daemon_main`) ---
    try:
        _daemon_fn(ctx)
    finally:
        _cleanup_fn()

    return 0


def debate_waitForOutputs(
    *,
    prefix: str,
    timeout: int,
    panes: Mapping[int, str],
    agents: Sequence[str],
    debate_dir: Path,
    pane_capacity_error: Callable[[str, str], bool],
    retry_pane: Callable[..., object],
    sleep_fn: Callable[[float], None],
    poll_interval: int = 5,
) -> tuple[bool, list[str], str | None]:
    # YELLOW intent: loop until timeout. Each cycle, scan agents; if their output
    # file exists and is non-empty, mark complete and remove their lock. Otherwise
    # check the pane for a capacity error and trigger a retry. When all agents
    # complete, return success. On timeout, return failure with the agents that
    # did complete and a timeout reason string.
    debate_dir = Path(debate_dir)
    completed: list[str] = []
    elapsed = 0

    while elapsed < timeout:
        for i, agent in enumerate(agents):
            out = debate_dir / f"{prefix}_{agent}.md"
            # Bash `[ -s "$out" ]` -> exists and non-zero size
            if out.exists() and out.stat().st_size > 0:
                lock = debate_dir / f".{prefix}_{agent}.lock"
                if lock.exists():
                    try:
                        lock.unlink()
                    except OSError:
                        pass
                if agent not in completed:
                    completed.append(agent)
                continue
            # No output yet: probe pane for capacity error, retry if so
            pane_id = panes.get(i)
            if pane_id is None:
                continue
            try:
                if pane_capacity_error(pane_id, agent):
                    try:
                        retry_pane(panes, i, agent, prefix)
                    except Exception:
                        # Bash `|| true` — swallow retry failures, keep polling
                        pass
            except Exception:
                pass

        if len(completed) == len(agents):
            return True, completed, None

        sleep_fn(poll_interval)
        elapsed += poll_interval

    reason = f"wait_for_outputs timeout after {timeout}s"
    return False, completed, reason


def debate_writeFailed(
    debate_dir: Path,
    stage: str,
    reason: str,
    agents: Iterable[str],
    *,
    pane_capture: Callable[[str], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> Path:
    """Write a `FAILED.txt` marker into ``debate_dir`` describing a debate failure.

    Bash analogue: ``write_failed`` (jot-plugin-orchestrator.sh ~L2817-2841).

    Behavior (RELAXED_COVERAGE - reconstructed from bash intent):
      * Header lines: '# debate FAILED', blank, 'stage:', 'reason:', 'timestamp:' (ISO-8601), blank.
      * Section '## missing agents' followed by one '### <agent>' subsection per agent
        whose ``<stage>_<agent>.md`` output file is missing or empty in ``debate_dir``.
      * If a lock file ``.<stage>_<agent>.lock`` exists with line ``debate:<pane_id>``,
        ``pane_capture(pane_id)`` is invoked and its result is fenced in triple backticks.
        Else writes ``(no pane captured -- lock file missing or malformed)``.
      * Atomic publish: writes to a temp file in ``debate_dir`` then renames over
        ``FAILED.txt``, so a partial file is never observable. Overwrites prior FAILED.txt.
      * Returns the final FAILED.txt path.
    """
    debate_dir = Path(debate_dir)
    if now is None:
        now = lambda: datetime.now(timezone.utc).astimezone()
    timestamp = now().replace(microsecond=0).isoformat()

    lines: list[str] = [
        "# debate FAILED",
        "",
        f"stage: {stage}",
        f"reason: {reason}",
        f"timestamp: {timestamp}",
        "",
        "## missing agents",
    ]

    for agent in agents:
        out_path = debate_dir / f"{stage}_{agent}.md"
        # Skip agents that produced non-empty output (matches bash `[ -s ... ] && continue`).
        if out_path.exists() and out_path.stat().st_size > 0:
            continue
        lines.append("")
        lines.append(f"### {agent}")
        lock_path = debate_dir / f".{stage}_{agent}.lock"
        pane_id = ""
        if lock_path.exists():
            for raw in lock_path.read_text().splitlines():
                if raw.startswith("debate:"):
                    pane_id = raw[len("debate:"):].strip()
                    break
        if pane_id:
            lines.append("```")
            capture_text = ""
            if pane_capture is not None:
                try:
                    capture_text = pane_capture(pane_id) or ""
                except Exception:
                    capture_text = ""
            if not capture_text:
                capture_text = "(pane capture unavailable)"
            # Strip trailing newline so the closing fence sits on its own line.
            lines.append(capture_text.rstrip("\n"))
            lines.append("```")
        else:
            lines.append("(no pane captured -- lock file missing or malformed)")

    body = "\n".join(lines) + "\n"

    debate_dir.mkdir(parents=True, exist_ok=True)
    # Atomic write: tempfile in same dir, then rename onto FAILED.txt.
    import tempfile
    fd, tmp_name = tempfile.mkstemp(prefix=".FAILED.txt.", dir=str(debate_dir))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        final = debate_dir / "FAILED.txt"
        tmp_path.replace(final)
        return final
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


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


def debate_anyLiveLock(debate_dir: str | os.PathLike[str]) -> bool:
    """True iff `<debate_dir>/.*.lock` references a still-live tmux pane.

    Behavior port of bash `any_live_lock`:
      * Iterate hidden `*.lock` files (glob `.*.lock`) in `debate_dir`.
      * Skip non-files (matches `[ -f "$lock" ] || continue`).
      * Extract the first line matching `^debate:(%<digits>)$`.
      * If that pane id appears in `tmux list-panes -a`, return True.
      * Return False if no lock yields a live pane.
    """
    d = Path(debate_dir)
    if not d.is_dir():
        return False

    # Collect candidate lock files: hidden, ending in `.lock`. Bash glob
    # `.*.lock` matches any file beginning with `.` and ending in `.lock`.
    locks = sorted(p for p in d.glob(".*.lock") if p.is_file())
    if not locks:
        return False

    live = _tmux_live_pane_ids()
    if not live:
        return False

    for lock in locks:
        try:
            text = lock.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _LOCK_LINE_RE.search(text)
        if not m:
            continue
        pane_id = m.group(1)
        if pane_id in live:
            return True
    return False


# Sends a "read <instructions> and perform them" prompt to the agent's pane via
# tmux_sendAndSubmit, then polls the pane (capture-pane with 2000 lines of
# scrollback, ANSI-stripped, fixed-string match against basename(instructions))
# for up to 30s in 1s ticks. Returns 0 when the marker appears, 1 on timeout.
# On timeout, logs "[orch] TIMEOUT: <stage>/<agent> did not echo prompt" to
# stderr and calls debate_writeFailed(stage, "send_prompt timeout for <agent>
# after 30s") (parity with bash write_failed). Marker derivation, scrollback
# size, poll cadence, and timeout are bash-faithful.
def debate_sendPromptToAgent(
    pane_id: str,
    stage: str,
    agent: str,
    instructions: str,
) -> int:
    rc = tmux_sendAndSubmit(pane_id, f"read {instructions} and perform them")
    # Bash sends the prompt unconditionally and ignores send_and_submit rc;
    # we preserve that behavior (no early return on rc != 0).
    _ = rc
    marker = Path(instructions).name
    elapsed = 0
    while elapsed < 30:
        captured = tmux_capturePane(pane_id, 2000)
        # Bash strips ANSI escapes via `tr -d '\033'` before fixed-string grep.
        stripped = (captured or "").replace("\x1b", "")
        if marker in stripped:
            print(f"[orch] {stage}/{agent} prompt received after {elapsed}s")
            return 0
        time.sleep(1)
        elapsed += 1
    print(
        f"[orch] TIMEOUT: {stage}/{agent} did not echo prompt",
        file=sys.stderr,
    )
    debate_writeFailed(stage, f"send_prompt timeout for {agent} after 30s")
    return 1


def _debate_launch_agent(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    launch_cmd: str,
    debate_dir: str,
) -> bool:
    return debate_launchAgent(
        pane_id=pane_id,
        stage=stage,
        agent=agent,
        launch_cmd=launch_cmd,
        ready_marker=debate_agentReadyMarker(agent),
        debate_dir=debate_dir,
    )


def _debate_send_prompt(
    *,
    pane_id: str,
    stage: str,
    agent: str,
    debate_dir: str,
) -> bool:
    instructions = f"{debate_dir}/{stage}_instructions_{agent}.txt"
    return debate_sendPromptToAgent(pane_id, stage, agent, instructions) == 0


def debate_probeGemini() -> str:
    """Probe whether the gemini agent is usable; return model name or "".

    Returns:
        - "" when gemini is unavailable (binary missing OR no credentials).
        - The configured model name (e.g., "gemini-2.5-pro") when ready.
        - "present" sentinel when binary + creds exist but no model is
          configured in models.json — caller still treats agent as usable.

    Behavior parity with bash `_probe_gemini`:
        Gate 1: `command -v gemini` must succeed.
        Gate 2: ~/.gemini/oauth_creds.json OR GEMINI_API_KEY OR GOOGLE_API_KEY.
        Gate 3: model = debate_defaultModel("gemini"); return model or "present".
    """
    # Gate 1: binary on PATH. shutil.which mirrors `command -v`.
    if shutil.which("gemini") is None:
        return ""

    # Gate 2: at least one credential source present. Order matches bash:
    # oauth file first (most common), then env vars.
    oauth_path = os.path.join(os.path.expanduser("~"), ".gemini", "oauth_creds.json")
    has_oauth = os.path.isfile(oauth_path)
    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY", ""))
    has_google_key = bool(os.environ.get("GOOGLE_API_KEY", ""))
    if not (has_oauth or has_gemini_key or has_google_key):
        return ""

    # Gate 3: resolve model name; fall back to "present" sentinel so the
    # caller's non-empty check still flags gemini as available.
    model = debate_defaultModel("gemini")
    return model if model else "present"


def debate_launchAgentsParallel(
    stage: str,
    panes: list[str],
    agents: list[str],
    debate_dir: str | Path,
) -> int:
    """Launch multiple debate agents in parallel for a given stage.

    Mirrors bash `launch_agents_parallel` (jot-plugin-orchestrator.sh ~L2962-2997).

    For each agent/pane pair:
    - If the output file (<debate_dir>/<stage>_<agent>.md) already exists and is
      non-empty, the agent is considered complete; the pane is killed and skipped.
    - If a lock file (<debate_dir>/.<stage>_<agent>.lock) exists, a live pane is
      already running; the new pane is killed and skipped.
    - Otherwise, launch the agent and send its prompt concurrently via
      ThreadPoolExecutor (replaces bash `&` + `wait`).

    Args:
        stage:      Debate stage label (e.g. "r1", "r2").
        panes:      Ordered list of tmux pane IDs; panes[i] pairs with agents[i].
        agents:     Ordered list of agent names (e.g. ["claude", "gemini"]).
        debate_dir: Directory holding stage output and instruction files.

    Returns:
        0 if all launched workers succeeded, 1 if any worker exited non-zero.

    RELAXED_COVERAGE:
        Bash signature was `launch_agents_parallel <stage> <panes_var>` where
        panes_var was an indirect array reference to a global and AGENTS/DEBATE_DIR
        were implicit globals. Python makes all four params explicit.
    """
    debate_dir = Path(debate_dir)
    t0 = time.monotonic()
    fail = 0

    # Map future -> agent name so we can log failures by name.
    future_to_agent: dict[Future[int], str] = {}

    with ThreadPoolExecutor() as pool:
        for pane_id, agent in zip(panes, agents):
            output_file = debate_dir / f"{stage}_{agent}.md"
            lock_file = debate_dir / f".{stage}_{agent}.lock"

            # Skip: output already exists (non-empty) -- agent previously completed.
            if output_file.exists() and output_file.stat().st_size > 0:
                print(f"[orch] {stage}/{agent} already complete, skipping launch", flush=True)
                tmux_killPane(pane_id)
                continue

            # Skip: lock held by a live pane -- wait_for_outputs will observe it.
            if lock_file.exists():
                print(
                    f"[orch] {stage}/{agent} lock held by live pane, "
                    "skipping launch (wait_for_outputs will observe)",
                    flush=True,
                )
                tmux_killPane(pane_id)
                continue

            # Launch agent and send prompt concurrently.
            def _worker(
                _pane_id: str = pane_id,
                _agent: str = agent,
            ) -> int:
                launch_cmd = debate_agentLaunchCmd(_agent)
                ready_marker = debate_agentReadyMarker(_agent)
                ok = debate_launchAgent(_pane_id, stage, _agent, launch_cmd, ready_marker)
                if not ok:
                    return 1
                instructions = str(debate_dir / f"{stage}_instructions_{_agent}.txt")
                return debate_sendPromptToAgent(_pane_id, stage, _agent, instructions)

            future_to_agent[pool.submit(_worker)] = agent

        # Collect results as workers complete.
        for future in as_completed(future_to_agent):
            agent_name = future_to_agent[future]
            try:
                rc = future.result()
            except Exception as exc:
                print(f"[orch] {stage}/{agent_name} worker raised: {exc}", file=sys.stderr, flush=True)
                rc = 1
            if rc != 0:
                print(f"[orch] {stage}/{agent_name} worker exited non-zero", file=sys.stderr, flush=True)
                fail = 1

    wall = time.monotonic() - t0
    n_workers = len(future_to_agent)
    print(
        f"[orch] launch_agents_parallel {stage}: {n_workers} workers, {wall:.1f}s wall",
        file=sys.stderr,
        flush=True,
    )
    return fail


def debate_newEmptyPane(window_target: str, cwd: str) -> str | None:
    """Create a new empty pane in window_target rooted at cwd.

    Mirrors bash new_empty_pane():
      1. Re-tiles the window (output/rc suppressed, matching hide_output).
      2. Splits a new pane with -c <cwd> -P -F '#{pane_id}' and no command,
         returning the new pane id (e.g. '%42') or None on failure.

    Args:
        window_target: tmux target string for the window (e.g. 'session:window').
        cwd: Working directory for the new pane (-c flag to split-window).

    Returns:
        The new pane id string on success, or None on tmux failure or empty output.
    """
    # Re-tile; rc ignored (bash used hide_output which discards rc).
    tmux_retile(window_target)

    # Split a new pane with no command (-P -F '#{pane_id}' to capture id).
    # Passing cmd="" appends an empty string to argv; tmux split-window treats
    # a trailing empty token as "no command" on macOS tmux >= 3.x.  Use the
    # inline subprocess call (same pattern as tmux_splitWorkerPane in
    # jot_plugin_orchestrator.py) for full control and to avoid passing "".
    argv = [
        "tmux", "split-window",
        "-t", window_target,
        "-c", cwd,
        "-P", "-F", "#{pane_id}",
    ]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        caller = sys._getframe(0).f_code.co_name
        cmd_str = " ".join(argv)
        combined = (result.stdout or "") + (result.stderr or "")
        print(f"[{caller}] command '{cmd_str}' failed: {combined}", file=sys.stderr)
        return None
    pane_id = (result.stdout or "").strip()
    if not pane_id:
        return None
    return pane_id


def debate_abortMain() -> int:
    """Entry point for the /debate-abort hook. Returns process exit code.

    Mirrors bash `debate_abort_main`. Returns 0 on every code path
    (matches bash `exit 0` after emit_block).
    """
    # Test action: load context (env + stdin JSON + git toplevel).
    ctx = debate_initHookContext()

    # Require jq and tmux on PATH; checkRequirements emits + exits on failure.
    hookjson_checkRequirements("debate-abort", "jq", "tmux")

    transcript_path = ctx.get("TRANSCRIPT_PATH", "") or ""
    repo_root = ctx.get("REPO_ROOT", "") or ""

    # Empty transcript_path - hook payload didn't carry one. Bail politely.
    if not transcript_path:
        print(hookjson_emitBlock("/debate-abort: no transcript_path in hook payload"))
        return 0

    # Empty repo_root - cwd isn't inside a git repo; nowhere to look.
    if not repo_root:
        print(hookjson_emitBlock("/debate-abort requires a git repository"))
        return 0

    # Scan <repo>/Debates/*/ for dirs whose invoking_transcript matches.
    debates_root = Path(repo_root) / "Debates"
    best_ts = ""
    best: Path | None = None
    if debates_root.is_dir():
        for entry in debates_root.iterdir():
            if not entry.is_dir():
                continue
            marker = entry / "invoking_transcript.txt"
            if not marker.is_file():
                continue
            try:
                stored = marker.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Bash uses `[ "$(cat ...)" = "$TRANSCRIPT_PATH" ]` which does
            # not strip; preserve exact equality.
            if stored != transcript_path:
                continue
            ts = entry.name
            # Bash `[[ "$ts" > "$best_ts" ]]` is locale string comparison;
            # Python str > str is lexicographic by Unicode code point. For
            # ASCII timestamp basenames this matches expected behavior.
            if ts > best_ts:
                best_ts = ts
                best = entry

    if best is None:
        print(hookjson_emitBlock("/debate-abort: no debate found in this conversation"))
        return 0

    # If any lock file references a live tmux pane, refuse to delete.
    if debate_anyLiveLock(str(best)):
        live = debate_liveSession(str(best)) or "<unknown>"
        print(hookjson_emitBlock(
            f"/debate-abort: debate is running. to force-kill: "
            f"tmux kill-session -t {live}"
        ))
        return 0

    # Happy path: tear down the debate dir tree and report.
    shutil.rmtree(best, ignore_errors=False)
    print(hookjson_emitBlock(f"/debate-abort: deleted {best}"))
    return 0


def debate_startOrResume(
    *,
    debate_dir: str | Path,
    available_agents: list[str],
    resuming: bool,
    cwd: str,
    repo_root: str,
    settings_file: str,
    log_file: str,
    plugin_root: str,
    gemini_model: str,
    codex_model: str,
) -> None:
    """Start or resume a debate orchestration session.

    Mirrors debate_start_or_resume() from the bash original:
    1. Detect composition drift when resuming.
    2. Build missing per-stage instruction files (r1 / r2 / synthesis).
    3. Build the Claude command via debate_buildClaudeCmd.
    4. Claim a tmux session (debate-N); exit 0 with an error block on failure.
    5. Apply session-scoped tmux options and name the keepalive pane.
    6. Launch the daemon detached via Popen(start_new_session=True).
    7. Spawn a terminal if needed.
    8. Emit the final /debate <verb> block.
    """
    debate_dir = Path(debate_dir)
    window_name = "main"

    # Detect composition drift (resume path only).
    composition_drifted = False
    if resuming:
        original_agents: set[str] = set()
        for f in debate_dir.glob("r1_instructions_*.txt"):
            stem = f.stem
            agent_name = stem[len("r1_instructions_"):]
            original_agents.add(agent_name)
        if original_agents != set(available_agents):
            composition_drifted = True

    # Build missing per-stage instruction files.
    agents_joined = " ".join(available_agents)

    for agent in available_agents:
        r1_path = debate_dir / f"r1_instructions_{agent}.txt"
        if not r1_path.exists():
            debate_buildClaudePrompts(
                stage="r1",
                debate_dir=str(debate_dir),
                plugin_root=plugin_root,
                debate_agents=agents_joined,
                agent_filter=agent,
            )

    for agent in available_agents:
        r2_path = debate_dir / f"r2_instructions_{agent}.txt"
        if not r2_path.exists():
            debate_buildClaudePrompts(
                stage="r2",
                debate_dir=str(debate_dir),
                plugin_root=plugin_root,
                debate_agents=agents_joined,
                agent_filter=agent,
            )

    synthesis_path = debate_dir / "synthesis_instructions.txt"
    if not synthesis_path.exists():
        debate_buildClaudePrompts(
            stage="synthesis",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_joined,
            agent_filter=None,
        )

    # Build the Claude command.
    debate_buildClaudeCmd(
        cwd=cwd,
        repo_root=repo_root,
        log_file=log_file,
    )

    # Claim a tmux session.
    keepalive_cmd = (
        "exec sh -c 'trap \"\" INT HUP TERM; "
        "printf \"[debate keepalive]\\n\"; exec tail -f /dev/null'"
    )
    session = debate_claimSession(keepalive_cmd=keepalive_cmd)
    if not session:
        print(hookjson_emitBlock(
            "/debate: could not claim debate-<N> session (1000 already in use)"
        ))
        sys.exit(0)

    # Apply session-scoped tmux options and name the keepalive pane.
    _tmux_set = [
        ["tmux", "set-option", "-t", session, "remain-on-exit", "off"],
        ["tmux", "set-option", "-t", session, "mouse", "on"],
        ["tmux", "set-option", "-t", session, "pane-border-status", "top"],
        ["tmux", "set-option", "-t", session, "pane-border-format", " #{pane_title} "],
    ]
    for cmd in _tmux_set:
        subprocess.run(cmd, stderr=subprocess.DEVNULL)

    pane_title = f"keepalive:{debate_dir.name}"
    subprocess.run(
        ["tmux", "select-pane", "-t", f"{session}:{window_name}", "-T", pane_title],
        stderr=subprocess.DEVNULL,
    )

    # Launch the daemon detached (replaces bash `& disown`).
    orch_log_path = debate_dir / "orchestrator.log"
    orch_log_handle = open(orch_log_path, "a")

    daemon_env_extras = {
        "GEMINI_MODEL": gemini_model,
        "CODEX_MODEL": codex_model,
        "DEBATE_AGENTS": agents_joined,
        "COMPOSITION_DRIFTED": "1" if composition_drifted else "0",
        "SESSION": session,
    }
    daemon_env = {**os.environ, **daemon_env_extras}

    daemon_cmd = [
        "python3",
        str(Path(plugin_root) / "scripts" / "jot_plugin_orchestrator.py"),
        "debate-tmux-orchestrator",
        str(debate_dir),
        session,
        window_name,
        settings_file,
        cwd,
        repo_root,
        plugin_root,
    ]
    subprocess.Popen(
        daemon_cmd,
        stdout=orch_log_handle,
        stderr=orch_log_handle,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=daemon_env,
    )

    # Spawn a terminal if needed.
    terminal_spawnIfNeeded(
        session=session,
        log_file=log_file,
        skill="debate",
        required="yes",
    )

    # Emit the final status block.
    agents_str = ", ".join(available_agents)
    rel = f"Debates/{debate_dir.name}"
    verb = "resumed" if resuming else "spawned"
    print(hookjson_emitBlock(
        f"/debate {verb} ({agents_str}) -> {rel}/synthesis.md "
        f"(~10-30 min). View: tmux attach -t {session}"
    ))


def debate_main() -> int:
    """Hook entry-point for the /debate slash command.

    Returns 0 in all paths; failures surface via emit_block side-effects.
    """
    from datetime import datetime as _dt

    ctx = debate_initHookContext()
    log_file = ctx.get("LOG_FILE", "")
    raw_input = ctx.get("INPUT", "")
    transcript_path = ctx.get("TRANSCRIPT_PATH", "")
    repo_root = ctx.get("REPO_ROOT", "")

    hookjson_checkRequirements("debate", "jq", "python3", "tmux", "claude")

    # Fast-path: ignore inputs that don't even mention "/debate.
    if '"/debate' not in raw_input:
        return 0

    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{_dt.now().isoformat()} HOOK_INPUT {raw_input}\n")
        except OSError:
            pass

    try:
        payload = json.loads(raw_input) if raw_input else {}
    except (ValueError, TypeError):
        payload = {}
    prompt = (payload.get("prompt") or "") if isinstance(payload, dict) else ""
    prompt = prompt.lstrip()

    if not (prompt == "/debate" or prompt.startswith("/debate ")):
        return 0

    topic = prompt[len("/debate"):]
    if topic.startswith(" "):
        topic = topic[1:]

    if not topic:
        print(hookjson_emitBlock("debate: no topic provided. Usage: /debate <topic>"))
        return 0
    if not repo_root:
        print(hookjson_emitBlock("debate requires a git repository."))
        return 0

    detect_result = debate_detectAvailableAgents()
    available_agents: list[str] = list(detect_result.get("available", []))
    gemini_model: str = detect_result.get("gemini_model", "")
    codex_model: str = detect_result.get("codex_model", "")

    existing = debate_findMatching(repo_root, topic)
    resuming = False
    debate_dir: Path

    if existing:
        existing_path = Path(existing)
        if (existing_path / "synthesis.md").exists():
            print(hookjson_emitBlock(
                f"/debate: already complete, see {existing}/synthesis.md - "
                f"or 'rm -rf {existing}' to re-run"
            ))
            return 0
        if debate_anyLiveLock(existing):
            try:
                live = debate_liveSession(existing) or "<unknown>"
            except Exception:
                live = "<unknown>"
            print(hookjson_emitBlock(
                f"/debate: already running for this topic -> tmux attach -t {live}"
            ))
            return 0
        debate_dir = existing_path
        resuming = True
    else:
        if len(available_agents) < 2:
            names = " ".join(available_agents)
            print(hookjson_emitBlock(
                f"/debate: needs >=2 agents, got: {names}. "
                "All configured models for missing agents failed smoke tests. "
                "Fix credentials/quota and re-run '/debate <topic>'."
            ))
            return 0

        timestamp = _dt.now().strftime("%Y-%m-%dT%H-%M-%S")
        slug = _util_slugify(topic)
        debate_dir = Path(repo_root) / "Debates" / f"{timestamp}_{slug}"
        debate_dir.mkdir(parents=True, exist_ok=True)

        (debate_dir / "topic.md").write_text(f"{topic}\n", encoding="utf-8")
        if transcript_path:
            (debate_dir / "invoking_transcript.txt").write_text(
                f"{transcript_path}\n", encoding="utf-8"
            )

        plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
        capture_script = (
            Path(plugin_root) / "skills" / "jot" / "scripts" / "capture-conversation.py"
            if plugin_root
            else None
        )
        context_path = debate_dir / "context.md"
        if (
            transcript_path
            and Path(transcript_path).is_file()
            and capture_script is not None
            and capture_script.is_file()
        ):
            ok = False
            try:
                with context_path.open("w", encoding="utf-8") as out_fh:
                    proc = subprocess.run(
                        ["python3", str(capture_script), transcript_path],
                        stdout=out_fh,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                ok = proc.returncode == 0 and context_path.stat().st_size > 0
            except (OSError, subprocess.SubprocessError):
                ok = False
            if not ok:
                context_path.write_text("(conversation capture failed)\n", encoding="utf-8")
        else:
            context_path.write_text("(no conversation context available)\n", encoding="utf-8")

    if resuming:
        debate_checkResumeFeasibility(debate_dir, available_agents)
        failed_marker = debate_dir / "FAILED.txt"
        try:
            failed_marker.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    settings_file = os.environ.get("SETTINGS_FILE", "")
    debate_startOrResume(
        debate_dir=debate_dir,
        available_agents=available_agents,
        resuming=resuming,
        cwd=ctx.get("CWD", ""),
        repo_root=repo_root,
        settings_file=settings_file,
        log_file=log_file,
        plugin_root=os.environ.get("CLAUDE_PLUGIN_ROOT", ""),
        gemini_model=gemini_model,
        codex_model=codex_model,
    )

    return 0


def debate_retryMain() -> int:
    """Hook entry-point for the /debate-retry slash command.

    Locates the most recent debate directory in the current repo whose
    invoking_transcript.txt matches the current hook's transcript_path,
    then either reports its terminal state or resumes orchestration.
    """
    ctx = debate_initHookContext()
    transcript_path = ctx.get("TRANSCRIPT_PATH", "")
    repo_root = ctx.get("REPO_ROOT", "")
    cwd = ctx.get("CWD", "")
    log_file = ctx.get("LOG_FILE", "")

    hookjson_checkRequirements("debate-retry", "jq", "python3", "tmux", "claude")

    if not transcript_path:
        print(hookjson_emitBlock("/debate-retry: no transcript_path in hook payload"))
        return 0
    if not repo_root:
        print(hookjson_emitBlock("/debate-retry requires a git repository"))
        return 0

    debates_root = Path(repo_root) / "Debates"
    best: Path | None = None
    best_ts: str = ""

    if debates_root.is_dir():
        for entry in debates_root.iterdir():
            if not entry.is_dir():
                continue
            marker = entry / "invoking_transcript.txt"
            if not marker.is_file():
                continue
            try:
                content = marker.read_text(encoding="utf-8")
            except OSError:
                continue
            if content != transcript_path and content.rstrip("\n") != transcript_path:
                continue
            ts = entry.name
            if ts > best_ts:
                best_ts = ts
                best = entry

    if best is None:
        print(hookjson_emitBlock("/debate-retry: no debate found in this conversation"))
        return 0

    if (best / "synthesis.md").exists():
        print(hookjson_emitBlock(
            f"/debate-retry: already complete, see {best}/synthesis.md"
        ))
        return 0

    if debate_anyLiveLock(str(best)):
        try:
            live = debate_liveSession(str(best)) or "<unknown>"
        except Exception:
            live = "<unknown>"
        print(hookjson_emitBlock(
            f"/debate-retry: still running -> tmux attach -t {live}"
        ))
        return 0

    debate_dir = best
    try:
        topic = (debate_dir / "topic.md").read_text(encoding="utf-8")
    except OSError:
        topic = ""
    _ = topic
    resuming = True

    detect_result = debate_detectAvailableAgents()
    available_agents: list[str] = list(detect_result.get("available", []))
    gemini_model: str = detect_result.get("gemini_model", "")
    codex_model: str = detect_result.get("codex_model", "")

    debate_checkResumeFeasibility(debate_dir, available_agents)

    failed_marker = debate_dir / "FAILED.txt"
    try:
        failed_marker.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass

    settings_file = os.environ.get("SETTINGS_FILE", "")
    debate_startOrResume(
        debate_dir=debate_dir,
        available_agents=available_agents,
        resuming=resuming,
        cwd=cwd,
        repo_root=repo_root,
        settings_file=settings_file,
        log_file=log_file,
        plugin_root=os.environ.get("CLAUDE_PLUGIN_ROOT", ""),
        gemini_model=gemini_model,
        codex_model=codex_model,
    )

    return 0


def debate_daemonMain(
    *,
    debate_dir: str | Path,
    session: str,
    window_target: str,
    agents: list[str],
    stage_timeout: int,
    plugin_root: str,
    composition_drifted: bool = False,
) -> int:
    """Drive the full R1 -> R2 -> synthesis pipeline for a debate session.

    Returns 0 on success; 1 on any subordinate failure.
    """
    debate_dir = Path(debate_dir)

    print("========================================")
    print("[orch] DEBATE DAEMON")
    print(f"[orch] Dir:     {debate_dir}")
    print(f"[orch] Session: {session}")
    print(f"[orch] Window:  {window_target}")
    print(f"[orch] Agents:  {agents} ({len(agents)})")
    print(f"[orch] Timeout: {stage_timeout}s per stage")
    print(f"[orch] Drift:   {int(composition_drifted)}")
    print("========================================")

    debate_initAgentModels()

    if composition_drifted:
        print("[orch] composition drifted -- clearing r2_*.md, r2_instructions_*.txt, synthesis_instructions.txt")
        for pattern in ("r2_*.md", "r2_instructions_*.txt", ".r2_*.lock"):
            for f in debate_dir.glob(pattern):
                f.unlink(missing_ok=True)
        (debate_dir / "synthesis_instructions.txt").unlink(missing_ok=True)

    debate_cleanStaleLocks("r1")

    r1_panes: list[str] = []
    for _agent in agents:
        r1_panes.append(debate_newEmptyPane())

    tmux_retile(window_target)
    print(f"[orch] R1 panes: agents={agents}={r1_panes}")
    time.sleep(1)

    if debate_launchAgentsParallel("r1", r1_panes) != 0:
        return 1

    if debate_waitForOutputs("r1", stage_timeout, r1_panes) != 0:
        return 1

    for pane in r1_panes:
        tmux_killPane(pane)
    tmux_retile(window_target)
    print("[orch] R1 agent panes closed")

    debate_cleanStaleLocks("r2")

    agents_str = " ".join(agents)
    for agent in agents:
        r2_instructions = debate_dir / f"r2_instructions_{agent}.txt"
        if r2_instructions.exists():
            continue
        debate_buildClaudePrompts(
            stage="r2",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_str,
            agent_filter=agent,
        )

    r2_panes: list[str] = []
    for _agent in agents:
        r2_panes.append(debate_newEmptyPane())

    tmux_retile(window_target)
    print(f"[orch] R2 panes: agents={agents}={r2_panes}")
    time.sleep(1)

    if debate_launchAgentsParallel("r2", r2_panes) != 0:
        return 1

    if debate_waitForOutputs("r2", stage_timeout, r2_panes) != 0:
        return 1

    for pane in r2_panes:
        tmux_killPane(pane)
    tmux_retile(window_target)
    print("[orch] R2 agent panes closed")

    synthesis_md = debate_dir / "synthesis.md"
    if synthesis_md.exists() and synthesis_md.stat().st_size > 0:
        print("[orch] synthesis already complete, skipping launch; running archive step")
        debate_archive()
        print(f"[orch] DEBATE COMPLETE -- synthesis at {synthesis_md}")
        return 0

    debate_cleanStaleLocks("synthesis")

    synthesis_instructions = debate_dir / "synthesis_instructions.txt"
    if not synthesis_instructions.exists():
        debate_buildClaudePrompts(
            stage="synthesis",
            debate_dir=str(debate_dir),
            plugin_root=plugin_root,
            debate_agents=agents_str,
            agent_filter=None,
        )

    synth_pane = debate_newEmptyPane()
    tmux_retile(window_target)
    print(f"[orch] synthesis pane: {synth_pane}")
    time.sleep(1)

    launch_cmd = debate_agentLaunchCmd("claude")
    ready_marker = debate_agentReadyMarker("claude")

    if debate_launchAgent(synth_pane, "synthesis", "claude", launch_cmd, ready_marker) != 0:
        return 1

    if debate_sendPromptToAgent(synth_pane, "synthesis", "claude", str(synthesis_instructions)) != 0:
        return 1

    if shell_waitForFile(str(synthesis_md), stage_timeout) != 0:
        return 1

    tmux_killPane(synth_pane)
    tmux_retile(window_target)
    print("[orch] synthesis pane closed")

    debate_archive()
    print(f"[orch] DEBATE COMPLETE -- synthesis at {synthesis_md}")
    return 0
