#!/bin/bash
# scan-existing-todos-test.sh — exercise the atomic-claim helper.
# Failing condition: two concurrent runs return the same ID, or the helper
# ignores existing NNN_*.md / NNN_*.md done/ files when computing max.
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$THIS_DIR/../scripts/scan-existing-todos.sh"

TMP=$(mktemp -d /tmp/todo-scan-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/Todos/done"
# Seed max = 005 via a done file and max = 007 via an open file.
touch "$TMP/Todos/done/005_old.md"
touch "$TMP/Todos/007_open.md"

# 1. Single-run: should claim 008.
out=$(bash "$SCRIPT" "$TMP")
if [ "$out" != "008" ]; then
  echo "FAIL: expected 008, got $out" >&2; exit 1
fi
if [ ! -f "$TMP/Todos/.todo-state/id-008.claim" ]; then
  echo "FAIL: sentinel id-008.claim missing" >&2; exit 1
fi

# 2. Concurrent run: should skip 008 (still sentinel'd) and claim 009.
out2=$(bash "$SCRIPT" "$TMP")
if [ "$out2" != "009" ]; then
  echo "FAIL: expected 009 on second run, got $out2" >&2; exit 1
fi

# 3. Parallel race: launch 10 concurrent claims, ensure all distinct.
rm -rf "$TMP/Todos/.todo-state"
pids=()
results_file="$TMP/results.txt"
: > "$results_file"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  ( bash "$SCRIPT" "$TMP" >> "$results_file" ) &
  pids+=("$!")
done
for p in "${pids[@]}"; do wait "$p"; done

unique=$(sort -u "$results_file" | wc -l | tr -d ' ')
total=$(wc -l < "$results_file" | tr -d ' ')
if [ "$unique" != "$total" ]; then
  echo "FAIL: duplicate IDs in concurrent race — $total results, $unique unique" >&2
  cat "$results_file" >&2
  exit 1
fi

echo "PASS: scan-existing-todos claims distinct IDs ($total concurrent, $unique unique)"
