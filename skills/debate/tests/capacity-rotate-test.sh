#!/bin/bash
# capacity-rotate-test.sh — verifies the capacity-error detection + model
# rotation added to the daemon. Covers:
#   A. pane_has_capacity_error matches known error markers per-agent and
#      returns NON-zero for panes with no error.
#   B. _next_fallback_model rotates through model-fallbacks.json entries,
#      skipping already-TRIED models, returning rc=1 when exhausted.
#   C. init_agent_models seeds CURRENT_MODEL_* and TRIED_MODELS_* correctly
#      from GEMINI_MODEL / CODEX_MODEL env vars.
#   D. agent_launch_cmd appends `--model '<m>'` for gemini/codex when the
#      current model is set, and omits it when empty.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
nope() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

mk_env() {
  SANDBOX=$(mktemp -d /tmp/capacity-rotate-test.XXXXXX)
  DEBATE_DIR="$SANDBOX/debate"; mkdir -p "$DEBATE_DIR"
  SESSION="capacity-test-$$"
  WINDOW_NAME="main"
  WINDOW_TARGET="${SESSION}:${WINDOW_NAME}"
  SETTINGS_FILE="$SANDBOX/settings.json"; echo "{}" > "$SETTINGS_FILE"
  DEBATE_AGENTS="claude"
  export DEBATE_DAEMON_SOURCED=1
  export DEBATE_DIR SESSION WINDOW_NAME WINDOW_TARGET SETTINGS_FILE DEBATE_AGENTS
  . "$PLUGIN_ROOT/skills/debate/scripts/debate-tmux-orchestrator.sh"
}
teardown_env() {
  rm -rf "$SANDBOX"
  unset DEBATE_DAEMON_SOURCED
}

# ────────── A. pane_has_capacity_error ──────────
echo "T1: pane_has_capacity_error detects codex 'at capacity' string"
mk_env
tmux new-session -d -s "$SESSION" -n "$WINDOW_NAME" "sleep 60"
MSG_FILE=$(mktemp /tmp/codex-cap-msg.XXXXXX)
printf '⚠ Selected model is at capacity. Please try a different model.\n' > "$MSG_FILE"
PANE=$(tmux split-window -t "$WINDOW_TARGET" -P -F '#{pane_id}' "cat '$MSG_FILE'; sleep 60")
sleep 1
if pane_has_capacity_error "$PANE" codex >/dev/null; then
  ok "codex marker detected"
else
  nope "codex marker NOT detected"
fi
tmux kill-session -t "$SESSION"
rm -f "$MSG_FILE"
teardown_env

echo "T2: pane_has_capacity_error returns non-zero for a clean pane"
mk_env
tmux new-session -d -s "$SESSION" -n "$WINDOW_NAME" "sleep 60"
PANE=$(tmux split-window -t "$WINDOW_TARGET" -P -F '#{pane_id}' "echo 'all good'; sleep 60")
sleep 1
if pane_has_capacity_error "$PANE" codex >/dev/null; then
  nope "false positive — detected capacity on clean pane"
else
  ok "clean pane correctly returns non-zero"
fi
tmux kill-session -t "$SESSION"
teardown_env

echo "T3: pane_has_capacity_error detects gemini RESOURCE_EXHAUSTED"
mk_env
tmux new-session -d -s "$SESSION" -n "$WINDOW_NAME" "sleep 60"
MSG_FILE=$(mktemp /tmp/gemini-cap-msg.XXXXXX)
printf 'Error: [GoogleGenerativeAI Error]: RESOURCE_EXHAUSTED — quota hit\n' > "$MSG_FILE"
PANE=$(tmux split-window -t "$WINDOW_TARGET" -P -F '#{pane_id}' "cat '$MSG_FILE'; sleep 60")
sleep 1
if pane_has_capacity_error "$PANE" gemini >/dev/null; then
  ok "gemini RESOURCE_EXHAUSTED detected"
else
  nope "gemini marker NOT detected"
fi
tmux kill-session -t "$SESSION"
rm -f "$MSG_FILE"
teardown_env

echo "T4: pane_has_capacity_error detects claude overloaded_error"
mk_env
tmux new-session -d -s "$SESSION" -n "$WINDOW_NAME" "sleep 60"
MSG_FILE=$(mktemp /tmp/claude-cap-msg.XXXXXX)
printf 'API Error: 529 {"type":"overloaded_error"}\n' > "$MSG_FILE"
PANE=$(tmux split-window -t "$WINDOW_TARGET" -P -F '#{pane_id}' "cat '$MSG_FILE'; sleep 60")
sleep 1
if pane_has_capacity_error "$PANE" claude >/dev/null; then
  ok "claude overloaded_error detected"
else
  nope "claude marker NOT detected"
fi
tmux kill-session -t "$SESSION"
rm -f "$MSG_FILE"
teardown_env

# ────────── B. _next_fallback_model rotation ──────────
echo "T5: _next_fallback_model rotates through list, skipping tried"
mk_env
# Override fallbacks json in a sandboxed plugin root.
sandbox_plugin="$SANDBOX/plugin"
mkdir -p "$sandbox_plugin/skills/debate/scripts/assets"
printf '{"codex":["m1","m2","m3"],"gemini":[],"claude":[]}' \
  > "$sandbox_plugin/skills/debate/scripts/assets/model-fallbacks.json"
export CLAUDE_PLUGIN_ROOT_SAVED="$CLAUDE_PLUGIN_ROOT"
export CLAUDE_PLUGIN_ROOT="$sandbox_plugin"
init_agent_models  # seeds TRIED_MODELS_codex="" (CODEX_MODEL not set)
first=$(_next_fallback_model codex)
[ "$first" = "m1" ] && ok "first rotation picks m1" || nope "first=[$first] expected m1"
_stash TRIED_MODELS codex "m1"
second=$(_next_fallback_model codex)
[ "$second" = "m2" ] && ok "after tried=m1, next picks m2" || nope "second=[$second] expected m2"
_stash TRIED_MODELS codex "m1,m2,m3"
if _next_fallback_model codex >/dev/null; then
  nope "exhausted list should fail — got a model"
else
  ok "exhausted list returns rc=1"
fi
export CLAUDE_PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT_SAVED"
teardown_env

# ────────── C. init_agent_models from env ──────────
echo "T6: init_agent_models seeds from GEMINI_MODEL / CODEX_MODEL"
mk_env
export GEMINI_MODEL="gem-7"
export CODEX_MODEL="cdx-8"
init_agent_models
[ "$(_lookup CURRENT_MODEL gemini)" = "gem-7" ] && ok "CURRENT_MODEL_gemini seeded" \
  || nope "CURRENT_MODEL_gemini wrong: [$(_lookup CURRENT_MODEL gemini)]"
[ "$(_lookup CURRENT_MODEL codex)"  = "cdx-8" ] && ok "CURRENT_MODEL_codex seeded" \
  || nope "CURRENT_MODEL_codex wrong: [$(_lookup CURRENT_MODEL codex)]"
[ "$(_lookup TRIED_MODELS gemini)" = "gem-7" ] && ok "TRIED_MODELS_gemini seeded" \
  || nope "TRIED_MODELS_gemini wrong: [$(_lookup TRIED_MODELS gemini)]"
unset GEMINI_MODEL CODEX_MODEL
teardown_env

# ────────── D. agent_launch_cmd + --model ──────────
echo "T7: agent_launch_cmd appends --model when CURRENT_MODEL is set"
mk_env
_stash CURRENT_MODEL codex "gpt-5.3-codex"
CMD=$(agent_launch_cmd codex)
if echo "$CMD" | grep -qF -e "--model 'gpt-5.3-codex'"; then
  ok "codex --model flag present when CURRENT_MODEL_codex is set"
else
  nope "codex cmd missing --model: [$CMD]"
fi
_stash CURRENT_MODEL codex ""
CMD=$(agent_launch_cmd codex)
if echo "$CMD" | grep -qF -e "--model"; then
  nope "codex cmd should NOT have --model when CURRENT_MODEL empty: [$CMD]"
else
  ok "codex cmd omits --model when CURRENT_MODEL empty"
fi
teardown_env

# ────────── Summary ──────────
printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m[capacity-rotate-test] %d passed, 0 failed\033[0m\n' "$pass"
  exit 0
else
  printf '\033[31m[capacity-rotate-test] %d passed, %d failed\033[0m\n' "$pass" "$fail"
  exit 1
fi
