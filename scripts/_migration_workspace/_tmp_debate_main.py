"""Workspace-temp module for debate_main migration.

Migrated from bash debate_main() (jot-plugin-orchestrator.sh L2567-2632)
plus init_hook_context() (L2273-2294).

SIGNATURE CHANGE (RELAXED_COVERAGE):
    Bash mutated globals (PROMPT, TOPIC, DEBATE_DIR, RESUMING, AVAILABLE_AGENTS,
    REPO_ROOT, TRANSCRIPT_PATH, LOG_FILE, CWD, INPUT). Python uses local vars
    populated from a single context dict returned by debate_initHookContext()
    and a DetectResult dict from debate_detectAvailableAgents().

PLAIN-ASCII NOTE:
    Bash source contained Unicode em-dash and right-arrow in user-facing
    strings; per project conventions we substitute ' - ' and '->' respectively.

MERGE NOTE -- WORKSPACE FALLBACK:
    The try/except import block below is a temporary workaround. When merging
    into jot_plugin_orchestrator.py, drop the except branch entirely.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Workspace-fallback imports -- REMOVE except branch on merge
# ---------------------------------------------------------------------------
try:
    from jot_plugin_orchestrator import (  # type: ignore
        debate_initHookContext,
        debate_detectAvailableAgents,
        debate_findMatching,
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
    from _tmp_debate_findMatching import debate_findMatching  # type: ignore[no-redef]
    from _tmp_debate_anyLiveLock import debate_anyLiveLock  # type: ignore[no-redef]
    from _tmp_debate_liveSession import debate_liveSession  # type: ignore[no-redef]
    from _tmp_debate_checkResumeFeasibility import debate_checkResumeFeasibility  # type: ignore[no-redef]
    from _tmp_debate_startOrResume import debate_startOrResume  # type: ignore[no-redef]
    from jot_plugin_orchestrator import (  # type: ignore[no-redef]
        hookjson_emitBlock,
        hookjson_checkRequirements,
    )


# Slug helpers - lowercase, replace non-alnum runs with '-', head 40, strip trailing '-'.
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slugify(topic: str) -> str:
    """Mirror bash: tr lower | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//'."""
    lowered = topic.lower()
    collapsed = _NON_ALNUM_RE.sub("-", lowered)
    return collapsed[:40].rstrip("-")


def debate_main() -> int:
    """Hook entry-point for the /debate slash command.

    Returns:
        0 in all paths (matches bash `exit 0` semantics; failures are surfaced
        via emit_block side-effects rather than non-zero exit).
    """
    # ------------------------------------------------------------------
    # 1. Initialise hook context. Returns a dict with SCRIPTS_DIR, LOG_FILE,
    #    INPUT, CWD, TRANSCRIPT_PATH, REPO_ROOT.
    # ------------------------------------------------------------------
    ctx = debate_initHookContext()
    log_file = ctx.get("LOG_FILE", "")
    raw_input = ctx.get("INPUT", "")
    transcript_path = ctx.get("TRANSCRIPT_PATH", "")
    repo_root = ctx.get("REPO_ROOT", "")

    # External-binary requirements check (delegates to merged helper).
    hookjson_checkRequirements("debate", "jq", "python3", "tmux", "claude")

    # ------------------------------------------------------------------
    # 2. Fast-path: ignore inputs that don't even mention "/debate.
    # ------------------------------------------------------------------
    if '"/debate' not in raw_input:
        return 0

    # Best-effort hook-input log (mirrors bash `printf ... >> $LOG_FILE`).
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat()} HOOK_INPUT {raw_input}\n")
        except OSError:
            pass

    # ------------------------------------------------------------------
    # 3. Parse the prompt out of the JSON payload, lstrip whitespace, and
    #    require a strict /debate or /debate <topic> match.
    # ------------------------------------------------------------------
    try:
        payload = json.loads(raw_input) if raw_input else {}
    except (ValueError, TypeError):
        payload = {}
    prompt = (payload.get("prompt") or "") if isinstance(payload, dict) else ""
    prompt = prompt.lstrip()

    if not (prompt == "/debate" or prompt.startswith("/debate ")):
        return 0

    # Strip prefix and one optional space.
    topic = prompt[len("/debate"):]
    if topic.startswith(" "):
        topic = topic[1:]

    if not topic:
        hookjson_emitBlock("debate: no topic provided. Usage: /debate <topic>")
        return 0
    if not repo_root:
        hookjson_emitBlock("debate requires a git repository.")
        return 0

    # ------------------------------------------------------------------
    # 4. Detect agents and look for an existing matching debate dir.
    # ------------------------------------------------------------------
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
            hookjson_emitBlock(
                f"/debate: already complete, see {existing}/synthesis.md - "
                f"or 'rm -rf {existing}' to re-run"
            )
            return 0
        if debate_anyLiveLock(existing):
            try:
                live = debate_liveSession(existing) or "<unknown>"
            except Exception:
                live = "<unknown>"
            hookjson_emitBlock(
                f"/debate: already running for this topic -> tmux attach -t {live}"
            )
            return 0
        debate_dir = existing_path
        resuming = True
    else:
        # ------------------------------------------------------------------
        # 5. Fresh debate - need at least 2 agents.
        # ------------------------------------------------------------------
        if len(available_agents) < 2:
            names = " ".join(available_agents)
            hookjson_emitBlock(
                f"/debate: needs >=2 agents, got: {names}. "
                "All configured models for missing agents failed smoke tests. "
                "Fix credentials/quota and re-run '/debate <topic>'."
            )
            return 0

        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        slug = _slugify(topic)
        debate_dir = Path(repo_root) / "Debates" / f"{timestamp}_{slug}"
        debate_dir.mkdir(parents=True, exist_ok=True)

        (debate_dir / "topic.md").write_text(f"{topic}\n", encoding="utf-8")
        if transcript_path:
            (debate_dir / "invoking_transcript.txt").write_text(
                f"{transcript_path}\n", encoding="utf-8"
            )

        # Conversation context capture via external script.
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

    # ------------------------------------------------------------------
    # 6. Resume-only feasibility gate + clear stale FAILED.txt.
    # ------------------------------------------------------------------
    if resuming:
        debate_checkResumeFeasibility(debate_dir, available_agents)
        failed_marker = debate_dir / "FAILED.txt"
        try:
            failed_marker.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    # ------------------------------------------------------------------
    # 7. Dispatch to start/resume orchestration.
    # ------------------------------------------------------------------
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
