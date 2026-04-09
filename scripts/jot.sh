#!/bin/bash
# jot.sh — /jot UserPromptSubmit hook. Phase 1 + Phase 2 (queue-driven).
#
# Phase 1 invariant: the user's idea must survive every partial failure.
#   Whatever goes wrong during enrichment or Phase 2 launch, the input.txt
#   is already on disk (durable-first) so the user can retrieve their idea.
#
# Phase 2 architecture: per-project persistent claude instance running in
#   a tmux window inside the shared `jot` session. Jobs are appended to a
#   FIFO queue at $CWD/Todos/.jot-state/queue.txt. SessionStart and Stop
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

# ── emit_block: print {decision:block, reason:...} JSON. ─────────────────
# Uses jq when available; falls back to hand-rolled JSON when jq itself
# is missing (the requirements check needs to report THAT jq is missing).
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

# ── check_requirements: probe for required commands. ────────────────────
check_requirements() {
  local -a missing=()
  command -v jq      >/dev/null 2>&1 || missing+=("jq (brew install jq)")
  command -v python3 >/dev/null 2>&1 || missing+=("python3 (brew install python)")
  command -v tmux    >/dev/null 2>&1 || missing+=("tmux (brew install tmux)")
  command -v claude  >/dev/null 2>&1 || missing+=("claude (https://claude.com/claude-code)")
  if [ ${#missing[@]} -eq 0 ]; then
    return 0
  fi
  local list="" item
  for item in "${missing[@]}"; do
    if [ -z "$list" ]; then list="$item"; else list="$list, $item"; fi
  done
  emit_block "jot needs: $list — install and retry."
  exit 0
}

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

check_requirements

# Source the shared state-lib helpers (used by phase2_enqueue_and_launch)
# shellcheck source=scripts/jot-state-lib.sh
. "$SCRIPTS_DIR/jot-state-lib.sh"

# ── Parse prompt (whole-string trim via python, NOT sed) ────────────────
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | python3 -c 'import sys; print(sys.stdin.read().strip())')

# ── Exact-match prefix gate ──────────────────────────────────────────────
if [[ "$PROMPT" != "/jot" && "$PROMPT" != "/jot "* ]]; then
  exit 0
fi

IDEA="${PROMPT#/jot}"
IDEA="${IDEA# }"
IDEA=$(printf '%s' "$IDEA" | python3 -c 'import sys; print(sys.stdin.read().strip())')
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

# ── Target dir ─────────────────────────────────────────────────────────
TARGET_DIR="$CWD/Todos"
mkdir -p "$TARGET_DIR"

INPUT_FILE="$TARGET_DIR/${TIMESTAMP}_input.txt"
INPUT_REL="Todos/${TIMESTAMP}_input.txt"

# ── DURABLE-FIRST: write the raw idea immediately ─────────────────────
{
  printf '# Jot Task\n\n## Idea\n%s\n\n' "$IDEA"
  printf '## Working Directory\n%s\n\n' "$CWD"
} > "$INPUT_FILE"

# ── Best-effort state gathering (each helper guarded by safe()) ──────
BRANCH=$(safe "$SCRIPTS_DIR/git-branch.sh" "$CWD")
COMMITS=$(safe "$SCRIPTS_DIR/git-commits.sh" "$CWD")
UNCOMMITTED=$(safe "$SCRIPTS_DIR/git-uncommitted.sh" "$CWD")
OPEN_TODOS=$(safe "$SCRIPTS_DIR/scan-open-todos.sh" "$CWD")
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

# ── INSTRUCTIONS heredoc (the prompt the background claude follows) ──
INSTRUCTIONS=$(cat <<JOT_INSTRUCTIONS
You are creating a TODO from a jotted idea. Steps:

1. Read each file listed under "## Open TODO Files" to check for existing TODOs related to this idea (skip if the value is the literal "(unavailable)").

2. SCAN "## Recent Conversation" for context relevant to the idea. Match by SEMANTIC RELEVANCE, not exact strings — does any user/assistant turn mention the same topic, system, file, or concept as the idea?

3. IF "## Recent Conversation" has NO relevant context (or only contains the fallback string "No conversation history available."):
   a. Read the "## Transcript Path" value from the input — it is the absolute path to the live .jsonl transcript.
   b. Use the Read tool DIRECTLY on that path. Do NOT run any Bash command to check whether it exists first — that will trigger a permission prompt and block the workflow. Just call Read. If Read returns an error (file not found, unreadable, empty), treat it as "no relevant context" and jump straight to step 3e.
   c. Walk the transcript from the END backwards, collecting up to ~50 user/assistant pairs that mention any keyword from the idea (case-insensitive substring match on the noun/verb tokens).
   d. If you find relevant context, use it as your context source for steps 5-6.
   e. If you find NOTHING relevant, proceed with the literal context string: "(no relevant prior context found in transcript)". Never crash, never ask, never block.

4. Decide: CREATE NEW TODO, OR APPEND to an existing TODO if there is a strong semantic match in step 1.

5a. CREATE NEW: Write to Todos/${TIMESTAMP}_<slug>.md where <slug> is the idea kebab-cased and truncated to 5-6 words. Use this frontmatter format:
---
id: ${TIMESTAMP}
title: <short title from idea>
status: open
created: <ISO 8601 timestamp with timezone>
branch: ${BRANCH}
---
## Idea
<verbatim from input.txt>

## Context
<1-4 sentences sourced from Recent Conversation OR the transcript fallback in step 3, then verbatim Branch / Commits / Uncommitted lines from ## Git State>

## Conversation
<the Recent Conversation block from above verbatim, OR the relevant pairs you extracted from the transcript in step 3>

5b. APPEND: Edit the matched existing TODO. Update its ## Context section (max 3 sentences added). Add new conversation pairs below ## Conversation separated by --- ${TIMESTAMP} ---. Do NOT change frontmatter.

6. Read your written file with the Read tool to verify ## Idea is present and matches the input.

7. ONLY AFTER step 6 succeeds, use the Write tool to OVERWRITE ${INPUT_REL} with this exact single-line content (no header, no extra lines):
   PROCESSED: Todos/<the slug filename you wrote in step 5>
   This is the success marker AND audit trail. The sandbox blocks rm; do NOT attempt to delete the file. Overwriting via Write is allowed and is the canonical success signal.

8. Output ONLY the relative path of the TODO file (Todos/<slug>.md) to stdout. Nothing else. No commentary.

Rules:
- NEVER ask questions. Zero interaction.
- NEVER run Bash commands. Use ONLY the Read, Write, and Edit tools for every step. Bash is not in the allowlist and will trigger a permission prompt that blocks this workflow. In particular, do NOT use \`ls\`, \`cat\`, \`test -f\`, or any other shell command to check whether a file exists before reading it — just call Read and handle the error case inline.
- Store conversation pairs verbatim. No summarization.
- Keep ## Context concise. No file contents, no diffs, no quoted code blocks.
- The TODO file is the PRIMARY artifact; the PROCESSED: marker on ${INPUT_REL} is the success signal.
- NEVER attempt to rm or delete ${INPUT_REL}. Overwrite it via the Write tool instead.
- If the transcript fallback in step 3 fails (file missing, unreadable, no matches), use the literal context string and continue. Never crash.
JOT_INSTRUCTIONS
)

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

# spawn_terminal_if_needed: open Terminal.app attached to the jot session
# only if no client is currently attached. No-op if a Terminal is already
# showing the session.
#
# macOS-only. On non-Darwin hosts we log a hint and let the user attach to
# the jot tmux session manually. `osascript` is documented in README as a
# Darwin-only optional dependency; the plugin still works headless without
# it, the user just won't get an auto-spawned Terminal window.
spawn_terminal_if_needed() {
  local clients
  clients=$(tmux list-clients -t jot 2>/dev/null || true)
  if [ -n "$clients" ]; then
    return 0
  fi
  case "${OSTYPE:-}" in
    darwin*)
      if ! command -v osascript >/dev/null 2>&1; then
        printf '%s jot: osascript unavailable; attach manually via `tmux attach -t jot`\n' \
          "$(date -Iseconds)" >> "$LOG_FILE" 2>/dev/null || true
        return 0
      fi
      osascript >/dev/null 2>&1 <<'OSA' &
tell application "Terminal"
  do script "tmux attach -t jot"
  set frontmost of window 1 to false
end tell
OSA
      ;;
    *)
      printf '%s jot: non-Darwin host; attach manually via `tmux attach -t jot`\n' \
        "$(date -Iseconds)" >> "$LOG_FILE" 2>/dev/null || true
      ;;
  esac
}

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

  local tmux_target="jot:$WINDOW_NAME"

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
  # - SessionStart: receives INPUT_FILE + tmux_target; sends the
  #   "Read <input.txt> and follow instructions" prompt via send-keys.
  # - Stop: receives INPUT_FILE + tmux_target + STATE_DIR; verifies the
  #   PROCESSED: marker, appends to audit.log, kills THIS window.
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

  # Expand ${CWD} and ${HOME} in the allow array, emit a JSON array literal.
  local allow_json
  allow_json=$(CWD="$CWD" HOME="$HOME" python3 -c '
import json, os, sys
path = os.environ.get("PERMISSIONS_FILE") or sys.argv[1]
with open(path) as f:
    data = json.load(f)
allow = data.get("permissions", {}).get("allow", [])
expanded = [
    item.replace("${CWD}", os.environ["CWD"]).replace("${HOME}", os.environ["HOME"])
    for item in allow
]
print(json.dumps(expanded))
' "$permissions_file")

  cat > "$SETTINGS_FILE" <<JSON
{
  "permissions": {
    "allow": $allow_json
  },
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-start.sh '$INPUT_FILE' '$tmux_target'"}]}],
    "Stop":         [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-stop.sh '$INPUT_FILE' '$tmux_target' '$STATE_DIR'"}]}],
    "SessionEnd":   [{"hooks": [{"type": "command", "command": "bash $hooks_scripts/jot-session-end.sh '$TMPDIR_INV'"}]}]
  }
}
JSON

  # Launch claude. cwd is set by tmux `-c "$CWD"` (already trusted per
  # ~/.claude.json). --add-dir is defensive in case cwd ever changes.
  CLAUDE_CMD="claude --settings '$SETTINGS_FILE' --add-dir '$CWD'"
}

# phase2_launch_window: create a new tmux window running its own claude
# instance for THIS jot invocation. Each /jot gets a unique window named
# "<project>-<timestamp>" so multiple concurrent jots coexist without
# clobbering each other. The Stop hook (configured in build_claude_cmd)
# kills the window when claude finishes, terminating that claude cleanly.
# No shared state, no queue drain, no /clear contamination.
phase2_launch_window() {
  STATE_DIR="$CWD/Todos/.jot-state"
  jot_state_init "$STATE_DIR"
  PROJECT=$(basename "$CWD")
  WINDOW_NAME="${PROJECT}-${TIMESTAMP}"

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

  build_claude_cmd  # generates $TMPDIR_INV, $SETTINGS_FILE, $CLAUDE_CMD

  if ! tmux has-session -t jot 2>/dev/null; then
    tmux new-session -d -s jot -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD"
    tmux set-option -t jot remain-on-exit off >/dev/null 2>&1 || true
    tmux set-option -t jot mouse on >/dev/null 2>&1 || true
  else
    tmux new-window -t jot -n "$WINDOW_NAME" -c "$CWD" "$CLAUDE_CMD"
  fi

  jot_lock_release "$tmux_lock"
  spawn_terminal_if_needed
}

phase2_launch_window

# ── Return block reason to user ────────────────────────────────────────
emit_block "Done! Jotted idea in $INPUT_REL"
exit 0
