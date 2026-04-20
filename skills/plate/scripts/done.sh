#!/usr/bin/env bash
# done.sh — /plate --done: replay stack[] as sequential commits (§7.3).
# Args: $1=convo_id
# Stdout: ancestor chain + resume command for user
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPTS_DIR/../../.." && pwd)"
PYTHON_DIR="$PLUGIN_ROOT/common/scripts/plate"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

# shellcheck source=paths.sh
. "$SCRIPTS_DIR/paths.sh"
plate_discover_repo_root

CONVO_ID="${1:?usage: done.sh <convo_id>}"
INSTANCE_FILE="${PLATE_ROOT}/instances/${CONVO_ID}.json"

# ── Preflight checks ─────────────────────────────────────────────────────
if [ ! -f "$INSTANCE_FILE" ]; then
  echo "Error: no plate state for session $CONVO_ID" >&2
  exit 1
fi

STACK_COUNT=$(INSTANCE_FILE="$INSTANCE_FILE" python3 -c 'import json,os; d=json.load(open(os.environ["INSTANCE_FILE"])); print(len(d.get("stack",[])))')
if [ "$STACK_COUNT" -eq 0 ]; then
  echo "Error: no plates on the stack to commit." >&2
  exit 1
fi

# ── Check for open delegated children (§9.3) ─────────────────────────────
HAS_LIVE_CHILDREN=$(INSTANCE_FILE="$INSTANCE_FILE" python3 "$PYTHON_DIR/check_live_children.py")
if [ "$HAS_LIVE_CHILDREN" = "yes" ]; then
  # The skill body (foreground claude) handles AskUserQuestion for this.
  # done.sh only runs after the user has chosen to proceed.
  echo "WARNING: delegated children still open. Proceeding per user choice." >&2
fi

# ── Replay loop: oldest first ─────────────────────────────────────────────
COMMIT_SHAS=()
LAST_REF=""

while IFS= read -r plate_json; do
  [ -z "$plate_json" ] && continue

  PLATE_ID=$(printf '%s' "$plate_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["plate_id"])')
  STASH_SHA=$(printf '%s' "$plate_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["stash_sha"])')
  HEAD_SHA=$(printf '%s' "$plate_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["push_time_head_sha"])')

  # Base for diff: previous plate's stash, or first plate's HEAD at push time
  if [ -z "$LAST_REF" ]; then
    BASE="$HEAD_SHA"
  else
    BASE="$LAST_REF"
  fi

  # Apply the diff for this plate via a temp file. $(...) command substitution
  # strips trailing newlines and can't carry NUL bytes, both of which corrupt
  # `git diff --binary` output (empirical: 4KB random-binary diffs lose ~110
  # bytes and `git apply` rejects with "corrupt binary patch at line N").
  # File I/O preserves the exact byte stream for both ASCII and binary plates.
  PATCH_FILE=$(mktemp "${TMPDIR:-/tmp}/plate-diff.XXXXXX")
  # shellcheck disable=SC2064  # expand PATCH_FILE now, not at trap-fire time
  trap "rm -f '$PATCH_FILE'" EXIT
  hide_errors git diff --binary "$BASE" "$STASH_SHA" > "$PATCH_FILE" || : > "$PATCH_FILE"
  if [ -s "$PATCH_FILE" ]; then
    if ! hide_errors git apply --index --3way - < "$PATCH_FILE"; then
      echo "Warning: conflict applying plate $PLATE_ID, attempting manual resolve" >&2
      # --3way may leave conflict markers for the user to resolve manually.
      # Emit a warning on unresolved conflicts rather than aborting — an abort
      # mid-done would leave the repo in a partial-apply state with no commit
      # and no cleanup.
      if ! git apply --index --3way - < "$PATCH_FILE"; then
        echo "Warning: unresolved conflicts remain for plate $PLATE_ID" >&2
      fi
    fi
  fi
  rm -f "$PATCH_FILE"
  trap - EXIT

  # Commit with structured message
  COMMIT_MSG=$(printf '%s' "$plate_json" | python3 "$PYTHON_DIR/commit_message.py")
  git commit --allow-empty -m "$COMMIT_MSG"
  COMMIT_SHA=$(git rev-parse HEAD)
  COMMIT_SHAS+=("$COMMIT_SHA")

  # Mark plate completed in instance JSON
  COMPLETED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  python3 "$PYTHON_DIR/instance_rw.py" complete "$INSTANCE_FILE" "$PLATE_ID" "$COMMIT_SHA" "$COMPLETED_AT"

  # Delete the named ref
  hide_errors git update-ref -d "refs/plates/${CONVO_ID}/${PLATE_ID}"

  LAST_REF="$STASH_SHA"

done < <(python3 "$PYTHON_DIR/instance_rw.py" stack-oldest "$INSTANCE_FILE")

# ── Final commit: capture any work done after the last plate (§7.3 step 4)
if ! hide_errors git diff --quiet HEAD || ! hide_errors git diff --cached --quiet HEAD; then
  git add -A
  git commit -m "[plate] final: work after last plate push"
  COMMIT_SHAS+=("$(git rev-parse HEAD)")
fi

# ── Cascade up through parent chain (§9.2) ────────────────────────────────
MAX_DEPTH=20
INSTANCE_FILE="$INSTANCE_FILE" PLATE_ROOT="$PLATE_ROOT" \
CONVO_ID="$CONVO_ID" PYTHON_DIR="$PYTHON_DIR" MAX_DEPTH="$MAX_DEPTH" \
python3 "$PYTHON_DIR/cascade_parent_chain.py"

# ── Print result ──────────────────────────────────────────────────────────
BRANCH=$(hide_errors git symbolic-ref --short HEAD) || BRANCH="detached"
echo "Committed ${#COMMIT_SHAS[@]} plates in ${CONVO_ID} -> ${BRANCH} (${COMMIT_SHAS[*]})"

# Print resume pointer if parent exists. Note: env-var prefixes only work on
# simple commands, not through a function wrapper — `hide_errors FOO=bar cmd`
# becomes `bash: FOO=bar: No such file or directory` (rc=127) because `"$@"`
# expansion bypasses bash's assignment-prefix recognition. print_resume_pointer
# is silent on missing parent_ref anyway, so drop hide_errors.
INSTANCE_FILE="$INSTANCE_FILE" PLATE_ROOT="$PLATE_ROOT" python3 "$PYTHON_DIR/print_resume_pointer.py"
