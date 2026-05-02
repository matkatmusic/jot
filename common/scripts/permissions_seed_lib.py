"""Three-state seeder for a user-editable permissions allowlist.

Public API:
    permissionsSeed(installed, default, default_sha_file,
                    prior_sha_file, log_file=None, log_prefix="plugin")

Three states (six branches):
    1) `default` or `default_sha_file` missing
       -> log warning, return.
    2) `installed` missing
       -> copy `default` -> `installed`; record current sha to
          `prior_sha_file`; log "seeded".
    3) sha(installed) == current_default_sha
       -> no-op.
    4) sha(installed) == prior_sha (user never edited)
       -> overwrite `installed` with `default`; update
          `prior_sha_file`; log "upgraded".
    5) sha(installed) != prior_sha AND prior_sha != current_default
       -> log "user-edited"; update `prior_sha_file` only;
          `installed` is preserved.
    6) `log_file` empty / unwritable
       -> logging silently dropped; function still returns normally.

Migrated from common/scripts/permissions-seed.sh per
MIGRATION_TO_PYTHON.md. Uses Python idioms (hashlib, pathlib,
explicit `is_file()` branches, narrow `try/except OSError` for
log writes) so none of the bash-era workarounds (`|| true`,
`2>/dev/null`, `|| echo ""`) are needed.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_LOG_PREFIX = "plugin"


def _isoTimestamp() -> str:
    """ISO-8601 timestamp with timezone, matching `date -Iseconds`."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _readFirstToken(path: Path) -> str:
    """First whitespace-delimited token from a file. Empty if missing/empty."""
    if not path.is_file():
        return ""
    text = path.read_text()
    parts = text.split()
    return parts[0] if parts else ""


def _appendLog(log_file: Path | None, prefix: str, msg: str) -> None:
    """Best-effort append. Silent when log_file is None or unwritable."""
    if log_file is None:
        return
    line = f"{_isoTimestamp()} {prefix}: {msg}\n"
    try:
        with log_file.open("a") as fh:
            fh.write(line)
    except OSError:
        # Branch 6: logging is best-effort. Read-only mount, missing
        # parent dir, etc. all collapse to "drop the line and continue."
        pass


def permissionsSeed(
    installed: Path | str,
    default: Path | str,
    default_sha_file: Path | str,
    prior_sha_file: Path | str,
    log_file: Path | str | None = None,
    log_prefix: str = DEFAULT_LOG_PREFIX,
) -> None:
    """Seed or upgrade a user-editable allowlist file.

    See module docstring for the three-state contract. Always returns
    None; logging is best-effort.
    """
    installed = Path(installed)
    default = Path(default)
    default_sha_file = Path(default_sha_file)
    prior_sha_file = Path(prior_sha_file)
    log_path = Path(log_file) if log_file else None

    # Branch 1: bundled default missing -> log and return.
    if not default.is_file() or not default_sha_file.is_file():
        _appendLog(
            log_path,
            log_prefix,
            f"bundled permissions default missing at {default} - cannot seed",
        )
        return

    current_default_sha = _readFirstToken(default_sha_file)

    # Branch 2: first install -> copy default + record sha.
    if not installed.is_file():
        shutil.copy(default, installed)
        prior_sha_file.write_text(current_default_sha + "\n")
        _appendLog(
            log_path,
            log_prefix,
            f"seeded {installed} from bundled default (sha={current_default_sha})",
        )
        return

    installed_sha = _sha256(installed)
    prior_sha = _readFirstToken(prior_sha_file)

    # Branch 3: installed already matches current default -> no-op.
    if installed_sha == current_default_sha:
        return

    # Branch 4: untouched install (sha matches what we last shipped) ->
    # overwrite with new default, advance prior_sha.
    if prior_sha and installed_sha == prior_sha:
        shutil.copy(default, installed)
        prior_sha_file.write_text(current_default_sha + "\n")
        _appendLog(
            log_path,
            log_prefix,
            f"upgraded {installed} to new bundled default "
            f"(was {prior_sha}, now {current_default_sha})",
        )
        return

    # Branch 5: user has edited installed AND a new default has shipped
    # since prior_sha was recorded -> preserve installed; advance
    # prior_sha so we don't log on every subsequent invocation.
    if prior_sha != current_default_sha:
        _appendLog(
            log_path,
            log_prefix,
            f"{installed} is user-edited; bundled default updated - "
            f"diff manually. installed_sha={installed_sha} "
            f"prior_sha={prior_sha} current_default_sha={current_default_sha}",
        )
        prior_sha_file.write_text(current_default_sha + "\n")
