# R1 — Claude: Audit of `mighty-exploring-kitten.md`

## Verdict

The plan correctly identifies **most** of the runtime bugs, but it (a) **overstates the blast radius of Bug A**, (b) **omits the migration-path defect** that will leave existing v1.1.0 installs broken even after the fix ships, and (c) **lacks concrete code for two new test files and the `todo-instructions.md` step-8 rewrite** that the plan claims will be made. Net: ship-able after the corrections below.

---

## 1. Bug A is real but **half** of it is already masked by a compat shim

### The plan's claim

> Claude will silently deny every Read/Write/Edit in the worker.

### What the source actually says

`common/scripts/jot/expand_permissions.py:30-56` contains a **non-destructive in-memory migration shim** that unconditionally injects:

```python
required = [
    "Write(//${REPO_ROOT}/Todos/**)",
    "Edit(//${REPO_ROOT}/Todos/**)",
]
for rule in required:
    if rule not in allow:
        allow.append(rule)
```

So the **`Write`/`Edit` rules are not actually broken** at runtime — the shim guarantees the absolute-path forms are present in the expanded allow array regardless of what the on-disk file says. Only the `Read` rules in `permissions.default.json:5,8` are genuinely broken:

```json
"Read(${REPO_ROOT}/Todos/**)",          // expands to Read(Users/.../Todos/**) — cwd-relative, denied
"Read(${REPO_ROOT}/.claude/plans/**)",  // same defect
```

### Why this matters for the plan

- The plan's framing ("every Read/Write/Edit … silently deny") is **factually wrong** — and that misframing leaves the **real** Read-rule defect rhetorically buried.
- The plan's fix (add `//` to all four path-anchor rules) is still **correct as a hygiene fix** — it removes the latent bug if the shim is ever removed and aligns the source with `assets/permissions.default.json` and `skills/plate/scripts/assets/permissions.default.json`.
- But the plan must also **decide whether to widen the shim** to cover the `Read` rules, because of issue 2 below.

---

## 2. Plan **omits** the migration defect: existing installs won't pick up the fix

### Evidence

`common/scripts/permissions-seed.sh` (per the existing audit, observation 2230) implements **three-state install logic**: `unmodified` → reseed; `modified-by-plugin` → reseed; `modified-by-user` → **leave alone**. Any user who upgraded `v1.0 → v1.1.0` will already have a `${CLAUDE_PLUGIN_DATA}/todo-permissions.local.json` that the seed script considers "user-edited" (because the v1.1.0 install wrote it), and `v1.1.1` will not overwrite it. Result: **the path-anchor fix in the bundled default never reaches existing installs.**

### Concrete fix — extend the shim to also inject the missing `Read` rules

```python
# common/scripts/jot/expand_permissions.py — augment the existing shim
required = [
    "Write(//${REPO_ROOT}/Todos/**)",
    "Edit(//${REPO_ROOT}/Todos/**)",
    "Read(//${REPO_ROOT}/Todos/**)",
    "Read(//${REPO_ROOT}/.claude/plans/**)",
]
LEGACY_PATTERNS = (
    "Write(Todos/", "Edit(Todos/",
    "Read(Todos/", "Read(.claude/plans/",
    "Read(${REPO_ROOT}/", "Write(${REPO_ROOT}/",
    "Edit(${REPO_ROOT}/",
)
```

This is the only way the plan's path-anchor fix becomes load-bearing for v1.1.0 → v1.1.1 upgraders. **Without this, the plan ships a bundled-default fix with zero runtime effect on the affected user base.**

---

## 3. Bug B (Bash rules) — fix is correct, but plan provides no test scaffold

The plan's diagnosis is exactly right: `lstrip("/")` strips the leading `/` from `${REPO_ROOT}`, so `Bash(bash ${REPO_ROOT}/…)` expands to `Bash(bash Users/…)` while the worker actually invokes `bash /Users/…`. Literal-prefix mismatch.

### Plan's proposed fix

```json
"Bash(bash /${REPO_ROOT}/skills/todo/scripts/scan-existing-todos.sh:*)",
"Bash(rm -f /${REPO_ROOT}/Todos/.todo-state/id-*.claim:*)"
```

### Concrete test (the plan promises but doesn't write `permissions-expand-test.sh`)

```bash
#!/bin/bash
# skills/todo/tests/permissions-expand-test.sh
# Asserts expand_permissions.py emits filesystem-absolute paths for every
# Read/Write/Edit rule and a literal "/" before ${REPO_ROOT} in every Bash rule.
set -euo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SELF_DIR/../../.." && pwd)"
PERMS="$REPO/skills/todo/scripts/assets/permissions.default.json"
EXPAND="$REPO/common/scripts/jot/expand_permissions.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAKE_REPO="/tmp/fake-repo-$$"

OUT="$(
  CWD="$FAKE_REPO" HOME="/Users/test" REPO_ROOT="$FAKE_REPO" \
  python3 "$EXPAND" "$PERMS"
)"

# Assertion 1: no unexpanded ${IDENT} survives.
if printf '%s' "$OUT" | grep -E '\$\{[A-Z_][A-Z0-9_]*\}' >/dev/null; then
  echo "FAIL: unexpanded placeholder in expand_permissions output:" >&2
  printf '%s\n' "$OUT" >&2
  exit 1
fi

# Assertion 2: every Read(/Write(/Edit( with a path argument starts with // or ~/.
while IFS= read -r rule; do
  case "$rule" in
    Read\(\*\*\)*) continue ;;                           # Read(**) is absolute by construction
    Read\(\~/*|Read\(//*|Write\(//*|Edit\(//*) ;;        # ok
    Read\(*|Write\(*|Edit\(*)
      echo "FAIL: non-anchored path rule: $rule" >&2; exit 1 ;;
  esac
done < <(printf '%s\n' "$OUT" | python3 -c '
import json, sys
for r in json.load(sys.stdin):
    print(r)
')

# Assertion 3: every Bash(bash ...) entry contains " /" (a literal space then /)
#  before the path, so it prefix-matches the actual command the worker runs.
while IFS= read -r rule; do
  case "$rule" in
    "Bash(bash /"*) ;;
    Bash\(bash*)
      echo "FAIL: Bash rule missing leading / on path: $rule" >&2; exit 1 ;;
  esac
done < <(printf '%s\n' "$OUT" | python3 -c '
import json, sys
for r in json.load(sys.stdin):
    print(r)
')

echo "PASS: permissions-expand-test"
```

---

## 4. Bug C (`release-claim.sh`) — plan's snippet is correct; here is the matching test

The plan's `release-claim.sh` is sound — `set -uo pipefail`, three-digit NNN guard, single `rm -f`. The plan declares `release-claim-test.sh` but provides no body. Concrete:

```bash
#!/bin/bash
# skills/todo/tests/release-claim-test.sh
set -euo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SELF_DIR/../../.." && pwd)"
SCRIPT="$REPO/skills/todo/scripts/release-claim.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/Todos/.todo-state"
SENTINEL="$TMP/Todos/.todo-state/id-007.claim"
: > "$SENTINEL"

# Happy path
bash "$SCRIPT" "$TMP" 007
[ ! -e "$SENTINEL" ] || { echo "FAIL: sentinel still exists"; exit 1; }

# Idempotence — second call must not error
bash "$SCRIPT" "$TMP" 007 || { echo "FAIL: not idempotent on missing sentinel"; exit 1; }

# Bad NNN — must exit non-zero, must not touch other files
EVIL="$TMP/Todos/.todo-state/id-../../etc/passwd"
mkdir -p "$(dirname "$EVIL")" || true
: > "$TMP/Todos/.todo-state/id-008.claim"
if bash "$SCRIPT" "$TMP" "../../etc/passwd" 2>/dev/null; then
  echo "FAIL: bad NNN was accepted"; exit 1
fi
[ -e "$TMP/Todos/.todo-state/id-008.claim" ] || { echo "FAIL: unrelated sentinel deleted"; exit 1; }

# Missing args
if bash "$SCRIPT" "$TMP" 2>/dev/null; then
  echo "FAIL: missing NNN was accepted"; exit 1
fi

echo "PASS: release-claim-test"
```

---

## 5. Plan §3 — the `todo-instructions.md` step-8 rewrite is **not in the plan as a snippet**

The plan says:

> Step 8 changes from `rm -f <REPO_ROOT>/Todos/.todo-state/id-<NNN>.claim` to `bash <SCRIPTS_DIR>/release-claim.sh <REPO_ROOT> <NNN>`.

But never provides the new step-8 wording. Concrete replacement (current step 8 lives at `skills/todo/scripts/assets/todo-instructions.md:54-56`):

```markdown
8. Release the claim sentinel by running this exact Bash command:
   bash ${SCRIPTS_DIR}/release-claim.sh ${REPO_ROOT} <NNN>
   (The allowlist permits exactly this prefix. If the script exits non-zero,
    log and continue; the sentinel is cosmetic-but-harmless.)
```

Note: **`${SCRIPTS_DIR}` and `${REPO_ROOT}` are pre-substituted by `render_template.py` before the worker ever sees them**, so the worker invokes a fully-resolved literal command — exactly what the `Bash(bash /${REPO_ROOT}/skills/todo/scripts/release-claim.sh:*)` rule prefix-matches.

---

## 6. Plan §4 (sha256 sidecar) — give the user the actual command

```bash
shasum -a 256 \
  /Users/matkatmusicllc/Programming/jot/skills/todo/scripts/assets/permissions.default.json \
  | awk '{print $1}' > \
  /Users/matkatmusicllc/Programming/jot/skills/todo/scripts/assets/permissions.default.json.sha256
```

Verify with `bash skills/todo/tests/permissions-default-sha256-test.sh` if such a test exists; otherwise add one — the existing `assets/permissions.default.json.sha256` and `skills/plate/scripts/assets/permissions.default.json.sha256` indicate the project already follows this idiom.

---

## 7. Plan §6 — CHANGELOG entry should explicitly call the migration concern

```markdown
## [1.1.1] — 2026-04-24

### Fixed
- `/jot:todo` and `/jot:todo-list` namespace dispatch (orchestrator case branches now normalise the `jot:` prefix). [c16737c]
- `/todo` foreground SKILL.md no longer requires `Bash(ls)` or `Bash(rm)` approvals — replaced with `Glob` and launcher-side cleanup.
- `render_template.py` no longer aborts on `${NNN}`/`${TRANSCRIPT_PATH}` in `todo-instructions.md` — switched to `<NNN>` placeholder + section-name reference.
- Worker permissions: every `Read(/Write(/Edit(` path-anchor rule now uses the
  `//${REPO_ROOT}/...` filesystem-absolute form. Bash rules now include a literal
  leading `/` before `${REPO_ROOT}`. Without these, the worker silently denied
  every read of `Todos/` and `.claude/plans/`, and rejected the
  `scan-existing-todos.sh` invocation.
- `release-claim.sh` replaces the inline `rm` in step 8 of the worker
  instructions, eliminating the fragile glob-Bash allow rule.

### Migration
- v1.1.0 installs that already wrote `${CLAUDE_PLUGIN_DATA}/todo-permissions.local.json`
  will keep their broken local file unless they delete it and re-run any
  `/jot:todo` (which will reseed). The v1.1.1 expand-time shim now auto-injects
  the four absolute-path Read/Write/Edit rules at runtime, so existing installs
  receive the fix transparently. The legacy detection warning fires once per
  invocation until the user updates their local file.
```

---

## 8. What the plan correctly nails

- **Bug B diagnosis is precise and minimal** — no scope creep into rewriting the matcher.
- **`release-claim.sh` is the right shape** — uniform with `scan-existing-todos.sh`, validates input, idempotent.
- **Defers Issue E option 2** to v1.2.0 — correct call; that is a UX redesign, not a bug fix.
- **Out-of-scope list is honest** — the `${HOME}` anchor bug in `assets/permissions.default.json:8` is real (`Read(${HOME}/.claude/projects/**)` expands without `//` and is therefore home-anchored not absolute, but Claude Code treats `~/` and bare `${HOME}` differently — separate audit).

---

## 9. Required additions before this plan ships

| § | Addition | Reason |
|---|---|---|
| Bug A | Extend `expand_permissions.py` shim to inject `Read(//…/Todos/**)` and `Read(//…/.claude/plans/**)` | Existing v1.1.0 installs won't pick up the bundled-default fix otherwise. |
| §3 | Concrete `todo-instructions.md` step-8 wording | Plan promises a behavioral change but never specifies the new instruction text. |
| §7 | Full `permissions-expand-test.sh` body | Plan's verification matrix references this test by name only. |
| §8 | Full `release-claim-test.sh` body | Same. |
| §6 | CHANGELOG migration note | Users on v1.1.0 deserve to know whether they need to re-seed. |

---

## 10. Position

**Approve with mandatory edits.** The plan's audit phase is honest about the v1.1.0 publish failure and the corrections it proposes are all directionally right. But shipping it as written produces a v1.1.1 that fixes the bundled defaults and **leaves every upgrading user broken** until they manually clear `${CLAUDE_PLUGIN_DATA}/todo-permissions.local.json`. The shim extension in §2 is the smallest change that makes the fix actually reach the user base, and the four missing snippets in §§3–8 are the difference between "plan" and "buildable plan."
