#!/usr/bin/env bash
# plate.sh — function definitions for the /plate UserPromptSubmit hook.
# Sourced by plate-orchestrator.sh. No side effects when sourced.
#
# Branch-model wiring (2026-05-01): every /plate variant runs inline by
# invoking common/scripts/plate/cli.py. The Python CLI's stdout becomes
# the user-facing message via emit_block. Same shape as /jot — no
# pending-*.json drop files, no AskUserQuestion bridges, no foreground-
# claude detour.

# usage: plate_main
# Entry point. Reads hook JSON from stdin, dispatches /plate variants
# inline, emits a single block back to the foreground claude.
plate_main() {
  : "${CLAUDE_PLUGIN_ROOT:?plate plugin env not set — not running under Claude Code plugin harness}"
  : "${CLAUDE_PLUGIN_DATA:?plate plugin env not set — not running under Claude Code plugin harness}"

  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"
  . "${CLAUDE_PLUGIN_ROOT}/common/scripts/hook-json.sh"

  LOG_FILE="${PLATE_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/plate-log.txt}"
  hide_errors mkdir -p "$(dirname "$LOG_FILE")"

  # ── Fast-path bail-out (mirrors jot.sh:130-133) ──────────────────────
  # Substring match against raw INPUT JSON before any jq parsing. Any
  # non-/plate prompt exits silently with no Python startup cost.
  INPUT=$(cat)
  case "$INPUT" in
    *'"/plate'*) ;;
    *) exit 0 ;;
  esac

  check_requirements "plate" jq python3

  # ── Strict prompt regex — typos exit silently before spawning Python ─
  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""')
  PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"   # lstrip whitespace
  if ! printf '%s' "$PROMPT" \
       | grep -qE '^/plate(\s+(--done|--drop|--trash|--recycle|--show|--next( +[0-9A-Za-z._@#$+-]+)?))?$'; then
    exit 0
  fi

  hide_errors printf '%s plate prompt="%s"\n' "$(date -Iseconds)" "$PROMPT" >> "$LOG_FILE"

  SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "?"') || SESSION_ID="?"
  TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"

  # All branch-model variants need a git repo to operate on. If we can't
  # find one, surface a friendly message instead of crashing in Python.
  REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "plate requires a git repository. Run 'git init' in your project root."
    exit 0
  fi

  # ── ERR trap: any failure becomes a single user-visible block ────────
  trap 'rc=$?; emit_block "plate crashed at line $LINENO (rc=$rc)"; hide_errors printf "%s FAIL line=%s rc=%s cmd=%s\n" "$(date -Iseconds)" "$LINENO" "$rc" "$BASH_COMMAND" >> "$LOG_FILE"; exit 0' ERR

  # ── Map prompt → cli.py argv ─────────────────────────────────────────
  CLI_PATH="${CLAUDE_PLUGIN_ROOT}/common/scripts/plate/cli.py"
  case "$PROMPT" in
    "/plate")              ARGS=(push "$SESSION_ID" "$TRANSCRIPT_PATH" "$REPO_ROOT") ;;
    "/plate --done")       ARGS=(done    "$REPO_ROOT") ;;
    "/plate --drop")       ARGS=(drop    "$REPO_ROOT") ;;
    "/plate --trash")      ARGS=(trash   "$REPO_ROOT") ;;
    "/plate --recycle")    ARGS=(recycle "$REPO_ROOT") ;;
    "/plate --show")       ARGS=(show    "$REPO_ROOT") ;;
    "/plate --next")       ARGS=(next    "$REPO_ROOT") ;;
    "/plate --next "*)     ARGS=(next    "$REPO_ROOT" "${PROMPT#/plate --next }") ;;
    *) emit_block "plate: unrecognized variant '$PROMPT'"; exit 0 ;;
  esac

  OUT=$(python3 "$CLI_PATH" "${ARGS[@]}" 2>&1) || true
  emit_block "$OUT"
  exit 0
}
