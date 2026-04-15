#!/bin/bash
# jot.sh — /jot UserPromptSubmit hook. Phase 1 + Phase 2 (queue-driven).
#
# Phase 1 invariant: the user's idea must survive every partial failure.
#   Whatever goes wrong during enrichment or Phase 2 launch, the input.txt
#   is already on disk (durable-first) so the user can retrieve their idea.
#
# Phase 2 architecture: per-project persistent claude instance running in
#   a tmux window inside the shared `jot` session. Jobs are appended to a
#   FIFO queue at $REPO_ROOT/Todos/.jot-state/queue.txt. SessionStart and Stop
#   hooks (defined in /tmp/jot.XXXXXX/settings.json) drain the queue via
#   tmux send-keys. See:
#     ~/.claude/hooks/scripts/jot-session-start.sh
#     ~/.claude/hooks/scripts/jot-stop.sh
#     ~/.claude/hooks/scripts/jot-session-end.sh
#
# Testing hook: set JOT_SKIP_LAUNCH=1 in the environment to skip Phase 2
#   entirely (no enqueue, no tmux, no claude). The canary suite uses this
#   to verify Phase 1 output without spawning real tmux sessions.
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
# LOG_FILE is env-overridable so the test suite can point it at a throwaway
# file instead of polluting the real log with synthetic test invocations.
# Default lives in CLAUDE_PLUGIN_DATA so the log survives plugin upgrades.
LOG_FILE="${JOT_LOG_FILE:-${CLAUDE_PLUGIN_DATA}/jot-log.txt}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# ── Hook JSON helpers (emit_block, check_requirements) ───────────────────
# shellcheck source=scripts/lib/hook-json.sh
. "$SCRIPTS_DIR/lib/hook-json.sh"

# ── Platform helpers (spawn_terminal_if_needed) ──────────────────────────
# shellcheck source=scripts/lib/platform.sh
. "$SCRIPTS_DIR/lib/platform.sh"

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
printf '%s HOOK_INPUT %s\n' "$(date -Iseconds)" "$INPUT" >> "$LOG_FILE" 2>/dev/null || true

check_requirements "jot" jq python3 tmux claude

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
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "?"' 2>/dev/null || echo "?")
printf '%s jot session=%s idea_len=%s\n' "$(date -Iseconds)" "$SESSION_ID" "${#IDEA}" >> "$LOG_FILE" 2>/dev/null || true

# ── ERR trap: surface any crash as a visible block reason ──────────────
trap 'rc=$?; emit_block "jot crashed at line $LINENO (rc=$rc)"; printf "%s FAIL line=%s rc=%s\n" "$(date -Iseconds)" "$LINENO" "$rc" >> "$LOG_FILE" 2>/dev/null || true; exit 0' ERR

# ── safe(): best-effort wrapper around helper scripts ──────────────────
safe() {
  local out
  out=$("$@" 2>/dev/null) || out="(unavailable)"
  printf '%s' "${out:-(unavailable)}"
}

TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || echo "")

CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || echo "")
[ -z "$CWD" ] && CWD="$PWD"
TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)

# ── Repo root (required — abort if not in a git repo) ─────────────────
# All jot-authored files (TODO .md, input.txt, state dir) live under
# $REPO_ROOT/Todos/, never under the session CWD. This guarantees that
# /jot from any subdirectory of a repo always lands in the same Todos/.
REPO_ROOT=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || true)
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
BRANCH=$(safe "$SCRIPTS_DIR/git-branch.sh" "$CWD")
COMMITS=$(safe "$SCRIPTS_DIR/git-commits.sh" "$CWD")
UNCOMMITTED=$(safe "$SCRIPTS_DIR/git-uncommitted.sh" "$CWD")
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

# jot_seed_permissions: three-state first-run / upgrade seeder for the
# user-editable permissions allowlist.
#
# Args:
#   $1 installed_file     ${CLAUDE_PLUGIN_DATA}/permissions.local.json
#   $2 default_file       ${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json  (bundled)
#   $3 default_sha_file   ${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json.sha256
#   $4 prior_sha_file     ${CLAUDE_PLUGIN_DATA}/permissions.default.sha256  (what we shipped last time)
#
# Three states:
#   (1) installed_file MISSING → copy default in, record prior_sha = current default sha.
#   (2) installed_file sha matches prior_sha → safe to overwrite on upgrade
#       (user never touched it, but we shipped a newer default). Copy default
#       in, update prior_sha.
#   (3) installed_file sha does NOT match prior_sha → user edited it. Leave
#       alone. Log a one-line warning the first time we see a newer bundled
#       default so the user knows to diff manually.
jot_seed_permissions() {
  local installed="$1" default="$2" default_sha_file="$3" prior_sha_file="$4"
  local current_default_sha installed_sha prior_sha

  # Bundled default must exist; if the plugin is broken we cannot seed.
  if [ ! -f "$default" ] || [ ! -f "$default_sha_file" ]; then
    printf '%s jot: bundled permissions default missing at %s — cannot seed\n' \
      "$(date -Iseconds)" "$default" >> "$LOG_FILE" 2>/dev/null || true
    return 0
  fi
  current_default_sha=$(awk '{print $1}' "$default_sha_file")

  # State 1: nothing installed yet — fresh copy.
  if [ ! -f "$installed" ]; then
    cp "$default" "$installed"
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
    printf '%s jot: seeded %s from bundled default (sha=%s)\n' \
      "$(date -Iseconds)" "$installed" "$current_default_sha" >> "$LOG_FILE" 2>/dev/null || true
    return 0
  fi

  installed_sha=$(shasum -a 256 "$installed" 2>/dev/null | awk '{print $1}')
  prior_sha=$([ -f "$prior_sha_file" ] && awk '{print $1}' "$prior_sha_file" || echo "")

  # Already up-to-date: no action.
  if [ "$installed_sha" = "$current_default_sha" ]; then
    return 0
  fi

  # State 2: installed matches the prior shipped default. User hasn't edited
  # → safe to overwrite with the newer bundled default.
  if [ -n "$prior_sha" ] && [ "$installed_sha" = "$prior_sha" ]; then
    cp "$default" "$installed"
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
    printf '%s jot: upgraded %s to new bundled default (was %s, now %s)\n' \
      "$(date -Iseconds)" "$installed" "$prior_sha" "$current_default_sha" >> "$LOG_FILE" 2>/dev/null || true
    return 0
  fi

  # State 3: user-edited. Leave it alone. Log a one-line hint the first time
  # we see a new default so the user knows to diff manually.
  if [ "$prior_sha" != "$current_default_sha" ]; then
    printf '%s jot: %s is user-edited; bundled default updated — diff manually. installed_sha=%s prior_sha=%s current_default_sha=%s\n' \
      "$(date -Iseconds)" "$installed" "$installed_sha" "$prior_sha" "$current_default_sha" >> "$LOG_FILE" 2>/dev/null || true
    # Advance prior_sha so we don't log this warning on every /jot — only once
    # per bundled-default upgrade.
    printf '%s\n' "$current_default_sha" > "$prior_sha_file"
  fi
  return 0
}

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
build_claude_cmd() {
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
  local hooks_scripts="$TMPDIR_INV"

  # Hooks wired per-invocation:
  # - SessionStart: receives INPUT_FILE + TMPDIR_INV; reads the tmux pane id
  #   from "$TMPDIR_INV/tmux_target" (written by phase2_launch_window after
  #   split-window), then sends the "Read <input.txt> and follow
  #   instructions" prompt via send-keys.
  # - Stop: receives INPUT_FILE + TMPDIR_INV + STATE_DIR; reads the sidecar
  #   synchronously BEFORE forking its kill-pane subshell, verifies the
  #   PROCESSED: marker, appends to audit.log, kills THIS pane.
  # - SessionEnd: wipes $TMPDIR_INV on claude exit. Safe because each claude
  #   has its own tmpdir and no other process references it.
  #
  # Permissions: loaded from the persistent allowlist at
  # ${CLAUDE_PLUGIN_DATA}/permissions.local.json. The file supports ${CWD}
  # and ${HOME} template placeholders that are expanded per-invocation here.
  # Users can edit the installed copy to add site-specific grants; changes
  # take effect on the next /jot.
  local permissions_file="${CLAUDE_PLUGIN_DATA}/permissions.local.json"
  local default_file="${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json"
  local default_sha_file="${CLAUDE_PLUGIN_ROOT}/assets/permissions.default.json.sha256"
  local prior_sha_file="${CLAUDE_PLUGIN_DATA}/permissions.default.sha256"
  mkdir -p "${CLAUDE_PLUGIN_DATA}"
  jot_seed_permissions "$permissions_file" "$default_file" "$default_sha_file" "$prior_sha_file"

  # Expand ${CWD}, ${HOME}, ${REPO_ROOT} in the allow array, emit a JSON
  # array literal. The helper also applies a backward-compat migration shim
  # for legacy cwd-relative Write(Todos/**)/Edit(Todos/**) entries; see
  # scripts/lib/expand_permissions.py for details.
  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" REPO_ROOT="$REPO_ROOT" \
    python3 "$SCRIPTS_DIR/lib/expand_permissions.py" "$permissions_file")

  cat > "$SETTINGS_FILE" <<JSON
{
  "permissions": {
    "allow": $allow_json
  },
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-start.sh '$INPUT_FILE' '$TMPDIR_INV'"}]}],
    "Stop":         [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-stop.sh '$INPUT_FILE' '$TMPDIR_INV' '$STATE_DIR'"}]}],
    "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-end.sh '$TMPDIR_INV'"}]}]
  }
}
JSON

  # Launch claude. cwd is set by tmux `-c "$CWD"` (the user's session
  # subdirectory). --add-dir grants the agent access to repo-root Todos/
  # even when cwd is a subdirectory deeper in the tree.
  CLAUDE_CMD="claude --settings '$SETTINGS_FILE' --add-dir '$CWD' --add-dir '$REPO_ROOT'"
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
    echo "[jot] failed to acquire global tmux-launch lock at $tmux_lock" >> "$LOG_FILE" 2>/dev/null || true
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
  n=$(cat "$counter_file" 2>/dev/null || echo 0)
  n=$(( n % 20 + 1 ))
  printf '%s\n' "$n" > "$counter_file"
  local pane_label="jot${n}"

  build_claude_cmd  # generates $TMPDIR_INV, $SETTINGS_FILE, $CLAUDE_CMD

  # ── Ensure jot session + jots window + keepalive pane exist ─────────────
  # The keepalive pane runs `tail -f /dev/null` wrapped by an `sh` that
  # traps INT/HUP/TERM, so an accidental C-c in that pane cannot kill it
  # and cascade window/session death. Once this pane exists, the jot
  # session is immortal until the user explicitly `tmux kill-session -t jot`.
  local keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[jot keepalive — do not kill]\n"; exec tail -f /dev/null'\'''
  if ! tmux has-session -t jot 2>/dev/null; then
    tmux new-session -d -s jot -n jots -c "$CWD" "$keepalive_cmd"
    tmux set-option -t jot remain-on-exit off           >/dev/null 2>&1 || true
    tmux set-option -t jot mouse on                     >/dev/null 2>&1 || true
    tmux set-option -t jot pane-border-status top       >/dev/null 2>&1 || true
    tmux set-option -t jot pane-border-format ' #{pane_title} ' >/dev/null 2>&1 || true
    tmux select-pane -t jot:jots.0 -T 'jot: keepalive'  >/dev/null 2>&1 || true
  elif ! tmux list-windows -t jot -F '#{window_name}' 2>/dev/null | grep -qx jots; then
    tmux new-window -t jot -n jots -c "$CWD" "$keepalive_cmd"
    tmux select-pane -t jot:jots.0 -T 'jot: keepalive'  >/dev/null 2>&1 || true
  else
    # ── Ensure keepalive pane still exists inside jots window ───────────
    # Guards case (c): session + jots window exist but keepalive pane was
    # manually killed or crashed. Without this, the last worker pane to
    # finish would cascade the window and session into death. Probes by
    # pane_title (not index) because worker panes outlive keepalive and
    # shift indices. (Added per 4-of-4 unanimous debate review.)
    if ! tmux list-panes -t jot:jots -F '#{pane_title}' 2>/dev/null \
         | grep -qx 'jot: keepalive'; then
      local KA_ID
      KA_ID=$(tmux split-window -t jot:jots -c "$CWD" -P -F '#{pane_id}' "$keepalive_cmd")
      [ -n "$KA_ID" ] && tmux select-pane -t "$KA_ID" -T 'jot: keepalive' >/dev/null 2>&1 || true
      tmux select-layout -t jot:jots tiled >/dev/null 2>&1 || true
    fi
  fi

  # ── Split a new pane for this worker; capture its stable pane id ────────
  local PANE_ID
  PANE_ID=$(tmux split-window -t jot:jots -c "$CWD" -P -F '#{pane_id}' "$CLAUDE_CMD")
  if [ -z "$PANE_ID" ]; then
    echo "[jot] tmux split-window returned empty pane id" >> "$LOG_FILE" 2>/dev/null || true
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

  tmux select-pane -t "$PANE_ID" -T "$pane_label"    >/dev/null 2>&1 || true
  tmux select-layout -t jot:jots tiled               >/dev/null 2>&1 || true

  jot_lock_release "$tmux_lock"
  spawn_terminal_if_needed "jot" "$LOG_FILE" "jot"
}

phase2_launch_window

# ── Return block reason to user ────────────────────────────────────────
emit_block "Done! Jotted idea in $INPUT_ABS"
exit 0
