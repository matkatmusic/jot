---
name: todo-clean
description: Clean up stale TODOs by comparing each open TODO against git history since its creation timestamp. Asks before marking each as done. Use when user says "/todo-clean", "clean up todos", "check for resolved todos", or "prune stale todos".
---

# /todo-clean — Resolve Stale TODOs

Scan open TODOs and check if git history suggests they've been resolved.

## Workflow

1. **Check for Todos/ directory**. If it doesn't exist, say "No Todos/ folder found." and stop.
2. **Read all `.md` files in `Todos/`** (not `Todos/done/`). Parse YAML frontmatter for: id, title, status, created, branch.
3. **For each open TODO**:
   a. Extract the `created` timestamp from frontmatter.
   b. Run `git log --oneline --since="{created}" -- .` to get all commits from that timestamp to now.
   c. Read the TODO's Idea, Context, and Dependencies sections.
   d. Compare the commit messages and changed files against the TODO's description. Look for:
      - Commits that reference the same feature/area described in the TODO
      - Files mentioned in the TODO's "Uncommitted files" that have since been committed
      - Keywords from the TODO title appearing in commit messages
   e. If evidence suggests the TODO was resolved, present it to the user via `AskUserQuestion`:
      - question: "Mark TODO {id} ({title}) as done?"
      - options: ["Yes — move to Todos/done/", "No — keep open", "Skip — review later"]
   f. If the user picks "Yes", move the file to `Todos/done/` and update frontmatter: set `status: done` and add `resolved: {current ISO timestamp}`.
4. **If no TODOs appear resolved**, say "All open TODOs still look active."
5. **Print summary**: "Cleaned N of M open TODOs. K remaining."

## Rules

- Always ask before moving a TODO to done. Never auto-resolve.
- Create `Todos/done/` if it doesn't exist.
- If a TODO has no `created` timestamp, check the full git history and warn about the missing date.
- If not in a git repo, say "Cannot clean TODOs without git history." and stop.
- Read-only on all files except the TODO files being moved/updated.
- Be conservative: only flag a TODO as resolved when commit evidence is reasonably clear. When uncertain, skip it.
