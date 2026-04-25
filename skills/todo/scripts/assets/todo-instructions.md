IMPORTANT: All file paths named in these instructions are absolute. Use
absolute file paths in every tool call — never emit relative paths.

You are creating a TODO file from a captured idea. Steps:

1. Read the "## Idea", "## Git State", "## Open TODO Files", "## Recent Conversation", "## Transcript Path" sections of your input file (which you have already read per your SessionStart prompt). "## Recent Conversation" is always present — use it directly as your primary context source.

2. Derive a slug from the idea — kebab-case, ≤5 words from the core topic. Example: idea "implement colorblind-safe palette for plate render-tree" → slug "colorblind-safe-palette-render-tree".

3. SCAN "## Open TODO Files" for existing TODOs related to this idea (semantic match, not substring). If there is a strong match, APPEND instead of CREATE (see step 4b).

3b. Determine the "Active plan" field: list ${REPO_ROOT}/.claude/plans/ via Read (the allowlist permits this). If exactly one `.md` file exists and its name maps to the current session's active task, use it. Otherwise use the literal string "None".

4a. CREATE NEW: Write ${REPO_ROOT}/Todos/${TIMESTAMP}_<slug>.md with this exact structure:

---
id: ${TIMESTAMP}
title: <short title derived from idea, ≤60 chars>
status: open
created: <ISO 8601 timestamp with timezone>
branch: ${BRANCH}
---

## Idea
<idea section verbatim from input.txt>

## Context
<2-3 sentences synthesized from Recent Conversation + Git State>

## Recent commits
<Commits line from Git State, one per line prefixed with "- ">

## Uncommitted files
<Uncommitted list from Git State, one per line prefixed with "- ", or "None">

## Active plan
<Path resolved in step 3b, or "None">

## Dependencies
<Libraries, designs, decisions, other TODOs this needs — or "None" if standalone>

4b. APPEND: Edit the matched existing TODO. Update its ## Context section (max 3 sentences added). Do NOT change the frontmatter id.

5. Read back your written file with the Read tool to verify the frontmatter and ## Idea match.

6. ONLY AFTER step 5 succeeds, use the Write tool to OVERWRITE ${INPUT_ABS} with this exact single-line content (no header, no extra lines):
   PROCESSED: <absolute path of the TODO file you wrote/appended>
   This is the success marker AND audit trail. The sandbox blocks rm; overwriting via Write is the canonical success signal.

7. Output ONLY the absolute path of the TODO file to stdout. Nothing else. No commentary.

Rules:
- NEVER ask questions. Zero interaction. (Clarification was handled by the foreground claude.)
- Use Read/Write/Edit for all file operations (no Bash calls required — the worker uses only Read/Write/Edit).
- NEVER attempt to rm or delete ${INPUT_ABS}. Overwrite via Write.
- All file paths MUST be absolute. Never use relative paths like Todos/foo.md.
- "## Recent Conversation" is always provided — do NOT attempt to Read the transcript file path named in the "## Transcript Path" section yourself; the launcher has already extracted the relevant window.
