# Implementation Milestones

This doc is an execution plan. Every milestone has prereqs, deliverables, verification steps, and exit criteria concrete enough for an implementing agent to complete without further clarification. All section references (§N) point to `architecture.md` in the same directory.

## Context for implementing agents

Current state: per-invocation shell scripts launch tmux agents (parallel Claude / Gemini / Codex instances) from Claude Code hooks. Every invocation pays shell + process-startup cost, which interrupts the conversation flow.

Target state: a long-lived Go daemon (`jotd`) serving requests over a Unix socket from a tiny Go messenger (`jot`). Hooks call `jot` and return in under 30 ms. See architecture.md §1.

## Milestone 0 — Discovery

**Objective.** Enumerate every op the new system must support by inventorying the existing shell scripts.

**Deliverables.**
- `docs/design/ops-inventory.md` listing, for each existing shell script that a hook currently invokes:
  - script path
  - which hook(s) invoke it
  - what mode it maps to (`async`, `status`, or `reply` per §6)
  - payload fields it needs
  - any side effects or external commands it runs (especially tmux invocations)

**Verification.** Every existing hook entry in the project's Claude Code config has a corresponding row in the inventory.

**Exit criteria.** The inventory is complete and reviewed by a human before milestone 1 begins.

---

## Milestone 1 — Module skeleton and shared types

**Objective.** Stand up the Go module, directory layout, and the shared proto package. No networking yet.

**Prereqs.** Milestone 0 complete.

**Deliverables.**

```
jot/
├── go.mod                           module github.com/<user>/jot
├── cmd/
│   ├── jot/main.go                  empty main, `package main; func main() {}`
│   └── jotd/main.go                 empty main, `package main; func main() {}`
├── internal/
│   ├── proto/
│   │   ├── proto.go                 types from §10.1
│   │   └── proto_test.go            round-trip marshal/unmarshal tests
│   └── paths/
│       ├── paths.go                 Socket(), PIDFile(), Log(), Spool(), StateDir()
│       └── paths_test.go            tests for both Linux and macOS env scenarios
└── Makefile                         targets: build, test, vet, clean
```

**Implementation notes.**
- `internal/paths` must honor the resolution rules in §4. Use `os.Getenv("XDG_RUNTIME_DIR")` for Linux, fall back to `/tmp/jot-<UID>.sock`. On macOS, always `/tmp/jot-<UID>.sock`. Detect macOS with `runtime.GOOS == "darwin"`.
- `proto.Version = 1` as a compile-time constant.
- Tests must verify that a Request round-trips through `json.Marshal` → `json.Unmarshal` without loss.

**Verification.** `make build test vet` exits 0.

**Exit criteria.** All files compile. All tests green. `./bin/jot` and `./bin/jotd` exist as zero-behavior binaries.

---

## Milestone 2 — Minimal jotd + async mode + first op

**Objective.** Prove end-to-end: hook → `jot --async` → running `jotd` → tmux pane appears. No lazy launch, no spool, no other modes.

**Prereqs.** Milestone 1 complete, `tmux` installed on test machine.

**Deliverables.**

1. **`cmd/jotd/main.go`.** Full daemon per §10.3, minus `drainSpool()` (stub it out). Must:
   - Acquire exclusive `flock` on PID file; exit 0 if held.
   - Remove stale socket, listen, `chmod 0600`.
   - Handle SIGTERM/SIGINT: close listener, unlink socket, exit 0.
   - `log.SetOutput` to a file at `paths.Log()`.
   - Accept loop, one goroutine per connection, 1-second read deadline on each connection.

2. **`cmd/jot/main.go`.** Async-only messenger. Must:
   - Parse CLI: `jot --async <op> [--payload <json>]` and build `proto.Request`.
   - Dial socket with 50 ms timeout. No lazy launch yet; on failure, print error to stderr and exit 2.
   - Write request line, call `CloseWrite()`, exit 0. Never read from the connection.
   - Total walltime target: ≤10 ms once `jotd` is running.

3. **`internal/ops/tmuxagent.go`.** First concrete op, `op: "spawn-tmux-agent"`. Payload:
   ```json
   {"session":"claude-parallel","window":"gemini","cmd":"gemini chat"}
   ```
   Implementation uses `exec.Command("tmux", "new-window", ...)` or `split-window` depending on payload. Returns `proto.Response{OK: true}` on success.

4. **`internal/ops/dispatch.go`.** `Dispatch(req proto.Request) proto.Response` maps `req.Op` to handler functions. Unknown op returns `{OK: false, Err: "unknown op: <name>"}`.

5. **`scripts/smoke-test.sh`.** Runs `jotd &`, waits 50 ms, runs `jot --async spawn-tmux-agent --payload '{...}'`, verifies with `tmux list-windows` that the window appears, cleans up.

**Implementation notes.**
- PID lock: use `golang.org/x/sys/unix.Flock` with `LOCK_EX|LOCK_NB`.
- Keep the PID file open for the process lifetime; flock releases on close.
- `spawnHelper()` is **not** implemented this milestone. Missing `jotd` is a user error that prints to stderr.
- Log line format: `2006-01-02T15:04:05.000Z LEVEL message`. Use `log.New` with `LstdFlags|LUTC|Lmicroseconds`.

**Verification.**

```sh
$ ./bin/jotd &
$ time ./bin/jot --async spawn-tmux-agent --payload '{"session":"t","window":"w","cmd":"sleep 5"}'
real    0m0.008s
$ tmux list-windows -t t
0: w* ...
$ kill %1 && wait
```

**Exit criteria.**
- Smoke test passes on both macOS and Linux.
- `time jot --async ...` reports under 10 ms real time.
- Killing `jotd` via SIGTERM leaves no stale socket, no stale PID file.

---

## Milestone 3 — Lazy launch and spool fallback

**Objective.** Messenger always exits 0, even when `jotd` is absent, crashed, or hung. Work is never lost.

**Prereqs.** Milestone 2 complete.

**Deliverables.**

1. **Lazy launch in `cmd/jot/main.go`.** Implement `dialWithLazyStart()` per §10.2. On connect failure:
   - `exec.Command("jotd")` with `SysProcAttr{Setsid: true}` and stdio detached.
   - Retry dial with 10 ms backoff for up to 150 ms total.
   - Still failing → fall through to spool.

2. **Spool writer in `cmd/jot/main.go`.** `spoolAppend(line []byte)`:
   - Open `paths.Spool()` with `O_APPEND|O_CREAT|O_WRONLY`, mode 0600.
   - For writes ≤ 4096 bytes (PIPE_BUF): single `Write` is atomic, no lock needed.
   - For writes > 4096 bytes: acquire `flock(LOCK_EX)`, write, release.
   - Always exit 0 after spooling.

3. **Spool drainer in `cmd/jotd/main.go`.** Replace the stub `drainSpool()`:
   - If `paths.Spool()` does not exist, return.
   - `rename` to `paths.Spool() + ".draining"` (atomic, isolates from concurrent writers).
   - Read line by line, unmarshal, dispatch only `ModeAsync` entries. Log and skip `status`/`reply` entries (see §8.2).
   - On completion, unlink the `.draining` file.
   - Runs once on startup, before `ln.Accept()`.

4. **Timeout in `cmd/jot/main.go`.** `conn.SetDeadline(time.Now().Add(200 * time.Millisecond))` immediately after dial succeeds. Any I/O error → spool fallback.

5. **Test script `scripts/test-resilience.sh`.** Exercises three scenarios:
   - a) `jotd` not running → `jot` launches it → message processed.
   - b) `jotd` SIGKILLed → `jot` spools → next `jotd` start drains spool → message processed.
   - c) `jotd` hung (simulated with SIGSTOP) → `jot` times out at 200 ms → spools → `SIGCONT` + restart → drain → processed.

**Implementation notes.**
- When forking `jotd`, **do not** `Wait()` on it. The messenger must return without reaping the child. `Setsid: true` detaches it from the messenger's process group so Claude Code doesn't keep a handle on it either.
- Drain before accept, otherwise a new `jot` call racing the drainer could double-process a message.
- Spool file format is identical to wire format: one JSON request per line. This means a future tool can replay spool files for debugging.

**Verification.** `scripts/test-resilience.sh` passes all three scenarios. `time jot --async ...` with `jotd` absent reports under 250 ms (one dial + launch + 150 ms retry + spool write, worst case).

**Exit criteria.**
- No scenario causes `jot` to exit non-zero.
- No scenario loses a message.
- `jotd` self-launches correctly from a bare shell environment (verify with `env -i ./bin/jot --async ...`).

---

## Milestone 4 — Status and reply modes

**Objective.** Support the two remaining modes so hooks can take pass/fail branches and surface text to the user.

**Prereqs.** Milestone 3 complete.

**Deliverables.**

1. **Extend `cmd/jot/main.go`.** Add `--status` and `--reply` flag handlers per §10.2. After `CloseWrite()`:
   - `bufio.NewReader(conn).ReadBytes('\n')` for the response.
   - Unmarshal into `proto.Response`.
   - For `--reply`: `io.WriteString(os.Stdout, resp.Text)`.
   - Exit 0 if `resp.OK`, exit 1 otherwise (with `resp.Err` to stderr).

2. **Two new ops.**
   - `op: "list-agents"` (reply mode). Returns formatted text listing current tmux windows in the configured session.
   - `op: "kill-agent"` (status mode). Payload `{"session":"...","window":"..."}`. Runs `tmux kill-window`, returns `{OK: true}` on success or `{OK: false, Err: "..."}` on failure.

3. **Spool drainer update.** Already skips `status`/`reply` modes per M3. Log at WARN level when a non-async entry is found in the spool; include the request for post-mortem.

4. **Integration tests `test/integration/modes_test.go`.** Full round-trips for each mode with a real `jotd` spawned for the test.

**Implementation notes.**
- `--reply` output goes to stdout unmodified; Claude Code surfaces that to the user verbatim. The helper is responsible for trailing newlines.
- A `reply` op whose response exceeds what fits in a single 64 KiB frame must chunk — defer this to a future milestone, add a `TODO` and a size check that returns an error.

**Verification.**

```sh
$ jot --reply list-agents
session "parallel":
  - claude (window 0, PID 12345)
  - gemini (window 1, PID 12346)
$ jot --status kill-agent --payload '{"session":"parallel","window":"1"}'
$ echo $?
0
```

**Exit criteria.**
- All three modes work end-to-end.
- Integration tests green on macOS and Linux.
- `list-agents` output renders readably when surfaced by Claude Code.

---

## Milestone 5 — Migrate existing shell scripts

**Objective.** Replace every per-invocation shell script with a `jot` op. Point hooks at the new binary. Delete the old scripts.

**Prereqs.** Milestone 4 complete. `docs/design/ops-inventory.md` from Milestone 0 is the authoritative task list.

**Deliverables.**

1. **One op implementation per inventory row.** Each op lives in `internal/ops/<opname>.go` with a handler function and unit tests.
2. **Hook config migration.** Update the project's Claude Code hook configuration to invoke `jot` with the appropriate `--async`/`--status`/`--reply` flag and op name.
3. **Deprecation PR.** Remove old shell scripts in a single commit, referencing the inventory rows they correspond to.
4. **Rollback script `scripts/rollback.sh`.** Restores old shell scripts from git history and points hooks back at them. Exists only during the migration window, deleted at the end.

**Implementation notes.**
- Migrate ops one at a time. Each migration commit should:
  - Add the Go op + tests.
  - Switch the hook for that op to `jot`.
  - Mark the inventory row as migrated.
  - Leave the old shell script in place until all consumers are switched.
- After all rows are migrated, a final commit deletes the old scripts.

**Verification.** For each migrated op, the behavior observed by the user (time to complete, side effects, output visible in conversation) must be equivalent or better than the shell-script version. Benchmark with `hyperfine` where possible.

**Exit criteria.**
- `docs/design/ops-inventory.md` has every row marked migrated.
- No shell script in the repo is still referenced by any hook.
- `scripts/rollback.sh` deleted.
- A tagged release `v1.0.0` exists.

---

## Milestone 6 — OS-level supervision (optional polish)

**Objective.** Survive reboots and crashes without requiring a hook invocation to bring `jotd` back.

**Prereqs.** Milestone 5 complete and stable for at least a week of real use.

**Deliverables.**

1. **`dist/launchd/com.<user>.jotd.plist`** for macOS. KeepAlive=true, RunAtLoad=true, stdio redirected to log file.
2. **`dist/systemd/jotd.service`** for Linux user units. `Restart=on-failure`, `Type=simple`.
3. **Install targets in Makefile:** `install-launchd` (macOS) and `install-systemd` (Linux) that copy the unit files to the right location and enable the service.
4. **README section** explaining optional supervision setup.

**Exit criteria.** After a reboot, `jotd` is running before the first hook invocation.

---

## Cross-cutting requirements

These apply to every milestone from M1 onward:

- **No external Go dependencies** beyond the standard library and `golang.org/x/sys/unix`. Keeps the single-binary promise honest.
- **Every exported function has a doc comment.**
- **Every milestone's exit criteria must be demonstrated on both macOS and Linux** before the milestone is considered done.
- **Decision log.** Append any architectural decision made during implementation to `docs/design/decisions.md` with date, context, and rationale.
- **Log lines are the debugging interface.** Helper logs every request at INFO and every failure at WARN.

## For the implementing agent

Start with Milestone 0 regardless of your familiarity with the repo. The inventory is the single source of truth for Milestone 5's scope; getting it wrong costs more than doing it right.

At each milestone boundary, stop and summarize: what was built, what was tested, what was deferred, any deviations from this doc. Update `docs/design/decisions.md` if the deviation is architectural.

If a requirement in this doc conflicts with `architecture.md`, treat `architecture.md` as authoritative and flag the conflict.