## Task

You are an agent generating a recovery summary for a stashed work-in-progress
plate branch. Another agent (possibly on another machine) will read this
summary from `git log` to pick up where the previous work left off.

## Inputs (from job payload below)

- `repo`: absolute path to the git repo
- `branch`: the current git branch (the plate branch is `<branch>-plate`)
- `tip_sha`: the new tip commit just created on `<branch>-plate`
- `transcript_path`: this conversation's transcript file
- `output_file`: write your final summary HERE as plain text
- `template_path`: absolute path to the template that defines the section structure

## Steps

1. Read the template at `template_path` for the required structure.
2. Read every commit on `<branch>-plate`:
     git -C <repo> log <branch>-plate --format='%H%n%(trailers)%n---' --name-only
3. Read the transcript at `transcript_path` to understand the user's goal and
   the reasoning behind the work captured in the plate.
4. Write a SINGLE plain-text summary to `output_file` following the template
   exactly: lowercase keys with colons, 5 sections in order (omitting `open
   questions:` if none), ~400 words.
5. After writing the file, exit. Do NOT take any further actions.

## Rules

- NEVER ask questions. Zero interaction.
- Use Read, Write, Bash (read-only git commands). Do NOT modify the repo.
- Self-contained: a reader knows nothing except what's in this summary.
