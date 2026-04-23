#!/bin/bash
# debate-build-prompts.sh — builds per-stage instruction files from templates.
# Usage: DEBATE_AGENTS="claude gemini codex" debate-build-prompts.sh <stage> <debate_dir> <plugin_root>
#   stage: r1 | r2 | synthesis
# DEBATE_AGENTS env var: space-separated list of active agents for this debate.
# AGENT_FILTER env var (optional): when set to an agent name, only emit that
#   agent's instruction file. AGENTS list still drives composition context
#   (for R2's "others" loop and synthesis's full-roster refs). Allows a
#   just-in-time rebuild for a newly-added agent without touching existing
#   per-agent instruction files.
set -euo pipefail

STAGE="$1"
DEBATE_DIR="$2"
PLUGIN_ROOT="$3"

RENDER="$PLUGIN_ROOT/common/scripts/jot/render_template.py"

if [ -n "${DEBATE_AGENTS:-}" ]; then
  read -ra AGENTS <<< "$DEBATE_AGENTS"
else
  AGENTS=()
  while IFS= read -r line; do
    [ -n "$line" ] && AGENTS+=("$line")
  done < "$DEBATE_DIR/agents.txt"
fi

FILTER="${AGENT_FILTER:-}"
_emit_for_agent() {
  [ -z "$FILTER" ] && return 0
  [ "$FILTER" = "$1" ] && return 0
  return 1
}

case "$STAGE" in
  r1)
    for agent in "${AGENTS[@]}"; do
      _emit_for_agent "$agent" || continue
      DEBATE_DIR="$DEBATE_DIR" \
      OUTPUT_FILE="$DEBATE_DIR/r1_${agent}.md" \
        python3 "$RENDER" \
          "$PLUGIN_ROOT/skills/debate/prompts/r1.template.md" \
          DEBATE_DIR OUTPUT_FILE \
        > "$DEBATE_DIR/r1_instructions_${agent}.txt"
    done
    ;;

  r2)
    # Dynamic: agent count varies (2 or 3). Generated inline, not from template.
    for agent in "${AGENTS[@]}"; do
      _emit_for_agent "$agent" || continue
      others=()
      for other in "${AGENTS[@]}"; do
        [ "$other" = "$agent" ] && continue
        others+=("$other")
      done
      {
        printf '# Debate — Round 2: Cross-Critique\n\n'
        printf '## Your Round 1 Response\nRead from: %s\n\n' "$DEBATE_DIR/r1_${agent}.md"
        printf '## Other Agents'\'' Round 1 Responses\n'
        for other in "${others[@]}"; do
          printf 'Read %s'\''s response from: %s\n' "$other" "$DEBATE_DIR/r1_${other}.md"
        done
        printf '\n## Instructions\n'
        # Lead with %s so the '-' prefix isn't parsed as a printf option flag.
        printf '%s\n' '- Identify agreement and disagreement across responses'
        printf '%s\n' '- Validate or challenge claims with evidence'
        printf '%s\n' '- Concede where others made stronger arguments'
        printf '%s\n' '- Raise new considerations from reading their perspectives'
        printf '\n## Output\nWrite your critique as markdown to: %s\nDo not write to any other file.\n' "$DEBATE_DIR/r2_${agent}.md"
      } > "$DEBATE_DIR/r2_instructions_${agent}.txt"
    done
    ;;

  synthesis)
    {
      printf '# Debate — Round 3: Synthesis\n\n'
      printf '%d agents (%s) debated across two rounds. Produce a balanced assessment.\n\n' \
        "${#AGENTS[@]}" "${AGENTS[*]}"
      printf '## Round 1 Responses\n'
      for agent in "${AGENTS[@]}"; do
        printf 'Read %s R1 from: %s\n' "$agent" "$DEBATE_DIR/r1_${agent}.md"
      done
      printf '\n## Round 2 Responses\n'
      for agent in "${AGENTS[@]}"; do
        printf 'Read %s R2 from: %s\n' "$agent" "$DEBATE_DIR/r2_${agent}.md"
      done
      printf '\n## Structure\n'
      printf '1. **Topic**: One-line restatement\n'
      printf '2. **Agreement**: Where agents align\n'
      printf '3. **Disagreement**: Where they diverge, strongest argument per side\n'
      printf '4. **Strongest Arguments**: Most compelling points, attributed\n'
      printf '5. **Weaknesses**: Arguments successfully challenged in R2\n'
      printf '6. **Path Forward**: Synthesized recommendation\n'
      printf '7. **Confidence**: High/Medium/Low with reasoning\n'
      printf '8. **Open Questions**: Unresolved issues\n'
      printf '\n## Output\nWrite synthesis as markdown to: %s\nDo not write to any other file.\n' "$DEBATE_DIR/synthesis.md"
    } > "$DEBATE_DIR/synthesis_instructions.txt"
    ;;

  *) echo "Unknown stage: $STAGE" >&2; exit 1 ;;
esac
