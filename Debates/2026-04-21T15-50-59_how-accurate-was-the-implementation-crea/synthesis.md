# Synthesis — /debate extraction accuracy (test.sh → skills/debate/scripts/)

## 1. Topic

How faithfully did the production `skills/debate/scripts/` implementation extract the validated flow from `skills/debate/tests/test.sh`?

## 2. Agreement

All three agents converge on the same fact pattern:

- **Core loop is faithful.** R1 → kill R1 panes → build R2 prompts → R2 → kill R2 panes → synthesis is ported correctly. `launch_agent`, `send_prompt`, and `wait_for_outputs` are near-verbatim copies (only `[test]` → `[orch]` log prefix changed).
- **Production additions are legitimate improvements**, not drift: daemon fork-and-disown, `--settings`/`--add-dir` Claude permission injection, `tmux resize-window` for detached sessions, `wait_for_file` blocking on `synthesis.md`.
- **Hardcoded `$HOME/Programming/dotfiles/...` capture-script path is a blocker** (unanimous R1 — Gemini risk 1, Claude defect 1, and Codex agreed by R2). Must be resolved to a plugin-relative path.
- **`detect_available_agents` is dead code beside a hardcoded `AVAILABLE_AGENTS=(gemini codex claude)`** (Claude + Codex R1; Gemini conceded R2). Users missing gemini/codex auth get silent daemon failures that the hook reports as success.

## 3. Disagreement

### Orchestrator-pane removal

- **Codex R1:** material inaccuracy / behavior change.
- **Gemini R1 + Claude R1:** intentional adaptation — a test-harness artifact correctly dropped because the daemon is the driver, not a pane.
- **Resolution:** Codex conceded R2. Consensus: intentional, but should be documented with a one-line rationale at the top of `debate-tmux-orchestrator.sh`.

### Severity of `[ -s "$out" ]` polling

- **Gemini R1:** "fatal polling flaw" — fires on first byte, kills panes mid-stream.
- **Claude R2:** narrower — agents use the atomic Write tool (temp-then-rename), so the file doesn't exist until it's complete. Race only materializes if a future agent streams or uses shell redirection.
- **Codex R2:** middle ground — predicate is underspecified and unsafe, but not proven fatal on current write semantics.
- **Resolution:** real latent risk; not a live bug. Hardening (sentinel footer or pane-idle check) is worth adding, but not urgent.

### Missing pre-stage `rm -f`

- **Claude R1:** defect; matters for retries/slug collisions.
- **Gemini R1 + Codex R1:** obsolete — `Debates/<ts>_<slug>/` is unique per run.
- **Resolution:** Claude conceded R2. Demoted from Medium-low to latent. Re-add only before any resume/retry feature ships.

## 4. Strongest Arguments

| Argument | Source | Why it survives |
|---|---|---|
| Hardcoded dotfiles path breaks every non-author machine | Claude R1 / Gemini R1 | Unanimous, plainly machine-specific, trivial fix |
| Dead `detect_available_agents` + hardcoded agent list → silent daemon failure | Claude R1 / Codex R1 | Two independent reads converged; failure mode is invisible to the hook caller |
| "Test-to-prod assumption leak" as a *category* | Codex R1 (framing) | Predicts where remaining defects live: send_prompt timeout, keepalive session lifecycle, tmp cleanup — all inherited attended-test assumptions |
| Operational context change — detached daemons amplify otherwise-tolerable fragilities | Claude R2 / Codex R2 | Reframes "faithful extraction" vs. "production-ready extraction" |

## 5. Weaknesses (arguments successfully challenged in R2)

- **Codex's orchestrator-pane "material inaccuracy"** — overstated; conceded.
- **Gemini's "fatal" framing of `-s` polling** — overstated given Write-tool atomicity; softened to underspecified/latent.
- **Claude's "missing `rm -f`" as a current defect** — overstated given fresh timestamped dirs; conceded as latent.
- **Claude's proposed capture-script replacement path** (`common/scripts/jot/capture_transcript.py`) — wrong. Verified location is `skills/jot/scripts/capture-conversation.py` (Gemini's path is correct).
- **Claude's `/tmp` reboot-cleaner mid-debate scenario** — conjectural without evidence about macOS `periodic` timing; the leak itself is real, the mid-debate race is speculative.

## 6. Path Forward (priority order)

_All path-forward items from this synthesis have been resolved; see the change history in `skills/debate/scripts/*` and `Todos/done/008_use-detect-available-agents.md`._

## 7. Confidence

**High** on the diagnosis. Three independent readings converged on the same inner-loop-faithful, boundary-brittle pattern. Concrete file/line evidence was cited by all three agents and cross-verified in R2.

**Medium** on a few specific severities: the `-s` race and the `/tmp` reboot-cleaner scenario are plausible but unverified at runtime, and the right fix depends on whether future agents will ever stream or use non-atomic writes.

## 8. Open Questions

- Does macOS `periodic`/tmp-cleaner realistically fire inside a typical debate duration? Needs empirical timing.
- Is the hardcoded three-agent list a deliberate product choice (not documented) or unintentional test-leak? Affects whether fix #2 is "call detect" or "explicit require-all-three".
- Does `capture-pane -p` reliably echo the typed marker at 200×60 detached size for `claude`'s TUI? `test.sh` validated under attended sizes only; behavior in the daemon path is unverified.
- Should the keepalive `debate` session be per-invocation (torn down on EXIT) or persistent across debates? Current implicit answer (persistent) was inherited from the test; no explicit product decision recorded.
