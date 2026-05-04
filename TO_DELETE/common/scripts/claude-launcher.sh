# claude-launcher.sh — generalized per-invocation `claude` launcher.
#
# This file is meant to be `source`d. It exports one function:
#
#   build_claude_cmd <settings_out> <allow_json> <hooks_json_file> <cwd> <add_dir...>
#
#   Arguments:
#     settings_out    Path to write the generated settings.json.
#     allow_json      A JSON array literal (string) of expanded permissions.
#                     Callers typically generate this via
#                     common/scripts/jot/expand_permissions.py.
#     hooks_json_file Path to a file containing the JSON object for the
#                     "hooks" key in settings.json (e.g. {"SessionStart":
#                     [...], "Stop": [...], "SessionEnd": [...]}).
#                     Caller is responsible for constructing this file
#                     with correct absolute paths to any hook scripts.
#     cwd             Launcher cwd (becomes the first --add-dir).
#     add_dir...      Zero or more additional --add-dir paths.
#
#   Prints the resolved `claude ...` command string to stdout. The caller
#   typically captures this into a variable and passes it to tmux.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 7).
# No longer assumes jot-specific hook scripts, permissions location, or
# SessionStart/Stop/SessionEnd wiring — callers supply those.

build_claude_cmd() {
  local settings_out="$1"
  local allow_json="$2"
  local hooks_json_file="$3"
  local cwd="$4"
  shift 4

  local hooks_json
  hooks_json=$(cat "$hooks_json_file")

  cat > "$settings_out" <<JSON
{
  "permissions": {
    "allow": $allow_json
  },
  "hooks": $hooks_json
}
JSON

  local cmd="claude --settings '$settings_out' --add-dir '$cwd'"
  local extra
  for extra in "$@"; do
    cmd="$cmd --add-dir '$extra'"
  done
  printf '%s\n' "$cmd"
}
