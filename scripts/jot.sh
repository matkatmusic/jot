#!/bin/bash
# jot.sh — /jot UserPromptSubmit hook. Thin orchestrator composing the
# reusable libraries under scripts/lib/.
#
# Phase 1 invariant: the user's idea must survive every partial failure.
#   Whatever goes wrong during enrichment or Phase 2 launch, the input.txt
#   is already on disk (durable-first) so the user can retrieve their idea.
#
# Phase 2: one claude per invocation, running in its own tmux pane inside
#   the cross-project `jot:jots` window. Lifecycle hooks (SessionStart,
#   Stop, SessionEnd) live in scripts/jot-session-start.sh, jot-stop.sh,
#   jot-session-end.sh; they are copied into /tmp/jot.XXXXXX/ at launch
#   so `claude plugin update` cannot yank them mid-run.
#
# Module layout (see plans/jot-generalizing-refactor.md):
#   lib/hook-json.sh         emit_block, check_requirements
#   lib/platform.sh          spawn_terminal_if_needed
#   lib/tmux.sh          reliable send-keys for Claude Code TUI
#   lib/tmux-launcher.sh     tmux session/window/pane primitives
#   lib/claude-launcher.sh   generalized build_claude_cmd
#   lib/permissions-seed.sh  three-state permissions.local.json seeder
#   lib/expand_permissions.py   expand ${CWD}/${HOME}/${REPO_ROOT}
#   lib/render_template.py      expand ${VAR} in template files
#   lib/strip_stdin.py          read stdin, print stripped
#   assets/jot-instructions.md  background-worker prompt template
#
# Testing hook: set JOT_SKIP_LAUNCH=1 in the environment to skip Phase 2
#   entirely (no tmux, no claude). The canary suite uses this to verify
#   Phase 1 output without spawning real tmux sessions.
set -euo pipefail

# ── Plugin-env assertions ────────────────────────────────────────────────
# jot.sh is a Claude Code plugin hook. The harness exports CLAUDE_PLUGIN_ROOT
# (where the plugin was installed) and CLAUDE_PLUGIN_DATA (persistent per-
# install state dir, survives plugin updates). Assert both are set BEFORE
# any downstream reference so we fail loudly rather than writing to empty
# paths in the emitted background-worker settings.json.
: "${CLAUDE_PLUGIN_ROOT:?jot plugin env not set — not running under Claude Code plugin harness}"
: "${CLAUDE_PLUGIN_DATA:?jot plugin env not set — not running under Claude Code plugin harness}"

SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"

# ── invoke_command helpers (hide_errors, hide_output, invoke_command) ─────
# Sourced first — used by every subsequent library and inline call.
# shellcheck source=scripts/lib/invoke_command.sh
. "$SCRIPTS_DIR/lib/invoke_command.sh"

# LOG_FILE is env-overridable so the test suite can point it at a throwaway
# file instead of polluting the real log with synthetic test invocations.
# Default lives in CLAUDE_PLUGIN_DATA so the log survives plugin upgrades.
LOG_FILE="${JOT_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/jot-log.txt}"
hide_errors mkdir -p "$(dirname "$LOG_FILE")"

# ── Hook JSON helpers (emit_block, check_requirements) ───────────────────
# shellcheck source=scripts/lib/hook-json.sh
. "$SCRIPTS_DIR/lib/hook-json.sh"

# ── Platform helpers (spawn_terminal_if_needed) ──────────────────────────
# shellcheck source=scripts/lib/platform.sh
. "$SCRIPTS_DIR/lib/platform.sh"

# ── Tmux launcher primitives (session/window/pane choreography) ──────────
# shellcheck source=scripts/lib/tmux-launcher.sh
. "$SCRIPTS_DIR/lib/tmux-launcher.sh"

# ── Claude launcher (settings.json + claude command builder) ─────────────
# shellcheck source=scripts/lib/claude-launcher.sh
. "$SCRIPTS_DIR/lib/claude-launcher.sh"

# ── Permissions seeder (three-state first-run / upgrade logic) ────────────
# shellcheck source=scripts/lib/permissions-seed.sh
. "$SCRIPTS_DIR/lib/permissions-seed.sh"

# ── Git query functions ──────────────────────────────────────────────────
# shellcheck source=scripts/lib/git.sh
. "$SCRIPTS_DIR/lib/git.sh"

# ── Read hook input from stdin ────────────────────────────────────────────
INPUT=$(cat)

# ── Bootstrap probe (no external deps) ───────────────────────────────────
case "$INPUT" in
  *'"/jot'*) ;;
  *) exit 0 ;;
esac

# Dump raw hook input so we can inspect what Claude Code actually passes
# us (session_id, transcript_path, cwd, etc). Only fires on /jot so we
# don't leak non-jot prompts.
hide_errors printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE"

check_requirements "jot" jq python3 tmux claude
tmux_require_version "2.9" || { emit_block "jot requires tmux 2.9+"; exit 0; }

# Source the shared state-lib helpers (used by phase2_enqueue_and_launch)
# shellcheck source=scripts/jot-state-lib.sh
. "$SCRIPTS_DIR/jot-state-lib.sh"

# ── Parse prompt (whole-string trim via python, NOT sed) ────────────────
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | python3 "$SCRIPTS_DIR/lib/strip_stdin.py")

# ── Exact-match prefix gate ──────────────────────────────────────────────
if [[ "$PROMPT" != "/jot" && "$PROMPT" != "/jot "* ]]; then
  exit 0
fi

IDEA="${PROMPT#/jot}"
IDEA="${IDEA# }"
IDEA=$(printf '%s' "$IDEA" | python3 "$SCRIPTS_DIR/lib/strip_stdin.py")
if [ -z "$IDEA" ]; then
  emit_block "jot: no idea provided"
  exit 0
fi

# ── Real /jot confirmed. Safe to log (redacted). ───────────────────────
SESSION_ID=$(printf '%s' "$INPUT" | hide_errors jq -r '.session_id // "?"') || SESSION_ID="?"
hide_errors printf '%s jot session=%s idea_len=%s\n' "$(date -Iseconds)" "$SESSION_ID" "${#IDEA}" >> "$LOG_FILE"

# ── ERR trap: surface any crash as a visible block reason ──────────────
trap 'rc=$?; emit_block "jot crashed at line $LINENO (rc=$rc)"; hide_errors printf "%s FAIL line=%s rc=%s\n" "$(date -Iseconds)" "$LINENO" "$rc" >> "$LOG_FILE"; exit 0' ERR

# ── safe(): best-effort wrapper around helper scripts ──────────────────
safe() {
  local out
  out=$(hide_errors "$@") || out="(unavailable)"
  printf '%s' "${out:-(unavailable)}"
}

TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | hide_errors jq -r '.transcript_path // empty')

CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$PWD"
TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

# ── Repo root (required — abort if not in a git repo) ─────────────────
# All jot-authored files (TODO .md, input.txt, state dir) live under
# $REPO_ROOT/Todos/, never under the session CWD. This guarantees that
# /jot from any subdirectory of a repo always lands in the same Todos/.
REPO_ROOT=$(hide_errors git -C "$CWD" rev-parse --show-toplevel) || REPO_ROOT=""
if [ -z "$REPO_ROOT" ]; then
  emit_block "jot requires a git repository. Run 'git init' in your project root."
  exit 0
fi

# ── Target dir (always repo root, never session CWD) ──────────────────
TARGET_DIR="$REPO_ROOT/Todos"
mkdir -p "$TARGET_DIR"

# INPUT_ABS replaces the old INPUT_REL — variable now holds an absolute
# path so it can be safely passed to background tools (Write/Edit) that
# don't honour the worker's tmux cwd. Renamed from INPUT_REL for clarity.
INPUT_FILE="$TARGET_DIR/${TIMESTAMP}_input.txt"
INPUT_ABS="${REPO_ROOT}/Todos/${TIMESTAMP}_input.txt"

# ── DURABLE-FIRST: write the raw idea immediately ─────────────────────
{
  printf '# Jot Task\n\n## Idea\n%s\n\n' "$IDEA"
  printf '## Working Directory\n%s\n\n' "$CWD"
} > "$INPUT_FILE"

# ── Best-effort state gathering (each helper guarded by safe()) ──────
BRANCH=$(safe git_get_branch_name "$CWD")
COMMITS=$(safe git_get_recent_commits "$CWD")
UNCOMMITTED=$(safe git_get_uncommitted "$CWD")
OPEN_TODOS=$(safe "$SCRIPTS_DIR/scan-open-todos.sh" "$REPO_ROOT")
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  CONVERSATION=$(safe python3 "$SCRIPTS_DIR/capture-conversation.py" "$TRANSCRIPT_PATH")
else
  CONVERSATION="(no transcript available)"
fi

# ── Append enrichment sections to the durable-first file ────────────
{
  printf '## Git State\n- Branch: %s\n- Commits: %s\n- Uncommitted: %s\n\n' "$BRANCH" "$COMMITS" "$UNCOMMITTED"
  printf '## Open TODO Files\n%s\n\n' "$OPEN_TODOS"
  printf '## Transcript Path\n%s\n\n' "${TRANSCRIPT_PATH:-(none)}"
  printf '## Recent Conversation\n%s\n\n' "$CONVERSATION"
} >> "$INPUT_FILE"

# ── INSTRUCTIONS (the prompt the background claude follows) ───────────
# Lives at scripts/assets/jot-instructions.md; render_template.py expands
# ${REPO_ROOT}, ${TIMESTAMP}, ${BRANCH}, ${INPUT_ABS} and fails loud on any
# unexpanded placeholder.
INSTRUCTIONS=$(REPO_ROOT="$REPO_ROOT" TIMESTAMP="$TIMESTAMP" BRANCH="$BRANCH" INPUT_ABS="$INPUT_ABS" \
  python3 "$SCRIPTS_DIR/lib/render_template.py" \
    "$CLAUDE_PLUGIN_ROOT/scripts/assets/jot-instructions.md" \
    REPO_ROOT TIMESTAMP BRANCH INPUT_ABS)

# ── Prepend Instructions to the TOP of the input file ────────────────
# Phase 2.6: claude opens the input.txt via "Read <path> and follow the
# instructions at the top". The Instructions section MUST be the first
# section after the # Jot Task heading, so claude sees the workflow first.
_BODY=$(cat "$INPUT_FILE")
{
  printf '# Jot Task\n\n## Instructions\n%s\n\n' "$INSTRUCTIONS"
  # Strip the duplicate "# Jot Task" line that's already in _BODY
  printf '%s\n' "$_BODY" | tail -n +2
} > "$INPUT_FILE"

# ── JOT_SKIP_LAUNCH: testing hook ──────────────────────────────────────
if [ "${JOT_SKIP_LAUNCH:-0}" = "1" ]; then
  emit_block "Jotted: $IDEA (launch skipped)"
  exit 0
fi

# ── Phase 2 helpers (defined inside jot.sh; could be sourced from a lib) ─

# spawn_terminal_if_needed is provided by lib/platform.sh (sourced below).

# permissions_seed is provided by lib/permissions-seed.sh (sourced above).

# build_claude_cmd: generate per-invocation settings.json + claude command
# Inputs: CWD, STATE_DIR, INPUT_FILE, WINDOW_NAME
# Outputs: TMPDIR_INV, SETTINGS_FILE, PERMISSIONS_FILE, CLAUDE_CMD
#
# Architecture:
#   ONE claude instance per /jot invocation, running in its own tmux window.
#   When claude finishes processing, the Stop hook kills the window, which
#   terminates that claude. No shared state across jobs → no /clear → no
#   SessionEnd/cwd race → permissions from settings.json are trusted fresh
#   every time.
#
# Permissions model (plugin-native):
#   The bundled default at ${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json
#   is copied on first run into ${CLAUDE_PLUGIN_DATA}/permissions.local.json
#   by jot_seed_permissions(), which implements a three-state sha256 check
#   (missing / matches-prior-default / user-edited) so plugin upgrades can
#   refresh the default without clobbering user edits.
#
#   On every /jot, jot.sh reads the installed file, expands the ${CWD} and
#   ${HOME} template placeholders via an inline python heredoc, and writes
#   the resolved JSON inline into $TMPDIR_INV/settings.json. The background
#   worker reads settings.json with concrete paths and has no dependency on
#   plugin env vars.
#
#   This supersedes an earlier symlink-based approach where
#   $TMPDIR_INV/.claude/settings.local.json was symlinked into a persistent
#   host file — that mechanism is no longer used.
jot_build_claude_cmd() {
  TMPDIR_INV=$(mktemp -d /tmp/jot.XXXXXX)
  SETTINGS_FILE="$TMPDIR_INV/settings.json"
  PERMISSIONS_FILE="${CLAUDE_PLUGIN_DATA}/permissions.local.json"

  # ── Lifecycle-safe worker launch ───────────────────────────────────────
  # Each background worker owns a self-contained copy of its lifecycle hook
  # scripts inside $TMPDIR_INV. The emitted settings.json references these
  # copies, NOT ${CLAUDE_PLUGIN_ROOT}/scripts, so that `claude plugin update`
  # during a live worker cannot delete the scripts out from under it.
  # $TMPDIR_INV is wiped on SessionEnd when the worker exits, so the copies
  # are cleaned up automatically.
  cp "${CLAUDE_PLUGIN_ROOT}/scripts/jot-session-start.sh" "$TMPDIR_INV/jot-session-start.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/scripts/jot-stop.sh"          "$TMPDIR_INV/jot-stop.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/scripts/jot-session-end.sh"   "$TMPDIR_INV/jot-session-end.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/scripts/lib/tmux.sh"              "$TMPDIR_INV/tmux.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/scripts/lib/tmux-launcher.sh"     "$TMPDIR_INV/tmux-launcher.sh"
  cp "${CLAUDE_PLUGIN_ROOT}/scripts/lib/invoke_command.sh"    "$TMPDIR_INV/invoke_command.sh"
  local hooks_scripts="$TMPDIR_INV"

  # Permissions: loaded from the persistent allowlist at
  # ${CLAUDE_PLUGIN_DATA}/permissions.local.json. The file supports ${CWD}
  # and ${HOME} template placeholders that are expanded per-invocation.
  local permissions_file="${CLAUDE_PLUGIN_DATA}/permissions.local.json"
  local default_file="${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json"
  local default_sha_file="${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json.sha256"
  local prior_sha_file="${CLAUDE_PLUGIN_DATA}/permissions.default.sha256"
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  permissions_seed "$permissions_file" "$default_file" "$default_sha_file" "$prior_sha_file" "$LOG_FILE" "jot"

  # Expand permissions allow array (with legacy-form migration shim).
  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "$SCRIPTS_DIR/lib/expand_permissions.py" "$permissions_file")

  # Hooks wired per-invocation:
  # - SessionStart: receives INPUT_FILE + TMPDIR_INV; reads the tmux pane id
  #   sidecar at "$TMPDIR_INV/tmux_target", sends Read-and-follow prompt.
  # - Stop: receives INPUT_FILE + TMPDIR_INV + STATE_DIR; verifies PROCESSED:
  #   marker, appends audit.log, kills pane.
  # - SessionEnd: wipes $TMPDIR_INV on claude exit.
  local hooks_json_file="$TMPDIR_INV/hooks.json"
  cat > "$hooks_json_file" <<JSON
{
  "SessionStart": [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-start.sh '$INPUT_FILE' '$TMPDIR_INV'"}]}],
  "Stop":         [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-stop.sh '$INPUT_FILE' '$TMPDIR_INV' '$STATE_DIR'"}]}],
  "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-end.sh '$TMPDIR_INV'"}]}]
}
JSON

  # Launch claude via the generalized builder. cwd is set by tmux (subdir);
  # --add-dir grants access to repo-root Todos/ from any subdir.
  CLAUDE_CMD=$(build_claude_cmd "$SETTINGS_FILE" "$allow_json" "$hooks_json_file" "$CWD" "$REPO_ROOT")
}

# phase2_launch_window: spawn a new tmux PANE running its own claude
# instance for THIS jot invocation. All panes live inside a single
# window "jot:jots" alongside a SIGINT-hardened keepalive pane that
# holds the window (and therefore the session) open forever. The Stop
# hook (configured in build_claude_cmd) kills the specific pane when
# claude finishes, which terminates that claude cleanly while leaving
# the rest of the dashboard intact.
# No shared state, no queue drain, no /clear contamination.
phase2_launch_window() {
  STATE_DIR="$REPO_ROOT/Todos/.jot-state"
  jot_state_init "$STATE_DIR"
  # NOTE: pane_label is generated AFTER tmux-launch.lock is acquired so
  # the monotonic counter read/increment/write is serialized across all
  # concurrent /jot invocations. See the counter block below.

  # ── GLOBAL tmux-launch lock ─────────────────────────────────────────────
  # The `jot` tmux session is a cross-project singleton. Two /jot invocations
  # in DIFFERENT projects previously locked on per-project $STATE_DIR/queue.lock
  # (unrelated locks), then both raced to `tmux new-session -s jot`, dropping
  # one invocation. The fix is a single global lock under CLAUDE_PLUGIN_DATA so
  # concurrent jots across projects serialize the new-session check + launch.
  # queue.lock remains per-project for its original purpose (legacy queue
  # drain, still referenced by jot-stop.sh audit writes).
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  local tmux_lock="${CLAUDE_PLUGIN_DATA}/tmux-launch.lock"
  if ! jot_lock_acquire "$tmux_lock" 10; then
    hide_errors echo "[jot] failed to acquire global tmux-launch lock at $tmux_lock" >> "$LOG_FILE"
    return 1
  fi

  # ── Monotonic pane counter (1..20, wraps) ──────────────────────────────
  # MUST live AFTER jot_lock_acquire — the lock serializes concurrent /jots
  # across all projects so the read/increment/write below is atomic. If
  # this block were placed earlier (before the lock), two simultaneous
  # /jots would both read N, both write N+1, and both label their panes
  # the same. Verified by debate review (4-of-4 unanimous, 2026-04-10).
  local counter_file="${CLAUDE_PLUGIN_DATA}/pane-counter.txt"
  local n
  n=$(hide_errors cat "$counter_file") || n=0
  n=$(( n % 20 + 1 ))
  printf '%s\n' "$n" > "$counter_file"
  local pane_label="jot${n}"

  jot_build_claude_cmd  # generates $TMPDIR_INV, $SETTINGS_FILE, $CLAUDE_CMD

  # ── Ensure jot session + jots window + keepalive pane exist ─────────────
  # The keepalive pane runs `tail -f /dev/null` wrapped by an `sh` that
  # traps INT/HUP/TERM, so an accidental C-c in that pane cannot kill it
  # and cascade window/session death. Once this pane exists, the jot
  # session is immortal until the user explicitly `tmux kill-session -t jot`.
  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[jot keepalive — do not kill]\n"; exec tail -f /dev/null'\'''
  tmux_ensure_session jot jots "$CWD" "$keepalive_cmd" 'jot: keepalive'

  # ── Split a new pane for this worker; capture its stable pane id ────────
  local PANE_ID
  if ! PANE_ID=$(tmux_split_worker_pane jot:jots "$CWD" "$CLAUDE_CMD"); then
    hide_errors echo "[jot] tmux split-window returned empty pane id" >> "$LOG_FILE"
    jot_lock_release "$tmux_lock"
    return 1
  fi

  # ── Handoff: write pane id for SessionStart/Stop hooks to read ──────────
  # Atomic rename (printf to .tmp, then mv) guarantees hooks never see a
  # partially-written sidecar. Write BEFORE any cosmetic tmux calls to
  # minimise the window where claude could fire SessionStart ahead of the
  # sidecar being present.
  printf '%s\n' "$PANE_ID" > "$TMPDIR_INV/tmux_target.tmp"
  mv "$TMPDIR_INV/tmux_target.tmp" "$TMPDIR_INV/tmux_target"

  tmux_set_pane_title "$PANE_ID" "$pane_label"
  tmux_retile jot:jots

  jot_lock_release "$tmux_lock"
  spawn_terminal_if_needed "jot" "$LOG_FILE" "jot"
}

phase2_launch_window

# ── Return block reason to user ────────────────────────────────────────
emit_block "Done! Jotted idea in $INPUT_ABS"
exit 0
