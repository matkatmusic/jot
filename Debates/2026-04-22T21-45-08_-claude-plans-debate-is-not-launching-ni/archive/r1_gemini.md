# Gemini Independent Analysis: Debate Tmux Session Isolation Plan

## Position
The proposed plan to isolate each `/debate` invocation into a distinct tmux session (`debate-<N>`) is **accurate, correct, and highly recommended**. It elegantly addresses the core symptom (silent failures on concurrent runs) and replaces the fundamentally flawed shared-session approach.

## Analysis & Rationale

The current architecture reuses a single `debate` tmux session and attaches new windows to it. This approach suffers from two critical flaws:
1. **Early Return on `spawn_terminal_if_needed`:** If the user already has the `debate` session attached (or existing in the background), the hook logic thinks the user is "already viewing" it and fails to spawn a new visible terminal window for the second invocation.
2. **Side-effect Collisions:** Concurrent writes to the shared tmux session cause race conditions with pane creation, resulting in missing `orchestrator.log` files and deadlocked debates.

The plan correctly identifies these issues and shifts from a "Shared Session, Unique Window" model to a "Unique Session, Single Window" model. 

### Pros
- **Strong Isolation:** By guaranteeing a completely fresh tmux session per invocation, we ensure that tmux pane commands never intersect or collide.
- **Reliable Terminal Spawning:** Because `spawn_terminal_if_needed` targets a brand-new session with 0 attached clients, it is guaranteed to spawn the visible Terminal application every single time a debate is invoked.
- **Clean Lifecycle Management:** Scoping the cleanup trap to `tmux_kill_session` entirely removes the session upon completion. It ensures no orphaned "empty" sessions remain, which is much cleaner than killing a specific window.

### Risks and Trade-offs

**1. Race Condition on Session Assignment**
The plan proposes the following helper:
```bash
debate_next_session_name() {
  local n=1
  while hide_errors tmux has-session -t "debate-$n"; do
    n=$((n + 1))
  done
  printf 'debate-%d\n' "$n"
}
```
*Risk:* If two `/debate` hooks are fired at the exact same millisecond, they could both evaluate `tmux has-session` before either calls `tmux new-session`. 
*Mitigation:* The plan correctly notes this risk is acceptable. If `tmux_ensure_session` attempts to create a session that already exists, it will fail loudly, and the `ERR` trap will bubble this up to the user. Given normal usage patterns (typing commands manually), exact millisecond concurrency is improbable. No further complexity (e.g., lockfiles) is warranted here.

**2. Positional Argument Shifting in Orchestrator**
The plan proposes shifting positional arguments in `debate-tmux-orchestrator.sh`:
```bash
DEBATE_DIR="$1"
SESSION="$2"
WINDOW_NAME="$3"
SETTINGS_FILE="$4"
CWD="$5"
REPO_ROOT="$6"
PLUGIN_ROOT="$7"
```
*Risk:* If any other scripts or tests call `debate-tmux-orchestrator.sh` and aren't updated, they will break. 
*Evidence & Mitigation:* The plan explicitly audits other callers. It notes that `skills/debate/scripts/debate.sh` must be updated to pass `$session`. It also notes that `tests/test.sh` might be out of date, but explicitly marks it as out-of-scope for this fix because it's a pre-extraction harness. This boundary is pragmatic and correct.

**3. Cleanup Trap Context**
The plan proposes replacing `tmux_kill_window` with:
```bash
hide_errors tmux_kill_session "$SESSION"
```
*Evidence:* I have verified via code search that `tmux_kill_session` is natively implemented within `common/scripts/tmux.sh`. Therefore, this function call will successfully clean up the entire `debate-<N>` session without erroring out.

## Conclusion
The architectural shift to ephemeral, isolated sessions is robust. The code snippets provided in the plan directly implement this shift with minimal collateral changes. Proceed with the implementation as specified.