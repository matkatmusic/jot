# Convo-Summary Template

Recovery summary for a stashed work-in-progress plate branch. A reader on
another machine reads this from `git log <branch>-plate -1 --format='%(trailers)'`
to pick up where the previous work left off.

## Output file structure

The agent's output file has TWO parts separated by a single blank line:

```
<subject line>

<5-section summary body>
```

### Part 1 — subject (line 1 of the output file)

A single concise line summarizing what changed in this plate commit. Replaces
the placeholder commit subject (`plate: WIP on <branch>`) on the **tip commit only**;
earlier plate commits keep their original subjects untouched.

Rules:
- **≤ 50 characters** (hard limit).
- Imperative mood, no trailing period (matches git's standard subject style).
- Describe what changed in THIS commit, not what the broader work is about.

Examples:
- `Extract git_lib from plate_lib`
- `Add summary template for cross-machine handoff`
- `Fix non-numeric index guard in plate_next`
- `Refactor plate_recycle to honor saved parent SHA`

### Part 2 — 5-section summary body (line 3+)

Target length: ~400 words. Hard cap 600.

Use these 5 sections, in this order, with UPPERCASE keys followed by a colon.
**Each section label MUST sit on its own line** with the section content on
the lines below it (a blank line between sections is fine but optional). The
trailer-rewrite pipeline (`_rebase_reword_summary.py::_format_trailer_body`)
preserves these line breaks via git's continuation-indent rule, so when a
reader runs `git log -1 --format='%(trailers)'` they see the labels rendered
on their own lines.

Bad (label inline with content — collapses into one wall of text):

```
WHAT: extracted git_lib from plate_lib
WHY: needed for python migration
```

Good (label on its own line):

```
WHAT:
extracted git_lib from plate_lib so plate_lib can shrink to plate-specific
orchestration.

WHY:
part of the larger jot Python migration.

HOW:
moved the helpers verbatim, then added a thin shim back in git.sh.

OPEN QUESTIONS:
- whether to keep the shim long-term or drop it next milestone

NEXT STEPS:
- write integration test for the shim
- update PLATE STATE.md
```

Section guidance:

WHAT:
  2-4 sentences describing the concrete work that's been done across this
  plate branch — files/features touched and what state they're in.

WHY:
  1-3 sentences on the underlying goal — what problem is this solving.

HOW:
  2-4 sentences on the approach taken — key technical decisions and the
  reasoning behind them.

OPEN QUESTIONS:
  Bullet list of unresolved items the next agent must decide.
  Omit this section entirely if there are none.

NEXT STEPS:
  1-4 bullets of concrete actions for the next agent.
