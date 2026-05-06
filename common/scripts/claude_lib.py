from pathlib import Path
from datetime import datetime, timezone
import shutil

from common.scripts.util_lib import (
    _readFirstToken,
    _sha256File
)

# Writes a Claude settings JSON file (permissions.allow + hooks block) and returns the `claude --settings ... --add-dir ...` command string with trailing newline.
def claude_buildCmd(
    settings_out: str,
    allow_json: str,
    hooks_json_file: str,
    cwd: str,
    *extra_dirs: str,
) -> str:
    hooks_json = Path(hooks_json_file).read_text()
    settings_body = (
        "{\n"
        '  "permissions": {\n'
        f'    "allow": {allow_json}\n'
        "  },\n"
        f'  "hooks": {hooks_json}\n'
        "}\n"
    )
    Path(settings_out).write_text(settings_body)
    cmd = f"claude --settings '{settings_out}' --add-dir '{cwd}'"
    for extra in extra_dirs:
        cmd += f" --add-dir '{extra}'"
    return cmd + "\n"

# Appends a single timestamped log line ("<ISO-8601> <prefix>: <message>") to log_file. No-op when log_file is None/empty. Write errors are swallowed (matches bash 2>/dev/null || true). Bash function read $log_file/$log_prefix via dynamic scoping; Python takes them as explicit params (Risk #4).
def claude_permseedLog(message: str, log_file: str | None, log_prefix: str = "plugin") -> None:
    if not log_file:
        return
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    line = f"{timestamp} {log_prefix}: {message}\n"
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        return

# Seeds or upgrades an installed permissions config from the bundled default; preserves user edits and records/logs default SHA transitions.
def claude_seedPermissions(
    installed: str,
    default: str,
    default_sha_file: str,
    prior_sha_file: str,
    log_file: str | None = None,
    log_prefix: str = "plugin",
) -> None:
    if not Path(default).is_file() or not Path(default_sha_file).is_file():
        claude_permseedLog(
            f"bundled permissions default missing at {default} - cannot seed",
            log_file,
            log_prefix,
        )
        return

    current_default_sha = _readFirstToken(default_sha_file)

    if not Path(installed).is_file():
        shutil.copyfile(default, installed)
        with open(prior_sha_file, "w", encoding="utf-8") as fh:
            fh.write(f"{current_default_sha}\n")
        claude_permseedLog(
            f"seeded {installed} from bundled default (sha={current_default_sha})",
            log_file,
            log_prefix,
        )
        return

    try:
        installed_sha = _sha256File(installed)
    except OSError:
        installed_sha = ""

    prior_sha = _readFirstToken(prior_sha_file) if Path(prior_sha_file).is_file() else ""

    if installed_sha == current_default_sha:
        return

    if prior_sha and installed_sha == prior_sha:
        shutil.copyfile(default, installed)
        with open(prior_sha_file, "w", encoding="utf-8") as fh:
            fh.write(f"{current_default_sha}\n")
        claude_permseedLog(
            f"upgraded {installed} to new bundled default "
            f"(was {prior_sha}, now {current_default_sha})",
            log_file,
            log_prefix,
        )
        return

    if prior_sha != current_default_sha:
        claude_permseedLog(
            f"{installed} is user-edited; bundled default updated - diff manually. "
            f"installed_sha={installed_sha} prior_sha={prior_sha} "
            f"current_default_sha={current_default_sha}",
            log_file,
            log_prefix,
        )
        with open(prior_sha_file, "w", encoding="utf-8") as fh:
            fh.write(f"{current_default_sha}\n")
