#!/bin/bash
# e2e-test.sh — end-to-end test of the debate skill with REAL agent CLIs.
#
# Replaces the legacy archive/test.sh attended harness. Reuses the production
# orchestrator daemon directly instead of duplicating its helpers, so the
# test stays in lockstep with the real code path.
#
# Flow:
#   1. Detect available agents (claude required; gemini/codex optional).
#      Skip if fewer than 2 agents are authenticated.
#   2. Build a sandboxed DEBATE_DIR with a small fixture topic.
#   3. Build R1 instructions via debate-build-prompts.sh.
#   4. Claim a fresh debate-<N> tmux session with a keepalive pane.
#   5. Run debate-tmux-orchestrator.sh in the foreground.
#   6. Assert: synthesis.md produced + archive/ populated + no FAILED.txt +
#      launch_agents_parallel wall-clock under the parallel-budget threshold.
#
# Cost: one real debate per run (live API calls, ~5–10 min wall). Not for CI.
# Requires: tmux, jq, authenticated claude (mandatory) + ≥1 of gemini/codex.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS_DIR="$PLUGIN_ROOT/skills/debate/scripts"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

. "$PLUGIN_ROOT/common/scripts/silencers.sh"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
nope() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; }

# ──────────── agent detection (mirrors debate.sh:_probe_*) ────────────
_default_model() {
  local models_json="$PLUGIN_ROOT/skills/debate/scripts/assets/models.json"
  hide_errors jq -r --arg a "$1" '.[$a][0] // ""' "$models_json"
}
_probe_gemini() {
  hide_output hide_errors command -v gemini || return 0
  [[ -f "$HOME/.gemini/oauth_creds.json" ]] \
    || [[ -n "${GEMINI_API_KEY:-}" ]] \
    || [[ -n "${GOOGLE_API_KEY:-}" ]] \
    || return 0
  local m; m=$(_default_model gemini)
  printf '%s\n' "${m:-present}"
}
_probe_codex() {
  hide_output hide_errors command -v codex || return 0
  [[ -f "$HOME/.codex/auth.json" ]] || [[ -n "${OPENAI_API_KEY:-}" ]] || return 0
  local m; m=$(_default_model codex)
  printf '%s\n' "${m:-present}"
}

if ! hide_output hide_errors command -v claude; then
  printf '\033[33m[e2e-test] SKIP — claude CLI not on PATH\033[0m\n'
  exit 0
fi
if ! hide_output hide_errors command -v tmux; then
  printf '\033[33m[e2e-test] SKIP — tmux not installed\033[0m\n'
  exit 0
fi

AVAILABLE_AGENTS=(claude)
GEMINI_MODEL=""
CODEX_MODEL=""
g=$(_probe_gemini)
if [ -n "$g" ]; then
  AVAILABLE_AGENTS+=(gemini)
  [ "$g" != "present" ] && GEMINI_MODEL="$g"
fi
c=$(_probe_codex)
if [ -n "$c" ]; then
  AVAILABLE_AGENTS+=(codex)
  [ "$c" != "present" ] && CODEX_MODEL="$c"
fi

if [ "${#AVAILABLE_AGENTS[@]}" -lt 2 ]; then
  printf '\033[33m[e2e-test] SKIP — fewer than 2 agents available: %s\033[0m\n' "${AVAILABLE_AGENTS[*]}"
  printf '          authenticate gemini and/or codex CLIs to enable this test.\n'
  exit 0
fi

echo "[e2e-test] available agents: ${AVAILABLE_AGENTS[*]}"

# ──────────── sandbox setup ────────────
SANDBOX=$(mktemp -d /tmp/debate-e2e.XXXXXX)
REPO_ROOT="$SANDBOX"
CWD="$SANDBOX"
mkdir -p "$REPO_ROOT/Debates"

TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)
DEBATE_DIR="$REPO_ROOT/Debates/${TIMESTAMP}_e2e-test"
mkdir -p "$DEBATE_DIR"

# Small, factually-bounded topic so agents converge in <2 min/round.
cat > "$DEBATE_DIR/topic.md" <<'TOPIC'
Should Python source files end with a final newline?
TOPIC

cat > "$DEBATE_DIR/context.md" <<'CONTEXT'
A short factual technical question. Each agent should provide a brief,
focused position with at most 2-3 supporting points. Keep responses
concise — under 500 words per round.
CONTEXT

: > "$DEBATE_DIR/invoking_transcript.txt"

# Build settings.json by interpolating REPO_ROOT into the production template.
TMPDIR_INV=$(mktemp -d /tmp/debate.XXXXXX)
SETTINGS_FILE="$TMPDIR_INV/settings.json"
sed "s|\${REPO_ROOT}|$REPO_ROOT|g" \
  "$PLUGIN_ROOT/skills/debate/scripts/assets/permissions.default.json" \
  > "$SETTINGS_FILE"

# Build R1 instructions via the production prompt builder (no duplication).
for a in "${AVAILABLE_AGENTS[@]}"; do
  if ! DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" AGENT_FILTER="$a" \
       bash "$SCRIPTS_DIR/debate-build-prompts.sh" r1 "$DEBATE_DIR" "$PLUGIN_ROOT"; then
    nope "build R1 instructions for $a"
    rm -rf "$SANDBOX" "$TMPDIR_INV"
    exit 1
  fi
done
echo "[e2e-test] R1 instructions built for: ${AVAILABLE_AGENTS[*]}"

# ──────────── claim a debate-<N> tmux session ────────────
SESSION=""
n=1
keepalive_cmd='exec sh -c '\''trap "" INT HUP TERM; printf "[debate e2e keepalive]\n"; exec tail -f /dev/null'\'''
while [ "$n" -lt 1000 ]; do
  candidate="debate-$n"
  if hide_errors tmux new-session -d -s "$candidate" -x 200 -y 60 -n main "$keepalive_cmd"; then
    SESSION="$candidate"
    break
  fi
  n=$((n + 1))
done
if [ -z "$SESSION" ]; then
  printf '\033[31m[e2e-test] FAIL — could not claim debate-<N> session (1000 already in use)\033[0m\n'
  rm -rf "$SANDBOX" "$TMPDIR_INV"
  exit 1
fi
echo "[e2e-test] tmux session: $SESSION"

hide_errors tmux set-option -t "$SESSION" remain-on-exit off
hide_errors tmux set-option -t "$SESSION" pane-border-status top
hide_errors tmux set-option -t "$SESSION" pane-border-format ' #{pane_title} '
hide_errors tmux select-pane -t "${SESSION}:main" -T "keepalive:e2e-test"

# Cleanup: kill session + sandbox on success; preserve both on failure for inspection.
cleanup_session() {
  if [ "$fail" -gt 0 ]; then
    printf '\033[33m[e2e-test] preserving artifacts for inspection:\033[0m\n'
    printf '           tmux: tmux attach -t %s\n' "$SESSION"
    printf '           dir:  %s\n' "$DEBATE_DIR"
    printf '           log:  %s\n' "$ORCH_LOG"
    return
  fi
  hide_errors tmux kill-session -t "$SESSION"
  rm -rf "$SANDBOX" "$TMPDIR_INV"
}
trap cleanup_session EXIT INT TERM

# ──────────── run the orchestrator daemon foreground ────────────
ORCH_LOG="$DEBATE_DIR/orchestrator.log"
echo "[e2e-test] running orchestrator (real agents — expect 5–10 min)"
echo "[e2e-test] orchestrator log: $ORCH_LOG"
echo "[e2e-test] live progress: tmux attach -t $SESSION"
echo

t0=$SECONDS
GEMINI_MODEL="$GEMINI_MODEL" CODEX_MODEL="$CODEX_MODEL" \
DEBATE_AGENTS="${AVAILABLE_AGENTS[*]}" COMPOSITION_DRIFTED=0 \
SESSION="$SESSION" \
  bash "$SCRIPTS_DIR/debate-tmux-orchestrator.sh" \
    "$DEBATE_DIR" "$SESSION" "main" "$SETTINGS_FILE" "$CWD" "$REPO_ROOT" "$PLUGIN_ROOT" \
    >> "$ORCH_LOG" 2>&1
rc=$?
total_wall=$((SECONDS - t0))
echo "[e2e-test] orchestrator finished after ${total_wall}s with rc=$rc"
echo

# ──────────── assertions ────────────
if [ "$rc" -eq 0 ]; then
  ok "orchestrator daemon exited 0"
else
  nope "orchestrator daemon exited $rc"
fi

if [ -s "$DEBATE_DIR/synthesis.md" ]; then
  size=$(wc -c < "$DEBATE_DIR/synthesis.md" | tr -d ' ')
  ok "synthesis.md produced (${size} bytes)"
else
  nope "synthesis.md missing or empty"
fi

if [ -d "$DEBATE_DIR/archive" ]; then
  ok "archive/ directory created"
  for a in "${AVAILABLE_AGENTS[@]}"; do
    if [ -s "$DEBATE_DIR/archive/r1_${a}.md" ]; then
      ok "archive/r1_${a}.md present"
    else
      nope "archive/r1_${a}.md missing"
    fi
    if [ -s "$DEBATE_DIR/archive/r2_${a}.md" ]; then
      ok "archive/r2_${a}.md present"
    else
      nope "archive/r2_${a}.md missing"
    fi
  done
else
  nope "archive/ directory not created"
fi

if [ -f "$DEBATE_DIR/FAILED.txt" ]; then
  nope "FAILED.txt present at top level — daemon reported a failure"
  echo "    --- FAILED.txt ---"
  sed 's/^/    /' "$DEBATE_DIR/FAILED.txt" | head -40
fi

# Parallelism wall-clock assertion. Per-agent budget = 120s ready + 30s prompt
# ≈ 150s. Parallel: stage wall ≈ max(per-agent) ≈ 30–150s. Serial: stage wall
# ≈ N × per-agent ≈ 200–450s. Threshold 200s catches serial regression with
# generous slack for slow cold-starts.
PARALLEL_THRESHOLD=200
src=""
if [ -f "$DEBATE_DIR/archive/orchestrator.log" ]; then
  src="$DEBATE_DIR/archive/orchestrator.log"
elif [ -f "$ORCH_LOG" ]; then
  src="$ORCH_LOG"
fi

if [ -z "$src" ]; then
  nope "orchestrator.log not found (looked in archive/ and top level)"
else
  for stage in r1 r2; do
    wall=$(hide_errors grep "launch_agents_parallel ${stage}:" "$src" \
      | sed -n 's/.*workers, \([0-9]*\)s wall.*/\1/p' | head -1)
    if [ -z "$wall" ]; then
      nope "stage ${stage}: no 'launch_agents_parallel' wall-clock log line"
    elif [ "$wall" -lt "$PARALLEL_THRESHOLD" ]; then
      ok "stage ${stage} launched in ${wall}s (< ${PARALLEL_THRESHOLD}s — parallelism confirmed)"
    else
      nope "stage ${stage} took ${wall}s (>= ${PARALLEL_THRESHOLD}s — serial regression suspected)"
    fi
  done
fi

# ──────────── summary ────────────
printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m[e2e-test] %d passed, 0 failed (total wall: %ds)\033[0m\n' "$pass" "$total_wall"
  exit 0
else
  printf '\033[31m[e2e-test] %d passed, %d failed (total wall: %ds)\033[0m\n' "$pass" "$fail" "$total_wall"
  exit 1
fi
