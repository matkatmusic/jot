# debate skill

Structured four-way AI debate: Claude + Gemini + Codex independently analyze a topic (R1), cross-critique each other's responses (R2), then a fourth Claude invocation synthesizes the debate.

Triggered by the user typing `/debate <topic>` in Claude Code. `scripts/orchestrator.sh` (plugin-level dispatcher) routes the hook to `skills/debate/scripts/debate-orchestrator.sh`.

## Flow

1. **Setup (hook-side, `debate.sh:debate_main`)** — parses hook JSON, creates `$REPO_ROOT/Debates/<ts>_<slug>/`, writes `topic.md` + `agents.txt` + `context.md` + per-agent `r1_instructions_*.txt`, seeds a Claude `settings.json` with write permissions for `Debates/**`, forks `debate-tmux-orchestrator.sh` as a background daemon, emits a progress message, exits.
2. **R1 (daemon)** — spawns 3 fresh panes (one per agent), launches the agent TUI in each, sends `read <r1_instructions_<agent>.txt> and perform them`, polls for `r1_<agent>.md` files.
3. **R2 (daemon)** — kills R1 panes; builds per-agent R2 instructions referencing the *other* agents' R1 outputs; spawns 3 fresh panes; same launch/send-prompt pattern; polls for `r2_<agent>.md`.
4. **Synthesis (daemon)** — kills R2 panes; builds `synthesis_instructions.txt`; spawns one Claude pane; polls for `synthesis.md`.

End state: tmux session `debate` with keepalive pane + synthesis pane. User reads `synthesis.md` or attaches with `tmux attach -t debate`.

## Permission flags per agent

Each agent is launched with flags that let it write output files (`r<N>_<agent>.md`, `synthesis.md`) without interactive approval prompts — the daemon is headless with respect to the agents' TUIs, so any approval dialog would hang the pane forever.

| Agent  | Flags | Rationale |
|--------|-------|-----------|
| gemini | `--allowed-tools 'read_file,write_file'` | Bypasses the approval dialog for exactly the two file-system tools the debate flow needs: `read_file` (topic, context, other agents' R1 outputs) and `write_file` (`r1_gemini.md`, `r2_gemini.md`). Any other tool use (shell, edit, glob) still prompts — and since no one is watching the pane, an unexpected tool will hit the stage timeout and surface as a visible failure. See [gemini configuration](https://geminicli.com/docs/reference/configuration/#command-line-arguments) and [file-system tools](https://geminicli.com/docs/reference/tools/#file-system). |
| codex  | `-a never --add-dir '$DEBATE_DIR'` | `-a never` suppresses approval prompts. `--add-dir` grants write access to the specific debate directory. Per codex docs: *"When you need to grant Codex write access to more directories, prefer `--add-dir` rather than forcing `--sandbox danger-full-access`."* |
| claude | `--settings '$SETTINGS_FILE' --add-dir '$CWD' --add-dir '$REPO_ROOT'` | `$SETTINGS_FILE` is a per-invocation temp `settings.json` built by `debate_build_claude_cmd` from `scripts/assets/permissions.default.json`, granting `Write(Debates/**)` and `Edit(Debates/**)`. `--add-dir` puts both the launcher cwd and the repo root in Claude's workspace. |

## File layout

```
skills/debate/
├── README.md                          # this file
├── SKILL.md                           # LLM-facing trigger ("do nothing, let the hook run")
├── prompts/
│   └── r1.template.md                 # consumed by debate-build-prompts.sh
├── scripts/
│   ├── assets/
│   │   ├── permissions.default.json         # Claude permission seed
│   │   └── permissions.default.json.sha256
│   ├── debate-orchestrator.sh         # hook entrypoint (sources debate.sh, calls debate_main)
│   ├── debate.sh                      # debate_main: setup + fork daemon
│   ├── debate-tmux-orchestrator.sh    # daemon: R1 → R2 → synthesis loop
│   └── debate-build-prompts.sh        # renders r1/r2/synthesis instruction files
└── tests/
    └── test.sh                        # hand-driven spec (pre-dates the skill extraction)
```

## Artifacts produced per debate

Under `$REPO_ROOT/Debates/<YYYY-MM-DDTHH-MM-SS>_<slug>/`:

- `topic.md`, `context.md`, `agents.txt` — inputs
- `r1_instructions_<agent>.txt`, `r1_<agent>.md` — R1 per agent
- `r2_instructions_<agent>.txt`, `r2_<agent>.md` — R2 per agent
- `synthesis_instructions.txt`, `synthesis.md` — final deliverable
- `orchestrator.log` — daemon stdout/stderr (stage progress, timeouts, agent readiness)
