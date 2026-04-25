#!/bin/bash
# debate.sh — function definitions for the /debate hook.
# Sourced by debate-orchestrator.sh. No side effects when sourced.
#
# debate_main() parses the hook JSON, sets up Debates/<ts>_<slug>/, seeds
# Claude settings (permissions only — no lifecycle hooks, unlike jot), then
# forks debate-tmux-orchestrator.sh as a background daemon. The hook returns
# immediately; the daemon drives R1 → R2 → synthesis in its own time.

# ── Provider detection (3-stage: binary + credentials + smoke test) ──

# Bash-native timeout (macOS lacks GNU timeout).
# Uses SIGTERM followed by SIGKILL because agent CLIs (notably gemini) trap
# SIGTERM and keep running to completion — causing the bash-level `wait` to
# block for the agent's natural runtime (200s+) rather than the requested
# timeout. SIGKILL cannot be caught, so the process dies within ~1s.
_run_with_timeout() {
  local secs=$1; shift
  "$@" &
  local pid=$!
  (
    sleep "$secs"
    hide_errors kill -TERM "$pid"
    sleep 1
    hide_errors kill -KILL "$pid"
  ) &
  local watchdog=$!
  hide_errors wait "$pid"
  local rc=$?
  hide_errors kill -KILL "$watchdog"
  hide_errors wait "$watchdog"
  return $rc
}

# Atomically claim the lowest-unused `debate-N` session. `tmux new-session -d`
# is the atomic primitive: it returns non-zero on name collision, so looping
# over N until one call succeeds is race-free across concurrent /debate hooks.
# Avoids the TOCTOU window of a has-session pre-check. First window named
# `main`; $1 (keepalive_cmd) becomes that window's argv. Prints claimed
# session name on stdout. Bound is a safety cap on pathological tmux state.
debate_claim_session() {
  local keepalive_cmd="$1"
  local n=1 session
  while [ "$n" -lt 1000 ]; do
    session="debate-$n"
    if hide_errors tmux new-session -d -s "$session" \
         -x 200 -y 60 \
         -n main \
         "$keepalive_cmd"; then
      printf '%s\n' "$session"
      return 0
    fi
    n=$((n + 1))
  done
  return 1
}

# _first_fallback_model <agent>
# Reads the first model name from model-fallbacks.json for <agent>. Empty
# string if no models listed. Used by detect_available_agents to assign a
# model without running a live smoke test — because at least one agent CLI
# (gemini) can take 200-400s to respond to a trivial `-p "Reply…"` probe,
# making live smoke tests unusable here. launch_agent's 120s readiness
# timeout catches broken agents at R1 spawn time instead.
_first_fallback_model() {
  local fallbacks_json="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts/assets/model-fallbacks.json"
  local agent="$1"
  hide_errors jq -r --arg a "$agent" '.[$a][0] // ""' "$fallbacks_json"
}

# _probe_gemini / _probe_codex — run inside backgrounded subshells. Presence
# check only (binary + credentials). Empty stdout → unavailable. Non-empty
# stdout → the fallback model name (or "" if no models configured).
_probe_gemini() {
  hide_output hide_errors command -v gemini || return 0
  [[ -f "$HOME/.gemini/oauth_creds.json" ]] \
    || [[ -n "${GEMINI_API_KEY:-}" ]] \
    || [[ -n "${GOOGLE_API_KEY:-}" ]] \
    || return 0
  # Non-empty model name OR literal "present" sentinel so the outer `-s` check
  # treats gemini as available even when no fallback model is configured.
  local m; m=$(_first_fallback_model gemini)
  printf '%s\n' "${m:-present}"
}
_probe_codex() {
  hide_output hide_errors command -v codex || return 0
  [[ -f "$HOME/.codex/auth.json" ]] || [[ -n "${OPENAI_API_KEY:-}" ]] || return 0
  local m; m=$(_first_fallback_model codex)
  printf '%s\n' "${m:-present}"
}

detect_available_agents() {
  AVAILABLE_AGENTS=(claude)
  GEMINI_MODEL=""
  CODEX_MODEL=""

  local tmpdir
  tmpdir=$(mktemp -d /tmp/debate-detect.XXXXXX)
  ( _probe_gemini > "$tmpdir/gemini" ) &
  ( _probe_codex  > "$tmpdir/codex"  ) &
  wait
  local m
  if [ -s "$tmpdir/gemini" ]; then
    AVAILABLE_AGENTS+=(gemini)
    m=$(cat "$tmpdir/gemini")
    [ "$m" = "present" ] || GEMINI_MODEL="$m"
  fi
  if [ -s "$tmpdir/codex" ]; then
    AVAILABLE_AGENTS+=(codex)
    m=$(cat "$tmpdir/codex")
    [ "$m" = "present" ] || CODEX_MODEL="$m"
  fi
  rm -rf "$tmpdir"
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

# ── Shared hook setup ──

# init_hook_context
# Reads hook JSON from stdin and sets shared globals (INPUT, CWD,
# TRANSCRIPT_PATH, REPO_ROOT, SCRIPTS_DIR, LOG_FILE). Sources the
# common libs. Called by debate_main, debate_retry_main, debate_abort_main.
init_hook_context() {
  : "${CLAUDE_PLUGIN_ROOT:?debate plugin env not set}"
  : "${CLAUDE_PLUGIN_DATA:?debate plugin env not set}"
  SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/skills/debate/scripts"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  LOG_FILE="${DEBATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/debate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/platform.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/tmux-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/claude-launcher.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/permissions-seed.sh"

  INPUT=${INPUT:-$(cat)}
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
}

# find_matching_debate <repo_root> <topic>
# Prints the matching debate dir path, or empty if none. Uses cmp so
# multi-line topics and trailing-newline edge cases work correctly.
# Most-recent dir (lexicographic timestamp) wins.
find_matching_debate() {
  local repo_root="$1" topic="$2"
  local dir match_ts="" best=""
  for dir in "$repo_root"/Debates/*/; do
    [ -f "$dir/topic.md" ] || continue
    if printf '%s\n' "$topic" | hide_errors cmp -s - "$dir/topic.md"; then
      local ts; ts=$(basename "$dir")
      if [[ "$ts" > "$match_ts" ]]; then
        match_ts="$ts"
        best="${dir%/}"
      fi
    fi
  done
  printf '%s' "$best"
}

# check_resume_feasibility
# Expects $DEBATE_DIR and AVAILABLE_AGENTS set. Permissive resume check:
#   - Appeared agents (in AVAILABLE_AGENTS but not in original composition)
#     are accepted — they'll be added to the debate, their instructions get
#     built just-in-time, and they run at each stage.
#   - Disappeared agents (in original composition but not in AVAILABLE_AGENTS)
#     are OK only if their R1 AND R2 outputs already exist; those outputs are
#     reused and the agent is re-added to AVAILABLE_AGENTS so synthesis
#     includes them. Otherwise hard-fail: cannot run a missing agent.
# Original composition is derived from r1_instructions_<agent>.txt filenames.
check_resume_feasibility() {
  local -a original=()
  local f agent
  for f in "$DEBATE_DIR"/r1_instructions_*.txt; do
    [ -f "$f" ] || continue
    agent=$(basename "$f" .txt)
    agent="${agent#r1_instructions_}"
    original+=("$agent")
  done

  local orig unusable=""
  for orig in "${original[@]}"; do
    case " ${AVAILABLE_AGENTS[*]} " in
      *" $orig "*) continue ;;
    esac
    # Disappeared — reusable iff outputs are complete.
    if [ -s "$DEBATE_DIR/r1_${orig}.md" ] && [ -s "$DEBATE_DIR/r2_${orig}.md" ]; then
      AVAILABLE_AGENTS+=("$orig")
    else
      unusable="$unusable $orig"
    fi
  done

  if [ -n "$unusable" ]; then
    emit_block "/debate: cannot resume, these original agents are unavailable and their outputs are incomplete:${unusable}. Fix credentials/quota and re-run '/debate <topic>', or '/debate-abort' to delete."
    exit 0
  fi
}

# any_live_lock <debate_dir> → 0 if a live lock exists, 1 otherwise.
any_live_lock() {
  local dir="$1" lock pane_id
  for lock in "$dir"/.*.lock; do
    [ -f "$lock" ] || continue
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    [ -n "$pane_id" ] && hide_errors tmux list-panes -a -F '#{pane_id}' | grep -qFx "$pane_id" && return 0
  done
  return 1
}

# live_debate_session <debate_dir> → prints the session currently hosting the
# debate's panes, empty on failure. Since debate-N is chosen at claim time and
# not stored on disk, we recover it by asking tmux which session owns any
# still-live lock-file pane id. Self-healing across session renames; no
# separate session-name artifact to keep in sync.
live_debate_session() {
  local dir="$1" lock pane_id session
  for lock in "$dir"/.*.lock; do
    [ -f "$lock" ] || continue
    pane_id=$(sed -n 's|^debate:\(%[0-9]*\)$|\1|p' "$lock")
    [ -n "$pane_id" ] || continue
    session=$(hide_errors tmux display-message -p -t "$pane_id" '#{session_name}') || continue
    [ -n "$session" ] && { printf '%s\n' "$session"; return 0; }
  done
  return 1
}

# debate_start_or_resume
# Shared body invoked by fresh-start and resume paths. Caller sets:
# TOPIC, DEBATE_DIR, RESUMING (0|1), AVAILABLE_AGENTS, GEMINI_MODEL,
# CODEX_MODEL, SCRIPTS_DIR, CWD, REPO_ROOT, LOG_FILE.
debate_start_or_resume() {
  # One tmux session per invocation; always a single window named `main`.
  # Session name `debate-N` is chosen at claim time below.
  local window_name="main"

  # Snapshot composition BEFORE any rebuild modifies r1_instructions_*.txt.
  # The daemon uses this to detect drift (appeared/disappeared agents) and
  # reset R2 artifacts so every agent critiques the correct roster.
  local composition_drifted=0
  if [ "$RESUMING" = 1 ]; then
    local -a _original=()
    local _f _aa
    for _f in "$DEBATE_DIR"/r1_instructions_*.txt; do
      [ -f "$_f" ] || continue
      _aa=$(basename "$_f" .txt); _aa="${_aa#r1_instructions_}"
      _original+=("$_aa")
    done
    local _orig_sorted _new_sorted
    _orig_sorted=$(printf '%s\n' "${_original[@]}" | sort -u | tr '\n' ' ')
    _new_sorted=$(printf '%s\n' "${AVAILABLE_AGENTS[@]}" | sort -u | tr '\n' ' ')
    [ "$_orig_sorted" != "$_new_sorted" ] && composition_drifted=1
  fi

  # Per-stage instruction build. Only missing files get built; full composition
  # provides context. R2 and synthesis templates reference r1_<agent>.md /
  # r2_<agent>.md only as paths (debate-build-prompts.sh never reads their
  # content), so they can be built at /debate-start time — surfacing any
  # template error here via emit_block rather than 15 min later in the daemon.
  # Composition drift (resume path) still rebuilds r2/synth inside daemon_main.
  local _a
  for _a in "${AVAILABLE_AGENTS[@]}"; do
    [ -f "$DEBATE_DIR/r1_instructions_${_a}.txt" ] && continue
    DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" AGENT_FILTER="$_a" \
      bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
  done
  for _a in "${AVAILABLE_AGENTS[@]}"; do
    [ -f "$DEBATE_DIR/r2_instructions_${_a}.txt" ] && continue
    DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" AGENT_FILTER="$_a" \
      bash "$SCRIPTS_DIR/debate-build-prompts.sh" r2 "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
  done
  if [ ! -f "$DEBATE_DIR/synthesis_instructions.txt" ]; then
    DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" \
      bash "$SCRIPTS_DIR/debate-build-prompts.sh" synthesis "$DEBATE_DIR" "${CLAUDE_PLUGIN_ROOT}"
  fi

  debate_build_claude_cmd

  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate keepalive]\n"; exec tail -f /dev/null'\'''
  local session
  session=$(debate_claim_session "$keepalive_cmd") || {
    emit_block "/debate: could not claim debate-<N> session (1000 already in use)"; exit 0
  }
  # Session-scoped options that tmux_ensure_session used to set. Kept here
  # so the pane-title border (which `select-pane -T` writes to) actually
  # renders, and so mouse works for the attached Terminal.
  hide_errors tmux set-option -t "$session" remain-on-exit off
  hide_errors tmux set-option -t "$session" mouse on
  hide_errors tmux set-option -t "$session" pane-border-status top
  hide_errors tmux set-option -t "$session" pane-border-format ' #{pane_title} '
  # Title the keepalive pane with the debate's directory basename so
  # live_debate_session (and human observers attaching via `tmux attach`)
  # can tell at a glance which debate the session hosts, even after
  # debate-N numbers get reused once a session dies.
  hide_errors tmux select-pane -t "${session}:main" -T "keepalive:$(basename "$DEBATE_DIR")"

  local orch_log="$DEBATE_DIR/orchestrator.log"
  GEMINI_MODEL="$GEMINI_MODEL" CODEX_MODEL="$CODEX_MODEL" \
  DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" COMPOSITION_DRIFTED="$composition_drifted" \
  SESSION="$session" \
    bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
      "$DEBATE_DIR" "$session" "$window_name" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "${CLAUDE_PLUGIN_ROOT}" \
      >> "$orch_log" 2>&1 </dev/null &
  disown

  spawn_terminal_if_needed "$session" "$LOG_FILE" "debate"

  local agents_str="${AVAILABLE_AGENTS[*]}"
  local rel="Debates/$(basename "$DEBATE_DIR")"
  local verb="spawned"
  [ "$RESUMING" = 1 ] && verb="resumed"
  emit_block "/debate ${verb} (${agents_str// /, }) → ${rel}/synthesis.md (~10-30 min). View: tmux attach -t ${session}"
}

# ── Main entry point ──

debate_main() {
  init_hook_context
  check_requirements "debate" jq python3 tmux claude

  case "$INPUT" in *'"/debate'*) ;; *) exit 0 ;; esac
  hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"

  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
  PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"
  [[ "$PROMPT" == "/debate" || "$PROMPT" == "/debate "* ]] || exit 0

  TOPIC="${PROMPT#/debate}"
  TOPIC="${TOPIC# }"
  [ -z "$TOPIC" ] && { emit_block "debate: no topic provided. Usage: /debate <topic>"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "debate requires a git repository."; exit 0; }

  trap 'rc=$?; emit_block "debate crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  detect_available_agents

  local existing
  existing=$(find_matching_debate "$REPO_ROOT" "$TOPIC")
  RESUMING=0
  if [ -n "$existing" ]; then
    if [ -f "$existing/synthesis.md" ]; then
      emit_block "/debate: already complete, see $existing/synthesis.md — or 'rm -rf $existing' to re-run"; exit 0
    fi
    if any_live_lock "$existing"; then
      local live; live=$(live_debate_session "$existing") || live="<unknown>"
      emit_block "/debate: already running for this topic → tmux attach -t ${live}"; exit 0
    fi
    DEBATE_DIR="$existing"
    RESUMING=1
  else
    if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
      emit_block "/debate: needs ≥2 agents, got: ${AVAILABLE_AGENTS[*]}. All fallback models for missing agents failed smoke tests. Fix credentials/quota and re-run '/debate <topic>'."
      exit 0
    fi
    local TIMESTAMP slug
    TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)
    slug=$(printf '%s' "$TOPIC" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//')
    DEBATE_DIR="$REPO_ROOT/Debates/${TIMESTAMP}_${slug}"
    mkdir -p "$DEBATE_DIR"
    printf '%s\n' "$TOPIC" > "$DEBATE_DIR/topic.md"
    [ -n "$TRANSCRIPT_PATH" ] && printf '%s\n' "$TRANSCRIPT_PATH" > "$DEBATE_DIR/invoking_transcript.txt"

    local capture_script="${CLAUDE_PLUGIN_ROOT}/skills/jot/scripts/capture-conversation.py"
    if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ] && [ -f "$capture_script" ]; then
      if ! hide_errors python3 "$capture_script" "$TRANSCRIPT_PATH" > "$DEBATE_DIR/context.md" \
           || [ ! -s "$DEBATE_DIR/context.md" ]; then
        printf '(conversation capture failed)\n' > "$DEBATE_DIR/context.md"
      fi
    else
      printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"
    fi
  fi

  if [ "$RESUMING" = 1 ]; then
    check_resume_feasibility
    rm -f "$DEBATE_DIR/FAILED.txt"
  fi

  debate_start_or_resume
  exit 0
}

# ── /debate-retry entry point ──

debate_retry_main() {
  init_hook_context
  check_requirements "debate-retry" jq python3 tmux claude

  [ -z "$TRANSCRIPT_PATH" ] && { emit_block "/debate-retry: no transcript_path in hook payload"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "/debate-retry requires a git repository"; exit 0; }

  trap 'rc=$?; emit_block "debate-retry crashed at line $LINENO (rc=$rc)"; exit 0' ERR

  local dir best_ts="" best=""
  for dir in "$REPO_ROOT"/Debates/*/; do
    [ -f "$dir/invoking_transcript.txt" ] || continue
    [ "$(cat "$dir/invoking_transcript.txt")" = "$TRANSCRIPT_PATH" ] || continue
    local ts; ts=$(basename "$dir")
    if [[ "$ts" > "$best_ts" ]]; then best_ts="$ts"; best="${dir%/}"; fi
  done
  [ -z "$best" ] && { emit_block "/debate-retry: no debate found in this conversation"; exit 0; }

  if [ -f "$best/synthesis.md" ]; then
    emit_block "/debate-retry: already complete, see $best/synthesis.md"; exit 0
  fi
  if any_live_lock "$best"; then
    local live; live=$(live_debate_session "$best") || live="<unknown>"
    emit_block "/debate-retry: still running → tmux attach -t ${live}"; exit 0
  fi

  DEBATE_DIR="$best"
  TOPIC=$(cat "$best/topic.md")
  RESUMING=1

  detect_available_agents
  check_resume_feasibility

  rm -f "$DEBATE_DIR/FAILED.txt"
  debate_start_or_resume
  exit 0
}

# ── /debate-abort entry point ──

debate_abort_main() {
  init_hook_context
  check_requirements "debate-abort" jq tmux

  [ -z "$TRANSCRIPT_PATH" ] && { emit_block "/debate-abort: no transcript_path in hook payload"; exit 0; }
  [ -z "$REPO_ROOT" ] && { emit_block "/debate-abort requires a git repository"; exit 0; }

  local dir best_ts="" best=""
  for dir in "$REPO_ROOT"/Debates/*/; do
    [ -f "$dir/invoking_transcript.txt" ] || continue
    [ "$(cat "$dir/invoking_transcript.txt")" = "$TRANSCRIPT_PATH" ] || continue
    local ts; ts=$(basename "$dir")
    if [[ "$ts" > "$best_ts" ]]; then best_ts="$ts"; best="${dir%/}"; fi
  done
  [ -z "$best" ] && { emit_block "/debate-abort: no debate found in this conversation"; exit 0; }

  if any_live_lock "$best"; then
    local live; live=$(live_debate_session "$best") || live="<unknown>"
    emit_block "/debate-abort: debate is running. to force-kill: tmux kill-session -t ${live}"
    exit 0
  fi
  rm -rf "$best"
  emit_block "/debate-abort: deleted $best"
  exit 0
}
