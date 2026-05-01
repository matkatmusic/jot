# Convo-Summary Template

Recovery summary for a stashed work-in-progress plate branch. A reader on
another machine reads this from `git log <branch>-plate -1 --format='%(trailers)'`
to pick up where the previous work left off.

Target length: ~400 words. Hard cap 600.

Use these 5 sections, in this order, with lowercase keys followed by a colon:

what:
  2-4 sentences describing the concrete work that's been done across this
  plate branch — files/features touched and what state they're in.

why:
  1-3 sentences on the underlying goal — what problem is this solving.

how:
  2-4 sentences on the approach taken — key technical decisions and the
  reasoning behind them.

open questions:
  Bullet list of unresolved items the next agent must decide.
  Omit this section entirely if there are none.

next steps:
  1-4 bullets of concrete actions for the next agent.
