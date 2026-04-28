# Migrate `/jot:debate` Gemini tool restrictions to Policy Engine

## Context

Gemini CLI's `--allowed-tools` flag and `tools.allowed` settings.json key are deprecated; the supported replacement is the Policy Engine, which reads `.toml` rule files from `~/.gemini/policies/`. The `/jot:debate` skill currently restricts each Gemini agent's tool surface via `--allowed-tools` on the command line. We need to express the same allow/deny intent via Policy Engine rules so debate keeps working when the deprecated flag is removed.

## Scope of change

### Code paths using `--allowed-tools` today (verified)
- `skills/debate/scripts/debate-tmux-orchestrator.sh:106-108` — `agent_launch_cmd()` for the gemini agent emits:
  ```
  gemini --allowed-tools 'read_file,write_file,run_shell_command(ls)' --model "$m"
  gemini --allowed-tools 'read_file,write_file,run_shell_command(ls)'
  ```
- `skills/debate/tests/test.sh:24` — test-harness `agent_launch_cmd()` emits:
  ```
  gemini --allowed-tools 'read_file,write_file'
  ```
- `skills/debate/README.md:22-23` — documents the `--allowed-tools` form for users.

### Settings files to migrate
- **None.** No `tools.allowed` (or `tools: { allowed: ... }`) entry exists anywhere in the repo. Only `permissions.default.json` exists, and that is a Claude permissions template, not Gemini config.

### Comment-only references (no functional change)
- `skills/debate/tests/agent-ls-permission-test.sh:5,26` — comments referencing the flag. Update wording.

## Policy Engine facts that drive the design

- Rules live in `~/.gemini/policies/*.toml` (User tier).
- **There is no CLI flag, env var, or per-invocation way to point Gemini at an alternate policy directory.** `--admin-policy` is admin-tier only.
- Rule shape:
  ```toml
  [[rule]]
  toolName     = "read_file"
  decision     = "allow"
  priority     = 500
  ```
  Optional fields: `argsPattern` (regex on JSON args), `commandPrefix` (shell prefix sugar), `mcpName`, `subagent`, `toolAnnotations`.
- Higher priority wins; tiers add a base offset (User = 4, Admin = 5).
- The recommended "allow-list, deny everything else" idiom is several `decision = "allow"` rules at priority 500 plus a final `toolName = "*"` `decision = "deny"` rule at priority 100.
- `deny` with no `argsPattern` removes the tool from the model's context entirely (cheaper and safer than just refusing).

## Design tension — per-invocation vs. global

`--allowed-tools` today applies **only to that one debate run**. The Policy Engine applies **to every gemini invocation on the machine**. A naive migration would silently restrict the user's unrelated Gemini sessions.

Two viable approaches:

### Option A — Global, debate-aware policy file
Install one file: `~/.gemini/policies/jot-debate.toml`. Use the `subagent` field (or, if not applicable, a `toolAnnotations` / `argsPattern` discriminator) to scope rules. **Problem:** the debate orchestrator does not invoke gemini as a subagent — it shells out to `gemini` directly inside a tmux pane. The `subagent` field will not match. There is no Policy Engine field that says "only when invoked from this working directory" or "only when this env var is set." So a global policy here would effectively become the user's machine-wide gemini policy — invasive.

### Option B — Per-session `HOME` (or `GEMINI_HOME` if supported) override
Wrap the gemini launch with `HOME=<scratch-dir> gemini …`, where `<scratch-dir>` contains a synthesized `.gemini/policies/jot-debate.toml`. Auth state lives in `~/.gemini/oauth_creds.json` (or similar) — would need to be symlinked from the real `$HOME` into the scratch dir so login is preserved. Adds complexity but preserves today's per-invocation scope.

### Option C — Drop tool restrictions entirely
Stop trying to sandbox Gemini's tool surface. Document the change. Simplest, but loses the safety property the current code is trying to provide (debate agents shouldn't run arbitrary shell, only `ls`).

**Recommendation pending user input — see "Open question" below.**

## Proposed implementation (assuming Option B once confirmed)

1. **Add helper `gemini_policy_dir()`** to `skills/debate/scripts/debate-tmux-orchestrator.sh`:
   - Create `$DEBATE_DIR/.gemini-home/.gemini/policies/jot-debate.toml` per debate run.
   - Symlink `$HOME/.gemini/oauth_creds.json` (and any other auth artifacts gemini cli writes) into the scratch `.gemini/`.
   - Write the TOML allow-list:
     ```toml
     [[rule]]
     toolName = "read_file"
     decision = "allow"
     priority = 500

     [[rule]]
     toolName = "write_file"
     decision = "allow"
     priority = 500

     [[rule]]
     toolName       = "run_shell_command"
     commandPrefix  = "ls"
     decision       = "allow"
     priority       = 500

     [[rule]]
     toolName = "*"
     decision = "deny"
     priority = 100
     ```

2. **Edit `agent_launch_cmd()` (`debate-tmux-orchestrator.sh:96-110`):**
   - Drop `--allowed-tools '…'`.
   - Prefix the emitted command with `HOME='$POLICY_HOME' ` so the scratch policies dir takes effect. Keep `--model "$m"` and the bare gemini form.

3. **Edit `tests/test.sh:20-24`:**
   - Same shape as production: prefix with `HOME=…`, drop `--allowed-tools`.
   - Add a new test fixture under `tests/` that synthesizes the same policy structure used by production.

4. **Update `tests/agent-ls-permission-test.sh:5,26`** — replace `--allowed-tools` references with Policy Engine wording.

5. **Update `skills/debate/README.md:22-23`** — replace the `--allowed-tools` row with a description of the Policy Engine TOML the orchestrator generates, and link to https://geminicli.com/docs/core/policy-engine/.

## Critical files to modify

- `skills/debate/scripts/debate-tmux-orchestrator.sh` (functional change + new helper)
- `skills/debate/tests/test.sh` (mirror production change)
- `skills/debate/tests/agent-ls-permission-test.sh` (comments only)
- `skills/debate/README.md` (docs)

## Verification (must fail if migration is broken)

1. **Policy file generation unit check.** Add `tests/policy-engine-toml-test.sh`: invoke the new `gemini_policy_dir()` helper, then `grep -c 'decision = "allow"'` the produced TOML and assert exactly 3 allow rules + 1 deny rule. Fails if helper drifts.
2. **Allowed-call e2e.** Run a real `/jot:debate` round on a trivial topic. Tail the gemini agent's tmux pane log; assert it successfully called `read_file` and `write_file` (R1 file shows up on disk, non-empty). Fails if the allow rules don't match.
3. **Denied-call e2e.** During the same debate run, inspect transcript for any `run_shell_command` other than `ls` — should see explicit "denied by policy" messaging from gemini. Fails if the deny-all rule is missing or shadowed.
4. **No leakage.** After the debate completes, run `gemini --version` (or any plain gemini invocation) outside the debate scratch home and confirm it does NOT inherit the debate policy (it should still see the user's normal policies, if any). Fails if Option B's HOME scoping isn't actually scoping.
5. **Auth preserved.** Confirm gemini does not re-prompt for login during the debate (i.e. the symlinked oauth creds work). Fails if symlink list is incomplete.

## Open question for user

Picking between Option A / B / C materially changes the implementation. See AskUserQuestion next.
