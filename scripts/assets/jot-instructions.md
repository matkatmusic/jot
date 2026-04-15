IMPORTANT: All file paths named in these instructions are absolute. Use
absolute file paths in every tool call — never emit relative paths.

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

5a. CREATE NEW: Write to ${REPO_ROOT}/Todos/${TIMESTAMP}_<slug>.md where <slug> is the idea kebab-cased and truncated to 5-6 words. Use this frontmatter format:
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

7. ONLY AFTER step 6 succeeds, use the Write tool to OVERWRITE ${INPUT_ABS} with this exact single-line content (no header, no extra lines):
   PROCESSED: ${REPO_ROOT}/Todos/<the slug filename you wrote in step 5>
   This is the success marker AND audit trail. The sandbox blocks rm; do NOT attempt to delete the file. Overwriting via Write is allowed and is the canonical success signal.

8. Output ONLY the absolute path of the TODO file to stdout. Nothing else. No commentary.

Rules:
- NEVER ask questions. Zero interaction.
- NEVER run Bash commands. Use ONLY the Read, Write, and Edit tools for every step. Bash is not in the allowlist and will trigger a permission prompt that blocks this workflow. In particular, do NOT use `ls`, `cat`, `test -f`, or any other shell command to check whether a file exists before reading it — just call Read and handle the error case inline.
- Store conversation pairs verbatim. No summarization.
- Keep ## Context concise. No file contents, no diffs, no quoted code blocks.
- The TODO file is the PRIMARY artifact; the PROCESSED: marker on ${INPUT_ABS} is the success signal.
- NEVER attempt to rm or delete ${INPUT_ABS}. Overwrite it via the Write tool instead.
- All file paths MUST be absolute. Never use relative paths like Todos/foo.md.
- If the transcript fallback in step 3 fails (file missing, unreadable, no matches), use the literal context string and continue. Never crash.
