# hook-json.sh — shared Claude Code hook JSON helpers.
#
# This file is meant to be `source`d. It exports:
#   emit_block <reason>       Print {"decision":"block","reason":...} to stdout.
#                             Uses jq when available; falls back to hand-rolled
#                             JSON so the requirements check can still report
#                             that jq is missing.
#   check_requirements <prefix> <cmd...>
#                             Probe each command; if any are missing, emit a
#                             block reason listing them with install hints,
#                             then exit 0. Known commands (jq, python3, tmux,
#                             claude) get canonical install hints; unknown
#                             commands are listed by name.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 3).

emit_block() {
  local reason="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg r "$reason" '{decision:"block", reason:$r}'
  else
    local esc="${reason//\\/\\\\}"   # backslashes first
    esc="${esc//\"/\\\"}"            # then quotes
    printf '{"decision":"block","reason":"%s"}\n' "$esc"
  fi
}

_hookjson_install_hint() {
  case "$1" in
    jq)       echo "jq (brew install jq)" ;;
    python3)  echo "python3 (brew install python)" ;;
    tmux)     echo "tmux (brew install tmux)" ;;
    claude)   echo "claude (https://claude.com/claude-code)" ;;
    *)        echo "$1" ;;
  esac
}

check_requirements() {
  local prefix="$1"; shift
  local -a missing=()
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$(_hookjson_install_hint "$cmd")")
  done
  if [ ${#missing[@]} -eq 0 ]; then
    return 0
  fi
  local list="" item
  for item in "${missing[@]}"; do
    if [ -z "$list" ]; then list="$item"; else list="$list, $item"; fi
  done
  emit_block "${prefix} needs: $list — install and retry."
  exit 0
}
