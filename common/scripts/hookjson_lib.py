
import shutil
import sys
import json

# Emit a Claude Code hook JSON block decision: {"decision":"block","reason":<reason>}.
def hookjson_emitBlock(reason: str) -> str:
    return json.dumps({"decision": "block", "reason": reason})

_INSTALL_HINTS: dict[str, str] = {
    "jq": "jq (brew install jq)",
    "python3": "python3 (brew install python)",
    "tmux": "tmux (brew install tmux)",
    "claude": "claude (https://claude.com/claude-code)",
}


# Returns a human-readable install hint for a known dependency; falls back to the bare command name.
def hookjson_installHint(cmd: str) -> str:
    return _INSTALL_HINTS.get(cmd, cmd)

# Probes commands; on any missing, emits a block-decision JSON listing them with install hints, then sys.exit(0).
def hookjson_checkRequirements(prefix: str, *cmds: str) -> None:
    missing: list[str] = []
    for cmd in cmds:
        if shutil.which(cmd) is None:
            missing.append(hookjson_installHint(cmd))
    if not missing:
        return None
    joined = ", ".join(missing)
    payload = hookjson_emitBlock(f"{prefix} needs: {joined} - install and retry.")
    print(payload)
    sys.exit(0)
