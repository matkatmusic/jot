#!/bin/bash
# upfront-instructions-test.sh — asserts debate_start_or_resume builds ALL
# per-stage instruction files (r1, r2, synthesis) at hook time, so
# prompt-build errors surface in the user-visible emit_block rather than
# 15 minutes later in the daemon.
#
# Pre-fix: daemon_main built r2 and synthesis instructions only after
# wait_for_outputs — a failed build there was invisible to the user.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
nope() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

SANDBOX=$(mktemp -d /tmp/upfront-instructions-test.XXXXXX)
TEST_REPO="$SANDBOX/repo"
mkdir -p "$TEST_REPO"
( cd "$TEST_REPO" && git init -q && git config user.email t@t && git config user.name t && git commit --allow-empty -q -m init )
DATA_DIR="$SANDBOX/data"; mkdir -p "$DATA_DIR"

# Drive debate_start_or_resume end-to-end against a fresh DEBATE_DIR.
# Stub debate_claim_session and the daemon fork so we don't actually
# spawn tmux panes or background bash.
TOPIC="paths-only-templates-r2-and-synthesis-upfront"
TIMESTAMP=$(date +%Y-%m-%dT%H-%M-%S)
SLUG=$(printf '%s' "$TOPIC" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' '-' | head -c 40 | sed 's/-$//')
DEBATE_DIR="$TEST_REPO/Debates/${TIMESTAMP}_${SLUG}"
mkdir -p "$DEBATE_DIR"
printf '%s\n' "$TOPIC" > "$DEBATE_DIR/topic.md"
printf '(no conversation context available)\n' > "$DEBATE_DIR/context.md"

AVAILABLE_AGENTS=(claude gemini codex)
GEMINI_MODEL=""; CODEX_MODEL=""
RESUMING=0
CWD="$TEST_REPO"; REPO_ROOT="$TEST_REPO"
LOG_FILE="$SANDBOX/log"
SCRIPTS_DIR="$PLUGIN_ROOT/skills/debate/scripts"
SETTINGS_FILE=""
export CLAUDE_PLUGIN_DATA="$DATA_DIR"

# Source what we need. Inject stubs BEFORE sourcing so hook helpers
# referenced by debate_start_or_resume are neutered.
. "$PLUGIN_ROOT/common/scripts/silencers.sh"
. "$PLUGIN_ROOT/common/scripts/hook-json.sh"
. "$PLUGIN_ROOT/skills/debate/scripts/debate.sh"

debate_build_claude_cmd() { SETTINGS_FILE="$SANDBOX/fake-settings.json"; echo '{}' > "$SETTINGS_FILE"; }
debate_claim_session()    { echo "debate-harness"; }
spawn_terminal_if_needed() { :; }
emit_block()              { printf 'EMIT: %s\n' "$*" ; }

# Override the daemon-fork block: we redefine the body by wrapping bash calls.
# debate_start_or_resume forks a daemon via `bash ... &; disown`. Easiest
# suppression: override `bash` symbol locally in this test scope — no, that
# would break debate-build-prompts.sh which we WANT to run. Instead, run
# debate_start_or_resume but set DEBATE_START_DRY_RUN=1 and trust the daemon
# tmux commands fail silently. The post-state check only cares about files
# on disk.
#
# Simpler: just call debate_start_or_resume and accept that the daemon will
# fail to launch (no real tmux session named `debate-harness`); the R1/R2/
# synthesis prompt-build and the instruction files are the test subject.
debate_start_or_resume 2>/dev/null >/dev/null || true

# Assertions: R1, R2, synthesis instruction files MUST exist upfront.
for a in claude gemini codex; do
  f="$DEBATE_DIR/r1_instructions_${a}.txt"
  [ -s "$f" ] && ok "r1_instructions_${a}.txt present upfront" \
               || nope "r1_instructions_${a}.txt missing or empty"
  f="$DEBATE_DIR/r2_instructions_${a}.txt"
  [ -s "$f" ] && ok "r2_instructions_${a}.txt present upfront" \
               || nope "r2_instructions_${a}.txt missing or empty"
done
f="$DEBATE_DIR/synthesis_instructions.txt"
[ -s "$f" ] && ok "synthesis_instructions.txt present upfront" \
             || nope "synthesis_instructions.txt missing or empty"

# Spot-check one R2 file references the other two agents as expected.
R2_CLAUDE="$DEBATE_DIR/r2_instructions_claude.txt"
if [ -s "$R2_CLAUDE" ] && grep -qF "r1_gemini.md" "$R2_CLAUDE" && grep -qF "r1_codex.md" "$R2_CLAUDE"; then
  ok "r2_instructions_claude.txt references gemini + codex r1 paths"
else
  nope "r2_instructions_claude.txt missing expected cross-agent references"
fi

# synthesis_instructions.txt must reference every agent's r1_*.md AND r2_*.md
# so the synthesizer can read all prior rounds.
SYNTH="$DEBATE_DIR/synthesis_instructions.txt"
synth_missing=""
for a in claude gemini codex; do
  grep -qF "r1_${a}.md" "$SYNTH" || synth_missing="$synth_missing r1_${a}.md"
  grep -qF "r2_${a}.md" "$SYNTH" || synth_missing="$synth_missing r2_${a}.md"
done
if [ -z "$synth_missing" ]; then
  ok "synthesis_instructions.txt references all r1_*.md and r2_*.md paths (3 agents × 2 rounds = 6 refs)"
else
  nope "synthesis_instructions.txt missing references:${synth_missing}"
fi

rm -rf "$SANDBOX"

printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32m[upfront-instructions-test] %d passed, 0 failed\033[0m\n' "$pass"
  exit 0
else
  printf '\033[31m[upfront-instructions-test] %d passed, %d failed\033[0m\n' "$pass" "$fail"
  exit 1
fi
