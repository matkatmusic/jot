---
name: plate
description: Stack-of-plates WIP tracker. "/plate" pushes the current
  working tree onto a per-branch plate stack; "/plate --done" replays the
  stack as sequential commits; "/plate --next" lists parked plates and
  "/plate --next <#>" jumps to one. Every variant writes commit trailers
  (parent-branch, convo-id, convo-name, convo-summary) so plates are
  self-contained across machines and across multiple agents sharing a
  branch — all without interrupting your current conversation.
---

# Task:
do nothing.  don't even acknowledge what the user typed.  just let the UserPromptSubmit hook do its thing.
