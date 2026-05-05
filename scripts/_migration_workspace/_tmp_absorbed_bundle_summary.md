# ABSORBED bundle: marker-only migration

Three bash helpers that disappear in Python — replaced by language-native idioms. No translation, only marker swap + name-map row.

---

## 1. `safe`

- **Bash signature:** `safe <command> [args...]` (line 1797)
- **PENDING marker line:** 1796
- **Purpose:** Run command via `hide_errors`; on non-zero exit substitute `(unavailable)`.
- **Marker replacement:** `# [ABSORBED -> try/except @ 2026-05-04]`
- **Name-map row:**
  `| ABSORBED | safe | (cmd...) -> str | try/except replaces error-tolerant cmd execution; "(unavailable)" sentinel on failure | 2026-05-04 |`
- **Canonical Python idiom:**
  ```python
  def _safe(fn, *args, **kwargs) -> str:
      try:
          out = fn(*args, **kwargs)
          return out if out else "(unavailable)"
      except Exception:
          return "(unavailable)"

  branch = _safe(git_get_branch_name, cwd)
  ```

---

## 2. `_stash`

- **Bash signature:** `_stash <namespace> <key> <value>` (line 2722) — `eval "${1}_${2}=\"\$3\""`
- **PENDING marker line:** 2721
- **Purpose:** Set dynamic shell var named `<namespace>_<key>` to value (poor man's 2-D map).
- **Marker replacement:** `# [ABSORBED -> dict @ 2026-05-04]`
- **Name-map row:**
  `| ABSORBED | _stash | (ns, key, val) -> None | plain dict keyed by (ns, key) replaces eval-based dynamic var | 2026-05-04 |`

## 3. `_lookup`

- **Bash signature:** `_lookup <namespace> <key>` (line 2724) — `eval "printf '%s' \"\${$_v:-}\""`
- **PENDING marker line:** 2723
- **Purpose:** Read dynamic shell var `<namespace>_<key>`; empty string if unset.
- **Marker replacement:** `# [ABSORBED -> dict @ 2026-05-04]`
- **Name-map row:**
  `| ABSORBED | _lookup | (ns, key) -> str | dict.get((ns, key), "") replaces eval-based dynamic var read | 2026-05-04 |`

### Canonical Python idiom (paired)

```python
# Module-level state for debate dynamic vars
_AGENT_STATE: dict[tuple[str, str], str] = {}

def _stash(ns: str, key: str, val: str) -> None:
    _AGENT_STATE[(ns, key)] = val

def _lookup(ns: str, key: str) -> str:
    return _AGENT_STATE.get((ns, key), "")

# Call site:
_stash("CURRENT_MODEL", "gemini", os.environ.get("GEMINI_MODEL", ""))
m = _lookup("CURRENT_MODEL", agent)
```

---

## Call sites in `jot-plugin-orchestrator.sh`

### `safe` (jot core: jot_session_start gather phase)
- 1973 — `BRANCH=$(safe git_get_branch_name "$CWD")`
- 1974 — `COMMITS=$(safe git_get_recent_commits "$CWD")`
- 1975 — `UNCOMMITTED=$(safe git_get_uncommitted "$CWD")`
- 1976 — `OPEN_TODOS=$(safe scan_open_todos "$REPO_ROOT")`
- 1978 — `CONVERSATION=$(safe python3 "$SCRIPTS_DIR/capture-conversation.py" "$TRANSCRIPT_PATH")`

### `_stash` (debate dynamic vars: init_agent_models, rotate_to_next_model)
- 2730 — `_stash CURRENT_MODEL "$_a" ""`
- 2731 — `_stash TRIED_MODELS  "$_a" ""`
- 2733 — `_stash CURRENT_MODEL gemini "${GEMINI_MODEL:-}"`
- 2734 — `_stash CURRENT_MODEL codex  "${CODEX_MODEL:-}"`
- 2735 — `_stash TRIED_MODELS  gemini "${GEMINI_MODEL:-}"`
- 2736 — `_stash TRIED_MODELS  codex  "${CODEX_MODEL:-}"`
- 2904 — `_stash CURRENT_MODEL "$agent" "$next"`
- 2906 — `_stash TRIED_MODELS "$agent" "${tried},${next}"`

### `_lookup` (debate dynamic vars: get_current_model, capacity check, rotate)
- 2742 — `m=$(_lookup CURRENT_MODEL "$a")`
- 2803 — `tried=$(_lookup TRIED_MODELS "$agent")`
- 2905 — `tried=$(_lookup TRIED_MODELS "$agent")`

---

## Merger handoff notes

- Replace each PENDING marker (lines 1796, 2721, 2723) with the ABSORBED string above.
- Do NOT delete the bash function bodies in this monolith pass — bash callers (lines 1973-1978, 2730-2906) still reference them. The bodies disappear when the entire surrounding function is ported to Python.
- In Python ports of jot core, replace `safe X` calls with `_safe(X, ...)` helper above.
- In Python ports of debate, replace the dual `(CURRENT_MODEL, TRIED_MODELS)` namespaces with a single `dict[tuple[str, str], str]` (or two dicts `current_model: dict[str, str]`, `tried_models: dict[str, str]` — equivalent, and arguably cleaner since the namespace dimension is closed).
