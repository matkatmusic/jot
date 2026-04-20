#!/usr/bin/env bash
# snapshot-stash.sh — Create named git ref for current working tree state.
# Args: $1=convo_id  $2=plate_id
# Stdout: the stash SHA
# Side effects: creates refs/plates/<convoID>/<plate-id>
set -euo pipefail

CONVO_ID="${1:?usage: snapshot-stash.sh <convo_id> <plate_id>}"
PLATE_ID="${2:?usage: snapshot-stash.sh <convo_id> <plate_id>}"

# git stash create produces a dangling commit. It returns NOTHING on a
# clean tracked tree. Fallback to HEAD in that case.
# shellcheck source=../../../common/scripts/silencers.sh
. "${CLAUDE_PLUGIN_ROOT}/common/scripts/silencers.sh"

# git stash create returns nothing on a clean tree — fallback to HEAD.
STASH_SHA=$(hide_errors git stash create) || STASH_SHA=""
[ -n "$STASH_SHA" ] || STASH_SHA=$(git rev-parse HEAD)

# Named ref keeps the stash commit alive against git gc.
# This MUST run immediately after stash create — no commands in between.
REF="refs/plates/${CONVO_ID}/${PLATE_ID}"
git update-ref "$REF" "$STASH_SHA"

printf '%s\n' "$STASH_SHA"
