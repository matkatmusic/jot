# Analysis of `mighty-exploring-kitten.md`

The plan `mighty-exploring-kitten.md` aims to fix critical runtime failures in the `/todo` skills of the `jot` plugin. My analysis covers the correctness of identified issues, missing code snippets, and overall effectiveness.

## Identified Issues & Proposed Fixes

### 1. Permission Path Anchoring (Bug A)
The plan correctly identifies that `permissions.default.json` uses `${REPO_ROOT}/Todos/**`, which expands to a cwd-relative path (e.g., `Users/test/project/Todos/**`) because `expand_permissions.py` strips the leading slash.
*   **Correctness:** High. This is a known idiom in the project (as seen in `jot` and `plate` assets) that requires `//` for filesystem-absolute paths.
*   **Correction:** While the plan proposes adding `//`, it must ensure the `expand_permissions.py` shim also covers these rules to support existing installs that won't pick up the new default file.

### 2. Bash Rule Leading Slash (Bug B)
The plan identifies that `Bash()` rules lack the leading `/` required for a prefix match against the actual command executed (e.g., `bash /Users/...`).
*   **Correctness:** High. Prefix matching in `Bash()` is literal.
*   **Snippet Provided:**
    ```json
    "Bash(bash /${REPO_ROOT}/skills/todo/scripts/scan-existing-todos.sh:*)",
    "Bash(rm -f /${REPO_ROOT}/Todos/.todo-state/id-*.claim:*)"
    ```

### 3. `release-claim.sh` Helper (Bug C)
The plan proposes replacing a brittle `rm` Bash rule with a dedicated helper script.
*   **Correctness:** High. This aligns with the project's preference for discrete scripts over complex inline Bash rules.
*   **Snippet Provided:**
    ```bash
    #!/bin/bash
    # release-claim.sh — delete the claim sentinel for a given NNN.
    set -uo pipefail
    REPO_ROOT="${1:?repo_root required}"
    NNN="${2:?NNN required}"
    case "$NNN" in
      [0-9][0-9][0-9]) ;;
      *) echo "release-claim: bad NNN '$NNN'" >&2; exit 2 ;;
    esac
    rm -f "$REPO_ROOT/Todos/.todo-state/id-$NNN.claim"
    ```

## Missing Code Snippets

The following sections indicate changes but lack concrete snippets:

### 1. `todo-instructions.md` Step 8 Rewrite
The plan mentions changing step 8 but doesn't provide the text.
*   **Proposed Snippet:**
    ```markdown
    8. Release the claim sentinel by running this exact Bash command:
       bash ${SCRIPTS_DIR}/release-claim.sh ${REPO_ROOT} <NNN>
       (The allowlist permits exactly this prefix. If the script exits non-zero,
        log and continue; the sentinel is cosmetic-but-harmless.)
    ```

### 2. Regression Test: `permissions-expand-test.sh`
The plan mentions this test but provides no implementation.
*   **Proposed Snippet:**
    ```bash
    #!/bin/bash
    # skills/todo/tests/permissions-expand-test.sh
    set -euo pipefail
    REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
    EXPAND="$REPO/common/scripts/jot/expand_permissions.py"
    PERMS="$REPO/skills/todo/scripts/assets/permissions.default.json"

    OUT=$(CWD=/x HOME=/Users/test REPO_ROOT=/Users/test/project python3 "$EXPAND" "$PERMS")

    # Assert filesystem-absolute paths
    printf '%s' "$OUT" | grep -qF '"Read(//Users/test/project/Todos/**)"' || exit 1
    # Assert leading slash in Bash rules
    printf '%s' "$OUT" | grep -qF '"Bash(bash /Users/test/project/skills/todo/scripts/scan-existing-todos.sh:*)"' || exit 1
    echo "PASS"
    ```

### 3. Regression Test: `release-claim-test.sh`
*   **Proposed Snippet:**
    ```bash
    #!/bin/bash
    # skills/todo/tests/release-claim-test.sh
    set -euo pipefail
    SCRIPT="./skills/todo/scripts/release-claim.sh"
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    mkdir -p "$TMP/Todos/.todo-state"
    touch "$TMP/Todos/.todo-state/id-001.claim"
    bash "$SCRIPT" "$TMP" 001
    [ ! -f "$TMP/Todos/.todo-state/id-001.claim" ] || exit 1
    echo "PASS"
    ```

## Verdict & Position
**Approve with Mandatory Additions.** The plan is technically sound and addresses the root causes of the reported failures. However, it is incomplete without the concrete instruction text and test scaffolds. Furthermore, a migration strategy (extending the `expand_permissions.py` shim) is required to ensure the fix reaches existing users.
