# Round 1 — Codex Analysis

## Position

`~/.claude/plans/mighty-exploring-kitten.md` identifies the two core `/todo` worker runtime failures correctly:

1. the repo-root path rules in `skills/todo/scripts/assets/permissions.default.json` are currently expanded into cwd-relative strings, and
2. the `Bash(...)` allow rule for `scan-existing-todos.sh` is currently missing the literal leading `/` that the executed command actually contains.

Those are real bugs today. However, the plan is **not fully correct as written**. It is stale in its release/versioning assumptions, and one of its proposed regression tests would fail on a correct configuration.

## What the plan gets right

### 1. Namespace dispatch was already fixed

This part is correct. `scripts/orchestrator.sh` now normalizes `/jot:<skill>` into `/<skill>` before dispatch:

```bash
case "$PROMPT" in
  /jot:*)
    PROMPT="/${PROMPT#/jot:}"
    INPUT=$(printf '%s' "$INPUT" | hide_errors jq --arg p "$PROMPT" '.prompt = $p')
    ;;
esac
```

That matches the plan's claim that bug #1 was already fixed in `c16737c`.

### 2. The foreground `SKILL.md` / pending-file cleanup fixes are already in the working tree

Current `skills/todo/SKILL.md` uses `Glob` instead of foreground `Bash ls`, and current `skills/todo/scripts/todo-launcher.sh` cleans up the pending sidecar itself:

```bash
hide_errors rm -f "$PENDING_FILE" || \
  hide_errors printf '%s todo-launcher: failed to rm pending_file=%s\n' \
    "$(date -Iseconds)" "$PENDING_FILE" >> "$LOG_FILE"
```

So the plan is right that the foreground Bash prompt problem was addressed by moving cleanup into the launcher.

### 3. The template-render crash diagnosis is correct

`common/scripts/jot/render_template.py` rejects any leftover `${IDENT}` token:

```python
leftover = re.findall(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", text)
if leftover:
    sys.stderr.write(
        f"render_template.py: unexpanded placeholders in {template_path}: "
        f"{sorted(set(leftover))}\n"
    )
    sys.exit(2)
```

The current `todo-instructions.md` has already switched `${NNN}` to `<NNN>` and removed the `${TRANSCRIPT_PATH}` placeholder usage, so the plan's root-cause analysis for bug #3 is correct.

### 4. The permission-anchor bug is real

Current `skills/todo/scripts/assets/permissions.default.json` still contains:

```json
"Read(${REPO_ROOT}/Todos/**)",
"Write(${REPO_ROOT}/Todos/**)",
"Edit(${REPO_ROOT}/Todos/**)",
"Read(${REPO_ROOT}/.claude/plans/**)",
"Bash(bash ${REPO_ROOT}/skills/todo/scripts/scan-existing-todos.sh:*)",
"Bash(rm -f ${REPO_ROOT}/Todos/.todo-state/id-*.claim)"
```

`common/scripts/jot/expand_permissions.py` does:

```python
repo_root = os.environ["REPO_ROOT"].lstrip("/")
...
.replace("${REPO_ROOT}", repo_root)
```

So with `REPO_ROOT=/Users/test/project`, the actual expansion today is:

```json
[
  "Read(Users/test/project/Todos/**)",
  "Write(Users/test/project/Todos/**)",
  "Edit(Users/test/project/Todos/**)",
  "Read(Users/test/project/.claude/plans/**)",
  "Read(~/.claude/projects/**)",
  "Bash(bash Users/test/project/skills/todo/scripts/scan-existing-todos.sh:*)",
  "Bash(rm -f Users/test/project/Todos/.todo-state/id-*.claim)",
  "Write(//Users/test/project/Todos/**)",
  "Edit(//Users/test/project/Todos/**)"
]
```

That is the decisive evidence. The `Read(...)` rules are broken exactly the way the plan says, and the `scan-existing-todos.sh` Bash rule is broken exactly the way the plan says.

## Where the plan is wrong or incomplete

### 1. Do not ship this as `v1.1.1`

This is the biggest plan error.

The repo already has:

- `.claude-plugin/plugin.json` at `version: "1.1.1"`
- `.claude-plugin/marketplace.json` at `version: "1.1.1"`
- local tag `v1.1.1` at commit `b3bd67e`

And `b3bd67e` only bumped version metadata; it did **not** include the worker permission fixes. So the plan's release section is stale and dangerous.

Correct release guidance:

- If `v1.1.1` was already pushed or published anywhere, the next release must be `v1.1.2`.
- Only if `v1.1.1` is definitely local-only and unpublished should you delete/move that tag and reuse `1.1.1`.

Also, if you bump the version again, you must update **both** metadata files, not just `.claude-plugin/plugin.json`:

```json
// .claude-plugin/plugin.json
{ "version": "1.1.2" }

// .claude-plugin/marketplace.json
{
  "metadata": { "version": "1.1.2" },
  "plugins": [{ "version": "1.1.2" }]
}
```

### 2. The proposed `permissions-expand-test.sh` assertion is too broad

The plan says the test should assert:

> Every `Read(`/`Write(`/`Edit(` entry in the output contains `//` directly after the paren.

That is wrong. `Read(~/.claude/projects/**)` is already correct and should remain home-anchored, not `//`-anchored.

So the test must assert only the repo-root-derived rules, not every read/write/edit rule indiscriminately.

A correct test shape is:

```bash
#!/bin/bash
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT=$(
  CWD=/x \
  HOME=/Users/test \
  REPO_ROOT=/Users/test/project \
  python3 "$REPO/common/scripts/jot/expand_permissions.py" \
    "$REPO/skills/todo/scripts/assets/permissions.default.json"
)

for needle in \
  'Read(//Users/test/project/Todos/**)' \
  'Write(//Users/test/project/Todos/**)' \
  'Edit(//Users/test/project/Todos/**)' \
  'Read(//Users/test/project/.claude/plans/**)' \
  'Read(~/.claude/projects/**)' \
  'Bash(bash /Users/test/project/skills/todo/scripts/scan-existing-todos.sh:*)' \
  'Bash(bash /Users/test/project/skills/todo/scripts/release-claim.sh:*)'
do
  printf '%s\n' "$OUT" | grep -qF "$needle" || {
    echo "FAIL: missing expanded permission: $needle" >&2
    exit 1
  }
done

leftover=$(printf '%s' "$OUT" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*\}' || true)
[ -z "$leftover" ] || {
  echo "FAIL: unexpanded placeholder(s): $leftover" >&2
  exit 1
}

echo "PASS: permissions expand correctly"
```

### 3. The `rm` rule discussion is directionally right, but the helper-script approach is the part worth keeping

The plan argues for adding `:*` to the `rm` rule. That is not the main issue. The real issue is that this rule currently expands to a broken absolute-path prefix, and it also depends on wildcard matching inside a shell command permission string:

```json
"Bash(rm -f ${REPO_ROOT}/Todos/.todo-state/id-*.claim)"
```

Even after fixing the leading slash, that is a brittle permission rule. The safer correction is the helper-script design the plan proposes.

I would keep that change and drop the direct `rm` rule entirely:

```json
{
  "permissions": {
    "allow": [
      "Read(//${REPO_ROOT}/Todos/**)",
      "Write(//${REPO_ROOT}/Todos/**)",
      "Edit(//${REPO_ROOT}/Todos/**)",
      "Read(//${REPO_ROOT}/.claude/plans/**)",
      "Read(~/.claude/projects/**)",
      "Bash(bash /${REPO_ROOT}/skills/todo/scripts/scan-existing-todos.sh:*)",
      "Bash(bash /${REPO_ROOT}/skills/todo/scripts/release-claim.sh:*)"
    ]
  }
}
```

and:

```bash
#!/bin/bash
# release-claim.sh — delete the claim sentinel for a given NNN.
set -euo pipefail

REPO_ROOT="${1:?repo_root required}"
NNN="${2:?NNN required}"

case "$NNN" in
  [0-9][0-9][0-9]) ;;
  *)
    echo "release-claim.sh: bad NNN '$NNN'" >&2
    exit 2
    ;;
esac

rm -f "$REPO_ROOT/Todos/.todo-state/id-$NNN.claim"
```

Then update step 8 in `todo-instructions.md` to the explicit helper call:

```md
8. Delete the claim sentinel via Bash:
   bash ${SCRIPTS_DIR}/release-claim.sh ${REPO_ROOT} <NNN>
   (If the sentinel deletion fails for any reason, log and continue; the sentinel is cosmetic-but-harmless.)
```

## Recommended corrected plan

1. Keep the already-made foreground fixes in `skills/todo/SKILL.md`, `skills/todo/scripts/todo-launcher.sh`, and `skills/todo/scripts/assets/todo-instructions.md`.
2. Fix `skills/todo/scripts/assets/permissions.default.json` exactly as shown above: `//` for repo-root path rules, literal `/` inside `Bash(bash /${REPO_ROOT}/...)`, and replace the inline `rm` permission with `release-claim.sh`.
3. Add `skills/todo/scripts/release-claim.sh`.
4. Add `skills/todo/tests/permissions-expand-test.sh` with precise assertions, not the over-broad "`every Read` starts with `//`" assertion.
5. Add `skills/todo/tests/release-claim-test.sh`.
6. Recompute `skills/todo/scripts/assets/permissions.default.json.sha256`.
7. Add a changelog entry for the runtime fixes.
8. If `v1.1.1` is already public, release this as `v1.1.2`; update both `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.

## Bottom line

The plan's diagnosis of the worker permission failures is correct, and its proposed permission-file shape is mostly right. But it should **not** be executed verbatim:

- the release/version steps are stale,
- the proposed permission-expansion test is partly wrong,
- and the helper-script variant is the robust fix for claim cleanup.

If those corrections are applied, the plan becomes sound.
