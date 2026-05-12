"""Shared loader for background-agent permission bundles.

All four background-agent skills (/jot, /todo, /plate, /debate) read their
worker-permission config from one bundled file:

    ${CLAUDE_PLUGIN_ROOT}/assets/bg_agent_permissions.json

On first use per CLAUDE_PLUGIN_DATA the loader seeds an installed copy at:

    ${CLAUDE_PLUGIN_DATA}/bg_agent_permissions.local.json

The installed copy is what callers actually read; users can edit it to customize
worker permissions. Upgrade detection uses a sha256 sidecar with the same
semantics as claude_seedPermissions: if the user has not modified the installed
file (its sha matches the prior-default sha) and the bundled default has
changed, the installed copy is refreshed automatically.

Three target-specific entrypoints share that loader:

  bgPermissions_loadClaude(tool, env, extra_allow=None, ...) -> str
      Returns json.dumps([...]) for a Claude Code settings.json permissions.allow
      block. Substitutes ${REPO_ROOT} / ${HOME} / ${CWD} in each entry, lstrips
      the leading "/" from REPO_ROOT so it slots into "//${REPO_ROOT}/..." form.
      extra_allow is appended verbatim (no substitution) so per-invocation
      dynamic paths assembled in Python flow through unchanged.

  bgPermissions_loadGemini(tool="debate", ...) -> str
      Returns a comma-joined string for `gemini --allowed-tools '<...>'`.

  bgPermissions_loadCodex(tool="debate", ...) -> dict[str, object]
      Returns {"approval": ..., "sandbox_mode": ..., "extra_flags": [...]} for
      the caller to assemble into a `codex` CLI invocation; per-invocation
      flags (--add-dir, --model) stay in the caller.

The loader does ASCII variable substitution only - no template engine, no macro
expansion. All allow rules are written out literally in the bundled JSON.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from common.scripts.claude_lib import claude_seedPermissions

# Bundled-default location relative to ${CLAUDE_PLUGIN_ROOT}.
_BUNDLE_RELPATH = "assets/bg_agent_permissions.json"
_BUNDLE_SHA_RELPATH = "assets/bg_agent_permissions.json.sha256"

# Installed (runtime) location relative to ${CLAUDE_PLUGIN_DATA}.
_INSTALLED_NAME = "bg_agent_permissions.local.json"
_INSTALLED_PRIOR_SHA_NAME = "bg_agent_permissions.default.sha256"

# Per-skill old runtime files used before the consolidation, named here so
# bgPermissions_warnLegacyFiles can surface them in a one-line warning.
_LEGACY_RUNTIME_FILES = (
    "permissions.local.json",
    "todo-permissions.local.json",
    "debate-permissions.local.json",
)


def _resolveBundle(bundle_path: Path | None) -> tuple[Path, Path]:
    """Return (bundle_json_path, bundle_sha_path) - explicit override or
    relative to CLAUDE_PLUGIN_ROOT."""
    if bundle_path is not None:
        return bundle_path, bundle_path.with_suffix(bundle_path.suffix + ".sha256")
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        raise RuntimeError(
            "CLAUDE_PLUGIN_ROOT not set - bg_permissions_lib needs an explicit "
            "bundle_path when running outside Claude Code"
        )
    return (
        Path(plugin_root) / _BUNDLE_RELPATH,
        Path(plugin_root) / _BUNDLE_SHA_RELPATH,
    )


def _resolveInstalled() -> tuple[Path, Path]:
    """Return (installed_json_path, prior_sha_path) under CLAUDE_PLUGIN_DATA."""
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data:
        raise RuntimeError(
            "CLAUDE_PLUGIN_DATA not set - bg_permissions_lib needs that to "
            "locate the installed runtime copy"
        )
    return (
        Path(plugin_data) / _INSTALLED_NAME,
        Path(plugin_data) / _INSTALLED_PRIOR_SHA_NAME,
    )


def _seedIfNeeded(bundle_path: Path | None, log_file: str | None = None) -> Path:
    """Seed or upgrade the installed runtime file, then return its path."""
    installed_path, prior_sha_path = _resolveInstalled()
    bundle_json, bundle_sha = _resolveBundle(bundle_path)
    installed_path.parent.mkdir(parents=True, exist_ok=True)
    claude_seedPermissions(
        str(installed_path),
        str(bundle_json),
        str(bundle_sha),
        str(prior_sha_path),
        log_file,
        "bg_agent_permissions",
    )
    return installed_path


def _loadSection(
    tool: str,
    worker: str,
    bundle_path: Path | None,
    log_file: str | None,
) -> dict:
    """Read installed runtime file, return the <tool>_permissions.<worker>
    sub-block. Falls back to the bundled file when the installed copy is
    missing or unreadable, so a fresh install does not deadlock waiting for
    its own seed."""
    installed_path = _seedIfNeeded(bundle_path, log_file=log_file)
    try:
        data = json.loads(installed_path.read_text())
    except (OSError, json.JSONDecodeError):
        bundle_json, _ = _resolveBundle(bundle_path)
        data = json.loads(bundle_json.read_text())

    key = f"{tool}_permissions"
    if key not in data:
        raise KeyError(f"bg_agent_permissions: no '{key}' section in {installed_path}")
    section = data[key]
    if worker not in section:
        raise KeyError(
            f"bg_agent_permissions: no '{worker}' sub-key under '{key}' in {installed_path}"
        )
    return section[worker]


def _substituteTemplates(items: Iterable[str], env: dict[str, str]) -> list[str]:
    """ASCII variable substitution on each entry. ${REPO_ROOT} is lstripped of
    its leading '/' so rules slot into the '//${REPO_ROOT}/...' form Claude
    Code's permission matcher expects."""
    repo_root = (env.get("REPO_ROOT") or "").lstrip("/")
    home = env.get("HOME", "")
    cwd = env.get("CWD", "")
    out: list[str] = []
    for item in items:
        out.append(
            item.replace("${CWD}", cwd)
                .replace("${HOME}", home)
                .replace("${REPO_ROOT}", repo_root)
        )
    return out


def bgPermissions_loadClaude(
    tool: str,
    env: dict[str, str],
    extra_allow: list[str] | None = None,
    bundle_path: Path | None = None,
    log_file: str | None = None,
) -> str:
    """Return the JSON-stringified allow array for a Claude background worker."""
    section = _loadSection(tool, "claude", bundle_path, log_file)
    expanded = _substituteTemplates(section.get("allow", []), env)
    if extra_allow:
        expanded.extend(extra_allow)
    return json.dumps(expanded)


def bgPermissions_loadGemini(
    tool: str = "debate",
    bundle_path: Path | None = None,
    log_file: str | None = None,
) -> str:
    """Return the comma-joined string for `gemini --allowed-tools '<...>'`."""
    section = _loadSection(tool, "gemini", bundle_path, log_file)
    return ",".join(section.get("allowed_tools", []))


def bgPermissions_loadCodex(
    tool: str = "debate",
    bundle_path: Path | None = None,
    log_file: str | None = None,
) -> dict[str, object]:
    """Return the Codex flag config: approval, sandbox_mode, extra_flags."""
    section = _loadSection(tool, "codex", bundle_path, log_file)
    return {
        "approval": section.get("approval", "never"),
        "sandbox_mode": section.get("sandbox_mode", "workspace-write"),
        "extra_flags": list(section.get("extra_flags", [])),
    }


def bgPermissions_warnLegacyFiles(log_file: str | None = None) -> list[str]:
    """If any pre-consolidation per-skill runtime files exist under
    CLAUDE_PLUGIN_DATA, log a one-line warning naming them so the user can
    hand-port any genuine local edits. Returns the list of detected files
    (mostly for test assertions). Caller decides whether to invoke this."""
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not plugin_data:
        return []
    found = [
        str(Path(plugin_data) / name)
        for name in _LEGACY_RUNTIME_FILES
        if (Path(plugin_data) / name).is_file()
    ]
    if found and log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as fh:
                fh.write(
                    "[bg_agent_permissions] legacy per-skill runtime files "
                    f"detected (not migrated automatically): {', '.join(found)}. "
                    "Hand-port any genuine local edits into "
                    f"{Path(plugin_data) / _INSTALLED_NAME} or delete to silence.\n"
                )
        except OSError:
            pass
    return found
