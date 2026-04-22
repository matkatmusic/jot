#!/bin/bash
# debate.sh — function definitions for the /debate hook.
# Sourced by debate-orchestrator.sh. No side effects when sourced.
#
# debate_main() parses the hook JSON, sets up Debates/<ts>_<slug>/, seeds
# Claude settings (permissions only — no lifecycle hooks, unlike jot), then
# forks debate-tmux-orchestrator.sh as a background daemon. The hook returns
# immediately; the daemon drives R1 → R2 → synthesis in its own time.

# ── Provider detection (3-stage: binary + credentials + smoke test) ──

# Bash-native timeout (macOS lacks GNU timeout)
_run_with_timeout() {
  local secs=$1; shift
  "$@" &
  local pid=$!
  ( sleep "$secs" && kill "$pid" 2>/dev/null ) &
  local watchdog=$!
  wait "$pid" 2>/dev/null
  local rc=$?
  kill "$watchdog" 2>/dev/null
  wait "$watchdog" 2>/dev/null
  return $rc
}

# Probe which gemini model responds within 30s. The default model is the
# first choice; on failure (typically quota exhaustion, HTTP 429) we retry
# with `-m gemini-3-flash-preview`, a lighter model that sits on a separate
# quota tier. Echoes the `-m` value on success (empty string = use default),
# returns rc=1 if neither candidate answers.
debate_gemini_working_model() {
  if _run_with_timeout 30 gemini -p "Reply with exactly: ok" >/dev/null 2>&1; then
    printf ''
    return 0
  fi
  if _run_with_timeout 30 gemini -m gemini-3-flash-preview -p "Reply with exactly: ok" >/dev/null 2>&1; then
    printf 'gemini-3-flash-preview'
    return 0
  fi
  return 1
}

detect_available_agents() {
  AVAILABLE_AGENTS=(claude)

  if command -v gemini >/dev/null 2>&1; then
    if [[ -f "$HOME/.gemini/oauth_creds.json" ]] || [[ -n "${GEMINI_API_KEY:-}" ]] || [[ -n "${GOOGLE_API_KEY:-}" ]]; then
      local gemini_model
      if gemini_model=$(debate_gemini_working_model); then
        AVAILABLE_AGENTS+=(gemini)
        # Persist the chosen model for the tmux orchestrator. Empty content
        # means "use CLI default"; the orchestrator branches on file non-emptiness.
        printf '%s' "$gemini_model" > "$DEBATE_DIR/gemini_model.txt"
        if [ -n "$gemini_model" ]; then
          hide_errors printf '%s debate: gemini primary model unavailable, using fallback %s\n' \
            "$(date -Iseconds)" "$gemini_model" >> "$LOG_FILE"
        fi
      else
        hide_errors printf '%s debate: gemini smoke test failed (primary + fallback)\n' "$(date -Iseconds)" >> "$LOG_FILE"
      fi
    else
      hide_errors printf '%s debate: gemini no auth credentials\n' "$(date -Iseconds)" >> "$LOG_FILE"
    fi
  fi

  if command -v codex >/dev/null 2>&1; then
    if [[ -f "$HOME/.codex/auth.json" ]] || [[ -n "${OPENAI_API_KEY:-}" ]]; then
      if _run_with_timeout 30 codex exec "Reply with exactly: ok" --full-auto >/dev/null 2>&1; then
        AVAILABLE_AGENTS+=(codex)
      else
        hide_errors printf '%s debate: codex smoke test failed\n' "$(date -Iseconds)" >> "$LOG_FILE"
      fi
    else
      hide_errors printf '%s debate: codex no auth credentials\n' "$(date -Iseconds)" >> "$LOG_FILE"
    fi
  fi
}

# ── Claude settings builder ──
# Writes a settings.json granting the debate permissions. No SessionStart /
# Stop / SessionEnd hooks — the daemon drives Claude interactively via
# tmux send-keys, so no lifecycle instrumentation is needed.
debate_build_claude_cmd() {
  TMPDIR_INV=$(mktemp -d /tmp/debate.XXXXXX)
  SETTINGS_FILE="$TMPDIR_INV/settings.json"

  local permissions_file="${CLAUDE_PLUGIN_DATA}/debate-permissions.local.json"
  local default_file="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/permissions.default.json"
  local default_sha_file="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/permissions.default.json.sha256"
  local prior_sha_file="${CLAUDE_PLUGIN_DATA}/debate-permissions.default.sha256"
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  permissions_seed "$permissions_file" "$default_file" "$default_sha_file" "$prior_sha_file" "$LOG_FILE" "debate"

  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "${CLAUDE_PLUGIN_ROOT}/common/scripts/jot/expand_permissions.py" "$permissions_file")

  # Empty hooks object — build_claude_cmd requires a file but we have no hooks.
  local hooks_json_file="$TMPDIR_INV/hooks.json"
  printf '{}\n' > "$hooks_json_file"

  build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT" > /dev/null
}

# ── Main entry point ──

debate_main() {
  : "${CLAUDE_PLUGIN_ROOT:?debate plugin env not set}"
  : "${CLAUDE_PLUGIN_DATA:?debate plugin env not set}"

  local SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${DEBATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/debate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"

  INPUT=$(cat)
  case "$INPUT" in
    *'"/debate'*) ;;
    *) exit 0 ;;
  esac

  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"
  check_requirements "debate" jq python3 tmux claude

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
  PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"
  if [[ "$PROMPT" != "/debate" && "$PROMPT" != "/debate "* ]]; then
    exit 0
  fi

  TOPIC="${PROMPT#/debate}"
  TOPIC="${TOPIC# }"
  if [ -z "$TOPIC" ]; then
    emit_block "debate: no topic provided. Usage: /debate <topic>"
    exit 0
  fi

  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "debate requires a git repository."
    exit 0
  fi

  # Guard against subshell execution: with `set -E`, this trap is inherited
  # into every `$(...)` command substitution. If a command inside
  # invoke_command's `$(...)` fails, the trap fires there first — emitting the
  # block JSON into the captured output, then `exit 0` would make the parent
  # think the command succeeded. Skip the emit-and-exit-0 path when
  # BASH_SUBSHELL > 0; just propagate the original rc so the parent's trap
  # can handle it cleanly.
  trap 'rc=$?; [ "$BASH_SUBSHELL" -gt 0 ] && exit "$rc"; emit_block "debate crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  # Detect which agents are installed, authenticated, and responsive.
  # Skipping this in favor of a hardcoded list means the hook reports
  # success while the daemon hangs forever waiting on a missing agent's
  # TUI — invisible to the caller. 3-stage validation (binary present +
  # credentials + 30s smoke test) is defined above at detect_available_agents.
  detect_available_agents
  if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
    emit_block "debate requires at least 2 agents. Found: ${AVAILABLE_AGENTS[*]}. Install or authenticate gemini or codex."
    exit 0
  fi

  # Create debate directory with slug
  local slug
  slug=$(printf '%s' "$TOPIC" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//')
  DEBATE_DIR="$REPO_ROOT/Debates/${TIMESTAMP}_${slug}"
  mkdir -p "$DEBATE_DIR"

  # Write topic + agents manifest
  printf '%s\n' "$TOPIC" > "$DEBATE_DIR/topic.md"
  printf '%s\n' "${AVAILABLE_AGENTS[@]}" > "$DEBATE_DIR/agents.txt"

  # Extract conversation context from calling session (same as jot)
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  local capture_script="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/capture-conversation.py"
  if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] && [ -f "$capture_script" ]; then
    hide_errors python3 "$capture_script" "$TRANSCRIPT_PATH" > "$DEBATE_DIR/context.md"
  else
    printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"
  fi

  # Build R1 instruction files
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
    bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"

  # Build claude settings (permissions only, no hooks)
  debate_build_claude_cmd

  # Ensure tmux session and window with keepalive pane
  local window_name="debate-${TIMESTAMP}_${slug}"
  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate keepalive]\n"; exec tail -f /dev/null'\'''
  tmux_ensure_session debate "$window_name" "$CWD" "$keepalive_cmd" 'debate: keepalive'
  local window_target="debate:${window_name}"

  # Detached sessions default to 80x24; give the window room for multiple panes.
  hide_errors tmux resize-window -t "$window_target" -x 200 -y 60

  # Fork the daemon (drives R1 → R2 → synthesis). Hook exits immediately.
  local orch_log="$DEBATE_DIR/orchestrator.log"
  bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
      "$DEBATE_DIR" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
      >> "$orch_log" 2>&1 </dev/null &
  disown

  spawn_terminal_if_needed "debate" "$LOG_FILE" "debate"

  local agents_str="${AVAILABLE_AGENTS[*]}"
  emit_block "/debate spawned (${agents_str// /, }) → Debates/${TIMESTAMP}_${slug}/synthesis.md (~10-30 min). View: tmux attach -t debate"
  exit 0
}
