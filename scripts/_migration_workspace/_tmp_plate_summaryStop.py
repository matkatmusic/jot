"""GREEN: plate_summaryStop — Python migration of bash `plate_summary_stop`.

Per-invocation SessionEnd hook for the spawned plate-summary agent. Reads the
agent's output file path and forwards repo/branch/output_file to
`common/scripts/plate/cli.py set-plate-summary`, which performs the trailer
rewrite via rebase-reword. Always returns 0 so a hook failure cannot block
session shutdown.

Migrated from /Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/jot-plugin-orchestrator.sh
(bash function plate_summary_stop @ lines 3810-3849). RELAXED_COVERAGE: no
paired bash _tests existed; behavior tests authored from intent + docstring.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the workspace dir is importable when this module is run/imported
# directly (mirrors the standard temp-file header for migration workspace).
sys.path.insert(0, str(Path(__file__).parent))


def plate_summaryStop(repo: str, branch: str, output_file: str) -> int:
    """Forward agent summary to plate cli; append audit line; never raise.

    Args:
        repo: absolute path to the repo whose plate branch is being summarised.
        branch: parent branch name (the plate branch is `<branch>-plate`).
        output_file: absolute path the spawned agent wrote its summary to.

    Returns:
        0 always. A non-zero return would let SessionEnd treat this hook as
        failed and surface noise to the user; the bash original exits 0
        unconditionally and we preserve that contract.
    """
    # Guard: any missing required arg -> silent no-op (mirrors bash early exit).
    if not repo or not branch or not output_file:
        return 0

    # Guard: agent never wrote the file -> nothing to forward.
    if not Path(output_file).is_file():
        return 0

    # Resolve cli.py: bash uses `cd "$(dirname "$0")/../../.." && pwd`. In the
    # Python migration the equivalent is the repo root above scripts/. We
    # locate it relative to this module so the function works whether installed
    # in the plugin tree or run from the migration workspace.
    repo_root = Path(__file__).resolve().parents[2]
    cli_path = repo_root / "common" / "scripts" / "plate" / "cli.py"

    # Resolve the audit log location with the same precedence as bash:
    #   1) $PLATE_LOG_FILE     (test/override hook)
    #   2) <repo>/.plate/plate-log.txt
    #   3) $CLAUDE_PLUGIN_DATA/plate-log.txt or ~/.claude/plugins/data/plate-jot-dev/plate-log.txt
    plate_log_env = os.environ.get("PLATE_LOG_FILE", "")
    if plate_log_env:
        log_file = Path(plate_log_env)
    elif Path(repo).is_dir():
        log_file = Path(repo) / ".plate" / "plate-log.txt"
    else:
        plugin_data = os.environ.get(
            "CLAUDE_PLUGIN_DATA",
            str(Path.home() / ".claude" / "plugins" / "data" / "plate-jot-dev"),
        )
        log_file = Path(plugin_data) / "plate-log.txt"

    # Best-effort mkdir of log dir; bash uses `2>/dev/null || true`.
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Run the cli command. Bash captures stdout+stderr together (`2>&1`) and
    # always continues (`|| true`). We mirror that with check=False and a
    # broad except, since this hook must never raise.
    out_text = ""
    try:
        result = subprocess.run(
            ["python3", str(cli_path), "set-plate-summary", repo, branch, output_file],
            capture_output=True,
            text=True,
            check=False,
        )
        out_text = (result.stdout or "") + (result.stderr or "")
    except Exception as exc:  # noqa: BLE001 — hook must never propagate.
        out_text = f"<exception: {exc}>"

    # Append one audit line. Bash format:
    #   "<ts> plate-summary-stop repo=<repo> branch=<branch> out=<OUT>"
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"{ts} plate-summary-stop repo={repo} branch={branch} out={out_text.strip()}\n"
    try:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        # Bash silences log-write failures with `2>/dev/null || true`.
        pass

    return 0
