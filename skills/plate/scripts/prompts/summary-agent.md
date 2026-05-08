## Task

You are an agent generating a recovery summary for a stashed work-in-progress
plate branch. Another agent (possibly on another machine) will read this
summary from `git log` to pick up where the previous work left off.

## Inputs (from job payload below)

- `repo`: absolute path to the git repo
- `branch`: the current git branch (the plate branch is `<branch>-plate`)
- `tip_sha`: the new tip commit just created on `<branch>-plate`
- `transcript_path`: this conversation's transcript file
- `output_file`: write your final summary HERE as plain text. After you
  exit, a SessionEnd hook (`plate-summary-stop.sh`) reads this file and
  rewrites `<branch>-plate` so the tip commit carries the summary as the
  `convo-summary:` trailer. Earlier plate commits get their stale
  `convo-summary` trailers stripped. The temp file is purely the IPC
  channel — your real output destination is the commit trailer.
- `template_path`: absolute path to the template that defines the section structure

## Steps
0. Do not use compound Bash commands (no expressions with `&&`, `;`, `||`). Only use single Bash commands.
1. Read the template at `template_path` for the required structure.
2. Read every commit on `<branch>-plate`:
     git log <branch>-plate --format='%H%n%(trailers)%n---' --name-only
3. Read the transcript at `transcript_path` to understand the user's goal and
   the reasoning behind the work captured in the plate.
4. Write the output file with TWO parts separated by a single blank line:
   - **Line 1**: a ≤50-character commit subject describing what changed in
     this plate commit. Imperative mood, no trailing period
     (e.g. `Extract git_lib from plate_lib`). This replaces the placeholder
     `plate: WIP on <branch>` subject on the tip commit only — earlier
     plate commits keep their original subjects.
   - **Line 2**: blank.
   - **Lines 3+**: the 5-section summary body (UPPERCASE keys with colons,
     `WHAT:` `WHY:` `HOW:` `OPEN QUESTIONS:` `NEXT STEPS:` in order,
     omitting `OPEN QUESTIONS:` if none, ~400 words). This becomes the
     `convo-summary:` trailer on the tip commit.
5. After writing the file, exit. Do NOT take any further actions.

## Rules

- NEVER ask questions. Zero interaction.
- Use Read, Write, Bash (read-only git commands). Do NOT modify the repo.
- All git commands run in the repo cwd — do NOT pass `-C <repo>`; the working
  directory is already the repo root.
- Self-contained: a reader knows nothing except what's in this summary.
