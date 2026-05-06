"""Workspace-temp module for debateRetry_main migration.

Migrated from bash debate_retry_main() (jot-plugin-orchestrator.sh L2636-2673)
plus init_hook_context() (L2273-2294).

SIGNATURE CHANGE (RELAXED_COVERAGE):
    Bash mutated globals (TRANSCRIPT_PATH, REPO_ROOT, DEBATE_DIR, TOPIC,
    RESUMING, AVAILABLE_AGENTS, CWD, LOG_FILE, INPUT, SETTINGS_FILE,
    CLAUDE_PLUGIN_ROOT, GEMINI_MODEL, CODEX_MODEL). Python uses local vars
    populated from a single context dict returned by debate_initHookContext()
    and a DetectResult dict from debate_detectAvailableAgents(). Returns int
    rather than calling sys.exit (caller decides on process exit).

PLAIN-ASCII NOTE:
    Bash source contained Unicode right-arrow (U+2192) in the still-running
    message; per project conventions we substitute plain ASCII '->'.

LEXICOGRAPHIC PICK:
    Bash used `[[ "$ts" > "$best_ts" ]]` to keep the largest basename. Python
    mirror: track max() over basenames of matching `<repo>/Debates/*/` dirs
    whose `invoking_transcript.txt` content equals TRANSCRIPT_PATH.

MERGE NOTE -- WORKSPACE FALLBACK:
    The try/except import block below is a temporary workaround. When merging
    into jot_plugin_orchestrator.py, drop the except branch entirely.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from the production scripts/ tree alongside workspace stubs.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Workspace-fallback imports -- REMOVE except branch on merge
# ---------------------------------------------------------------------------
try:
    from jot_plugin_orchestrator import (  # type: ignore
        debate_initHookContext,
        debate_detectAvailableAgents,
        debate_anyLiveLock,
        debate_liveSession,
        debate_checkResumeFeasibility,
        debate_startOrResume,
        hookjson_emitBlock,
        hookjson_checkRequirements,
    )
except ImportError:
    from _tmp_debate_initHookContext import debate_initHookContext  # type: ignore[no-redef]
    from _tmp_debate_detectAvailableAgents import debate_detectAvailableAgents  # type: ignore[no-redef]
    from _tmp_debate_anyLiveLock import debate_anyLiveLock  # type: ignore[no-redef]
    from _tmp_debate_liveSession import debate_liveSession  # type: ignore[no-redef]
    from _tmp_debate_checkResumeFeasibility import debate_checkResumeFeasibility  # type: ignore[no-redef]
    from _tmp_debate_startOrResume import debate_startOrResume  # type: ignore[no-redef]
    from jot_plugin_orchestrator import (  # type: ignore[no-redef]
        hookjson_emitBlock,
        hookjson_checkRequirements,
    )


def debateRetry_main() -> int:
    """Hook entry-point for the /debate-retry slash command.

    Locates the most recent debate directory in the current repo whose
    invoking_transcript.txt matches the current hook's transcript_path,
    then either reports its terminal state or resumes orchestration.

    Returns:
        0 in all paths (matches bash `exit 0` semantics; failures are
        surfaced via emit_block side-effects rather than non-zero exit).
    """
    # ------------------------------------------------------------------
    # 1. Initialise hook context. Returns a dict with SCRIPTS_DIR, LOG_FILE,
    #    INPUT, CWD, TRANSCRIPT_PATH, REPO_ROOT.
    # ------------------------------------------------------------------
    ctx = debate_initHookContext()
    transcript_path = ctx.get("TRANSCRIPT_PATH", "")
    repo_root = ctx.get("REPO_ROOT", "")
    cwd = ctx.get("CWD", "")
    log_file = ctx.get("LOG_FILE", "")

    # External-binary requirements check (delegates to merged helper).
    hookjson_checkRequirements("debate-retry", "jq", "python3", "tmux", "claude")

    # ------------------------------------------------------------------
    # 2. Guards: empty transcript_path or empty repo_root => emit + return.
    # ------------------------------------------------------------------
    if not transcript_path:
        hookjson_emitBlock("/debate-retry: no transcript_path in hook payload")
        return 0
    if not repo_root:
        hookjson_emitBlock("/debate-retry requires a git repository")
        return 0

    # ------------------------------------------------------------------
    # 3. Walk <repo_root>/Debates/*/. For each containing
    #    invoking_transcript.txt whose content equals transcript_path,
    #    track the lexicographically max basename. Bash compared by
    #    basename via `[[ "$ts" > "$best_ts" ]]`.
    # ------------------------------------------------------------------
    debates_root = Path(repo_root) / "Debates"
    best: Path | None = None
    best_ts: str = ""

    if debates_root.is_dir():
        for entry in debates_root.iterdir():
            # Bash glob matched directories only; mirror with is_dir().
            if not entry.is_dir():
                continue
            marker = entry / "invoking_transcript.txt"
            if not marker.is_file():
                continue
            try:
                content = marker.read_text(encoding="utf-8")
            except OSError:
                continue
            # Bash used `cat` with no trim; transcripts may have a trailing
            # newline from echo/printf '%s\n'. Compare both raw and stripped.
            if content != transcript_path and content.rstrip("\n") != transcript_path:
                continue
            ts = entry.name
            if ts > best_ts:
                best_ts = ts
                best = entry

    if best is None:
        hookjson_emitBlock("/debate-retry: no debate found in this conversation")
        return 0

    # ------------------------------------------------------------------
    # 4. Terminal-state checks: synthesis already exists, or live tmux pane.
    # ------------------------------------------------------------------
    if (best / "synthesis.md").exists():
        hookjson_emitBlock(
            f"/debate-retry: already complete, see {best}/synthesis.md"
        )
        return 0

    if debate_anyLiveLock(str(best)):
        try:
            live = debate_liveSession(str(best)) or "<unknown>"
        except Exception:
            live = "<unknown>"
        hookjson_emitBlock(
            f"/debate-retry: still running -> tmux attach -t {live}"
        )
        return 0

    # ------------------------------------------------------------------
    # 5. Resume path: read topic, detect agents, gate on feasibility,
    #    clear stale FAILED.txt, dispatch to start/resume orchestration.
    # ------------------------------------------------------------------
    debate_dir = best
    # topic.md may be missing in degenerate states; mirror bash `cat` which
    # would emit empty + nonzero rc but continue (set -e is not tripped here
    # since orchestrator wraps the call in trap-ERR with exit 0).
    try:
        topic = (debate_dir / "topic.md").read_text(encoding="utf-8")
    except OSError:
        topic = ""
    # `topic` is consumed by debate_startOrResume callees via debate_dir on disk.
    # Locally retained only to mirror bash's TOPIC export shape; suppress unused.
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

    import os
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
