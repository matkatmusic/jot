#!/bin/bash
# detect-agents-timing-test.sh — verifies detect_available_agents() after
# smoke tests were removed. The design now is: binary-on-PATH + auth-file
# present ⇒ agent available; no network call; model pulled from
# model-fallbacks.json[<agent>][0]; launch_agent's 120s readiness timeout
# catches agents that are actually broken at R1 spawn time.
#
# Pre-fix would have run a live smoke test and blocked for up to 200-400s
# per gemini model. These assertions prove: (a) detection is fast even when
# the agent binaries would otherwise hang, (b) the probe correctly gates on
# binary + credential presence, (c) fallback models are read from JSON.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
export CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"

COUNTER_FILE=$(mktemp /tmp/detect-agents-test-counter.XXXXXX)
echo "0 0" > "$COUNTER_FILE"
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; read -r p f < "$COUNTER_FILE"; echo "$((p+1)) $f" > "$COUNTER_FILE"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; read -r p f < "$COUNTER_FILE"; echo "$p $((f+1))" > "$COUNTER_FILE"; }

# mk_env builds a sandboxed plugin root + bin dir. Each stub hangs for 600s
# if invoked, so a passing test proves the probe never ran the binary.
mk_env() {
  local fallbacks_json="$1"
  local include_gemini_stub="${2:-1}"
  local include_codex_stub="${3:-1}"
  local include_gemini_creds="${4:-1}"
  local include_codex_creds="${5:-1}"

  SANDBOX=$(mktemp -d /tmp/detect-agents-test.XXXXXX)
  mkdir -p "$SANDBOX/bin" \
           "$SANDBOX/plugin/skills/debate/scripts/assets" \
           "$SANDBOX/plugin/common/scripts" \
           "$SANDBOX/home/.gemini" \
           "$SANDBOX/home/.codex"

  [ "$include_gemini_stub" = 1 ] && { cat > "$SANDBOX/bin/gemini" <<'EOF'
#!/bin/bash
sleep 600
EOF
    chmod +x "$SANDBOX/bin/gemini"
  }
  [ "$include_codex_stub" = 1 ] && { cat > "$SANDBOX/bin/codex" <<'EOF'
#!/bin/bash
sleep 600
EOF
    chmod +x "$SANDBOX/bin/codex"
  }
  [ "$include_gemini_creds" = 1 ] && : > "$SANDBOX/home/.gemini/oauth_creds.json"
  [ "$include_codex_creds"  = 1 ] && : > "$SANDBOX/home/.codex/auth.json"

  cp "$PLUGIN_ROOT/common/scripts/silencers.sh" "$SANDBOX/plugin/common/scripts/silencers.sh"
  printf '%s' "$fallbacks_json" > "$SANDBOX/plugin/skills/debate/scripts/assets/model-fallbacks.json"
}
teardown_env() { rm -rf "$SANDBOX"; }

# ms_now — millisecond wall-clock.
ms_now() { python3 -c 'import time; print(int(time.time()*1000))'; }

run_detect() {
  (
    export PATH="$SANDBOX/bin:/usr/bin:/bin"
    export CLAUDE_PLUGIN_ROOT="$SANDBOX/plugin"
    export HOME="$SANDBOX/home"
    export LOG_FILE="$SANDBOX/log"
    unset GEMINI_API_KEY GOOGLE_API_KEY OPENAI_API_KEY
    . "$PLUGIN_ROOT/common/scripts/silencers.sh"
    . "$PLUGIN_ROOT/skills/debate/scripts/debate.sh"
    detect_available_agents
    printf 'AGENTS=%s\n' "${AVAILABLE_AGENTS[*]}"
    printf 'GEMINI_MODEL=%s\n' "$GEMINI_MODEL"
    printf 'CODEX_MODEL=%s\n' "$CODEX_MODEL"
  )
}

# ══════════════════════ TEST A: fast path ══════════════════════
echo "T1: detect is sub-second when binaries + creds exist (no live smoke test)"
mk_env '{"gemini": ["gem-1"], "codex": ["cdx-1"]}'
START=$(ms_now)
OUT=$(run_detect)
END=$(ms_now)
ELAPSED=$((END - START))
echo "    (elapsed: ${ELAPSED}ms)"
# Generous 2000ms upper bound — python3 startup + 2 jq invocations + fork/wait.
# Critical: any call into the sleep-600 stub would blow WAY past this.
if [ "$ELAPSED" -lt 2000 ]; then
  pass "elapsed ${ELAPSED}ms < 2000ms — binaries NOT invoked"
else
  fail "elapsed ${ELAPSED}ms ≥ 2000ms — live smoke test may have leaked back in"
fi
if echo "$OUT" | grep -q 'AGENTS=claude gemini codex'; then
  pass "all 3 agents detected"
else
  fail "agents wrong: $(echo "$OUT" | grep AGENTS=)"
fi
if echo "$OUT" | grep -q 'GEMINI_MODEL=gem-1$'; then pass "gemini model = gem-1 (first fallback)"
else fail "gemini model wrong: $(echo "$OUT" | grep GEMINI_MODEL=)"; fi
if echo "$OUT" | grep -q 'CODEX_MODEL=cdx-1$'; then pass "codex model = cdx-1 (first fallback)"
else fail "codex model wrong: $(echo "$OUT" | grep CODEX_MODEL=)"; fi
teardown_env

# ══════════════════════ TEST B: empty fallback list ══════════════════════
echo "T2: empty fallback list → agent present but model string is empty"
mk_env '{"gemini": [], "codex": []}'
OUT=$(run_detect)
if echo "$OUT" | grep -q 'AGENTS=claude gemini codex'; then pass "agents detected despite empty fallback lists"
else fail "agents wrong: $(echo "$OUT" | grep AGENTS=)"; fi
if echo "$OUT" | grep -q 'GEMINI_MODEL=$'; then pass "GEMINI_MODEL empty (correct for no-fallback-list)"
else fail "GEMINI_MODEL should be empty: $(echo "$OUT" | grep GEMINI_MODEL=)"; fi
teardown_env

# ══════════════════════ TEST C: presence gates ══════════════════════
echo "T3: missing binary → agent NOT available (control for binary gate)"
mk_env '{"gemini": ["gem-1"], "codex": ["cdx-1"]}' 0 1 1 1  # no gemini stub
OUT=$(run_detect)
if echo "$OUT" | grep -q '^AGENTS=claude codex$'; then
  pass "gemini absent when binary missing"
else
  fail "gemini wrongly present: $(echo "$OUT" | grep AGENTS=)"
fi
teardown_env

echo "T4: missing credentials → agent NOT available (control for auth gate)"
mk_env '{"gemini": ["gem-1"], "codex": ["cdx-1"]}' 1 1 0 1  # no gemini creds
OUT=$(run_detect)
if echo "$OUT" | grep -q '^AGENTS=claude codex$'; then
  pass "gemini absent when creds missing"
else
  fail "gemini wrongly present despite no creds: $(echo "$OUT" | grep AGENTS=)"
fi
teardown_env

# ══════════════════════ SUMMARY ══════════════════════
read -r P F < "$COUNTER_FILE"
rm -f "$COUNTER_FILE"
printf '\n'
if [ "$F" -eq 0 ]; then
  printf '\033[32m[detect-agents-timing-test] %d passed, 0 failed\033[0m\n' "$P"
  exit 0
else
  printf '\033[31m[detect-agents-timing-test] %d passed, %d failed\033[0m\n' "$P" "$F"
  exit 1
fi
