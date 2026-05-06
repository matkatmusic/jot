#!/usr/bin/env python3
"""Merge migration workspace temp pairs into the canonical monolith files.

For each function name P, looks for `_tmp_<P>.py` + `_tmp_test_<P>.py`,
rewrites them, appends to scripts/jot_plugin_orchestrator.py and
scripts/test_monolith.py, swaps the corresponding bash [PENDING] marker,
appends a migration-name-map.md row, and deletes the temp pair.

Conservative: skips pairs that need bash-name -> python-name aliasing
(e.g. tests patching `_default_model` instead of `debate_defaultModel`).
Such pairs are reported at the end for manual handling.

Does NOT run pytest. Verification deferred to end of merge batch.
"""
from __future__ import annotations

import ast
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path("/Users/matkatmusicllc/Programming/jot-worktrees/python-migration")
WORKSPACE = REPO / "scripts" / "_migration_workspace"
ORCH_PY = REPO / "scripts" / "jot_plugin_orchestrator.py"
TEST_PY = REPO / "scripts" / "test_monolith.py"
NAME_MAP = REPO / "scripts" / "migration-name-map.md"
BASH = REPO / "scripts" / "jot-plugin-orchestrator.sh"
TODAY = date.today().isoformat()

# Bash function name -> Python name. Drives marker swaps.
BASH_TO_PY: dict[str, str] = {
    "_default_model": "debate_defaultModel",
    "agent_ready_marker": "debate_agentReadyMarker",
    "agent_error_markers": "debate_agentErrorMarkers",
    "agent_launch_cmd": "debate_agentLaunchCmd",
    "any_live_lock": "debate_anyLiveLock",
    "archive_debate": "debate_archive",
    "debate_build_claude_cmd": "debate_buildClaudeCmd",
    "debate_build_prompts": "debate_buildClaudePrompts",
    "check_resume_feasibility": "debate_checkResumeFeasibility",
    "debate_claim_session": "debate_claimSession",
    "clean_stale_locks": "debate_cleanStaleLocks",
    "cleanup": "debate_cleanup",
    "detect_available_agents": "debate_detectAvailableAgents",
    "find_matching_debate": "debate_findMatching",
    "init_agent_models": "debate_initAgentModels",
    "init_hook_context": "debate_initHookContext",
    "debate_launch": "debate_launch",
    "launch_agent": "debate_launchAgent",
    "live_debate_session": "debate_liveSession",
    "_next_model": "debate_nextModel",
    "pane_has_capacity_error": "debate_paneHasCapacityError",
    "_probe_codex": "debate_probeCodex",
    "_probe_gemini": "debate_probeGemini",
    "retry_pane_with_next_model": "debate_retryPaneWithNextModel",
    "send_prompt": "debate_sendPromptToAgent",
    "debate_tmux_orchestrator": "debate_tmuxOrchestrator",
    "wait_for_outputs": "debate_waitForOutputs",
    "write_failed": "debate_writeFailed",
    "jot_diag_collect": "jot_collectDiagnostics",
    "jot_session_end": "jot_sessionEnd",
    "jot_session_start": "jot_sessionStart",
    "jot_stop": "jot_stop",
    "plate_summary_stop": "plate_summaryStop",
    "plate_summary_watch": "plate_summaryWatch",
    "wait_for_file": "shell_waitForFile",
    "todo_launcher": "todo_launcher",
    "scan_open_todos": "todo_scanOpen",
    "todo_session_start": "todo_sessionStart",
    "todo_session_end": "todo_sessionEnd",
    "todo_stop": "todo_stop",
    "launch_agents_parallel": "debate_launchAgentsParallel",
    "new_empty_pane": "debate_newEmptyPane",
    "debate_abort_main": "debateAbort_main",
    "jot_main": "jot_main",
    "todo_main": "todo_main",
    "todo_list_main": "todoList_main",
    "plate_main": "plate_main",
    "debate_main": "debate_main",
    "debate_retry_main": "debateRetry_main",
}

PY_TO_BASH = {v: k for k, v in BASH_TO_PY.items()}

STDLIB_ALWAYS_OK = {
    "json", "hashlib", "errno", "fcntl", "os", "re", "shutil", "signal",
    "subprocess", "sys", "tempfile", "time", "datetime", "pathlib",
    "types", "typing", "collections", "io", "string", "textwrap",
    "functools", "itertools", "contextlib", "uuid", "random", "math",
}


def _orch_existing_imports() -> set[str]:
    """Return top-level module names already imported in orchestrator."""
    src = ORCH_PY.read_text()
    tree = ast.parse(src)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _func_imports(src: str) -> set[str]:
    """Top-level imports in the temp function source."""
    tree = ast.parse(src)
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def _strip_function_boilerplate(src: str) -> str:
    """Drop sys.path/import-bridge boilerplate; keep contract comment + body.

    Lines removed:
      - module docstring (first triple-quoted string-statement at top)
      - `import sys`, `from pathlib import Path`, `import os` ONLY if part
         of the boilerplate sys.path block (we keep them if used elsewhere
         via stdlib re-add later).
      - `sys.path.insert(...)` and surrounding `if str(HERE) ...` guards
      - `from jot_plugin_orchestrator import *` and try/except dependency
         shims.
    Body returned: the def(s) + supporting module-level data.
    """
    tree = ast.parse(src)
    keep_nodes: list[ast.AST] = []
    for node in tree.body:
        # Skip module docstring
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node is tree.body[0]
        ):
            continue
        # Skip future imports
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        # Skip all imports (stdlib re-added separately by orchestrator)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # Skip sys.path manipulation patterns
        if isinstance(node, ast.Assign):
            # `HERE = Path(__file__).resolve().parent`
            if any(isinstance(t, ast.Name) and t.id == "HERE" for t in node.targets):
                continue
        if isinstance(node, ast.If):
            # `if str(HERE) not in sys.path: sys.path.insert(...)`
            test_src = ast.unparse(node.test)
            if "sys.path" in test_src or "HERE" in test_src:
                continue
        if isinstance(node, ast.Expr):
            try:
                exp_src = ast.unparse(node.value)
            except Exception:
                exp_src = ""
            if "sys.path.insert" in exp_src:
                continue
        if isinstance(node, ast.Try):
            # Skip the dependency-fallback try/except blocks. They use
            # `from jot_plugin_orchestrator import` or `from _tmp_*`.
            try_src = ast.unparse(node)
            if "jot_plugin_orchestrator" in try_src or "_tmp_" in try_src:
                continue
        keep_nodes.append(node)

    chunks = []
    src_lines = src.splitlines(keepends=True)
    for n in keep_nodes:
        # Capture leading-comment lines immediately above the node
        start_line = getattr(n, "lineno", 1) - 1
        comment_start = start_line
        while comment_start > 0:
            prev = src_lines[comment_start - 1]
            stripped = prev.lstrip()
            if stripped.startswith("#"):
                comment_start -= 1
            elif prev.strip() == "":
                # allow ONE blank line between comment block and def, no further
                if comment_start - 2 >= 0 and src_lines[comment_start - 2].lstrip().startswith("#"):
                    comment_start -= 1
                else:
                    break
            else:
                break
        end_line = getattr(n, "end_lineno", start_line + 1)
        chunks.append("".join(src_lines[comment_start:end_line]))
    return "\n\n".join(c.rstrip() + "\n" for c in chunks)


def _rewrite_test_src(src: str, py_name: str) -> tuple[str, list[str]]:
    """Rewrite a temp test source for monolith use.

    Returns (rewritten_src, warnings).
    """
    warnings: list[str] = []
    lines = src.splitlines(keepends=True)
    out_lines: list[str] = []
    skip_next_blank = False
    in_module_doc = False
    seen_module_doc = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Drop module docstring
        if not seen_module_doc and stripped.startswith('"""'):
            in_module_doc = True
            seen_module_doc = True
            if stripped.count('"""') >= 2:
                in_module_doc = False
            continue
        if in_module_doc:
            if '"""' in stripped:
                in_module_doc = False
            continue
        # Drop boilerplate lines
        if (
            re.match(r"^\s*HERE\s*=\s*Path\(__file__\)", line)
            or re.match(r"^\s*if\s+str\(HERE\)\s+not\s+in\s+sys\.path", line)
            or re.match(r"^\s*sys\.path\.insert\(0,\s*str\(HERE\)\)", line)
            or re.match(r"^\s*sys\.path\.insert\(0,\s*os\.path", line)
            or re.match(r"^\s*sys\.path\.insert\(0,\s*os\.path\.dirname", line)
        ):
            continue
        # Strip lines that follow a stripped if-block continuation (one-liner indented after `if str(HERE)...`)
        # Drop `from _tmp_<P> import <P>` lines (handled by top-of-file imports)
        if re.match(r"^\s*from\s+_tmp_\w+\s+import\s+", line):
            continue
        # Drop `import _tmp_<P>` and `import _tmp_<P> as <alias>` lines (with optional trailing comment)
        if re.match(r"^\s*import\s+_tmp_\w+(\s+as\s+\w+)?\s*(#.*)?$", line):
            continue
        # Same for `from _tmp_<P> import ...` with optional trailing comment
        if re.match(r"^\s*from\s+_tmp_\w+\s+import\s+\S+(\s*,\s*\S+)*\s*(#.*)?$", line):
            continue
        # Drop `from __future__ import annotations`
        if re.match(r"^\s*from\s+__future__\s+import\s+annotations", line):
            continue
        # Drop bare `import sys` / `import os` if followed only by sys.path lines
        # (we conservatively keep them; tests may use os/sys legitimately)
        out_lines.append(line)

    body = "".join(out_lines)

    # Rewrite patches: "_tmp_X.module.func" -> jot_plugin_orchestrator.module.func
    # Match either patch("...") or monkeypatch.setattr("..."), preserving rest.
    def _patch_str_repl(m: re.Match) -> str:
        prefix = m.group(1)
        path = m.group(2)
        # path is like "_tmp_<P>.attr1.attr2..."
        parts = path.split(".")
        # Drop _tmp_<P> head
        rest = parts[1:]
        if not rest:
            warnings.append(f"empty patch path after stripping prefix: {m.group(0)}")
            return m.group(0)
        # patch("_tmp_X.shutil.which") => patch("jot_plugin_orchestrator.shutil.which")
        return f'{prefix}"jot_plugin_orchestrator.{".".join(rest)}"'

    body = re.sub(
        r'(\bpatch\(\s*)"(_tmp_[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"',
        _patch_str_repl,
        body,
    )
    body = re.sub(
        r'(monkeypatch\.setattr\(\s*)"(_tmp_[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"',
        _patch_str_repl,
        body,
    )

    # Single-attr patch: monkeypatch.setattr("_tmp_X.callee", val)
    # -> monkeypatch.setattr(jot_plugin_orchestrator, "callee", val)
    def _single_attr_monkey(m: re.Match) -> str:
        callee = m.group(1)
        rest = m.group(2)
        return f'monkeypatch.setattr(jot_plugin_orchestrator, "{callee}", {rest}'

    body = re.sub(
        r'monkeypatch\.setattr\(\s*"_tmp_[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)"\s*,\s*(.+)',
        _single_attr_monkey,
        body,
    )

    # Bare attribute access: `_tmp_<name>.attr` -> `jot_plugin_orchestrator.attr`
    # (covers `patch(_tmp_X.time.sleep, ...)`, `_tmp_X.subprocess`, etc.)
    body = re.sub(
        r'\b_tmp_[A-Za-z_][A-Za-z0-9_]*\b',
        'jot_plugin_orchestrator',
        body,
    )

    # Detect leftover _tmp_ references and warn
    leftover = re.findall(r'"_tmp_[A-Za-z_][A-Za-z0-9_]*[^"]*"', body)
    if leftover:
        warnings.append(f"leftover _tmp_ string refs: {leftover[:3]}")

    # Detect bash-name-aliased patches: patch("jot_plugin_orchestrator._default_model")
    # These need rename to actual python name.
    for bash_name, py in BASH_TO_PY.items():
        if bash_name == py:
            continue
        # Match attribute on jot_plugin_orchestrator that is the bash name
        pattern = rf'jot_plugin_orchestrator\.{re.escape(bash_name)}\b'
        if re.search(pattern, body):
            body = re.sub(pattern, f"jot_plugin_orchestrator.{py}", body)

    return body, warnings


def _bash_func_def_lineno(bash_name: str) -> int | None:
    """Find line of `<bash_name>()` def in the bash file. None if not found."""
    src = BASH.read_text().splitlines()
    pat = re.compile(rf"^{re.escape(bash_name)}\s*\(\s*\)\s*\{{")
    for i, line in enumerate(src):
        if pat.match(line):
            return i + 1  # 1-indexed
    return None


def _swap_bash_marker(bash_name: str, py_name: str) -> bool:
    """Swap `# [PENDING]` above the bash function to MIGRATED. Returns success.

    Idempotent: if marker is already MIGRATED for this py_name, returns True.
    """
    src_lines = BASH.read_text().splitlines(keepends=True)
    pat = re.compile(rf"^{re.escape(bash_name)}\s*\(\s*\)\s*\{{")
    for i, line in enumerate(src_lines):
        if pat.match(line):
            # Search backward for the [PENDING] marker (or already-MIGRATED marker)
            for j in range(i - 1, max(-1, i - 5), -1):
                if "# [PENDING]" in src_lines[j]:
                    indent = re.match(r"(\s*)", src_lines[j]).group(1)
                    src_lines[j] = f"{indent}# [MIGRATED -> {py_name} @ {TODAY}]\n"
                    BASH.write_text("".join(src_lines))
                    return True
                if f"[MIGRATED -> {py_name}" in src_lines[j]:
                    return True  # already swapped in a prior session
            return False
    return False


def _append_to_orchestrator(func_body: str, new_imports: list[str]) -> None:
    """Append function body to orchestrator. Add stdlib imports if needed."""
    src = ORCH_PY.read_text()
    if new_imports:
        # Insert after existing top-level imports (find last import line)
        lines = src.splitlines(keepends=True)
        last_import = 0
        for i, line in enumerate(lines):
            if re.match(r"^(import\s+|from\s+\S+\s+import\s+)", line):
                last_import = i
        # Insert after last import
        insert_at = last_import + 1
        for mod in sorted(new_imports):
            lines.insert(insert_at, f"import {mod}\n")
            insert_at += 1
        src = "".join(lines)
    if not src.endswith("\n"):
        src += "\n"
    src += "\n\n" + func_body.rstrip() + "\n"
    ORCH_PY.write_text(src)


def _append_to_test_monolith(test_body: str, py_name: str) -> None:
    """Append test body and update import block."""
    src = TEST_PY.read_text()
    # Add py_name to import block from jot_plugin_orchestrator import (...)
    # Find the import block
    pat = re.compile(
        r"from jot_plugin_orchestrator import \(\n(.*?)\n\)",
        re.DOTALL,
    )
    m = pat.search(src)
    if m:
        block = m.group(1)
        existing_lines = [l.rstrip().rstrip(",").strip() for l in block.split("\n")]
        existing_set = {l for l in existing_lines if l}
        if py_name not in existing_set:
            existing_set.add(py_name)
            new_lines = sorted(existing_set, key=lambda s: s.lower())
            new_block = "\n".join(f"    {l}," for l in new_lines)
            src = src[:m.start(1)] + new_block + src[m.end(1):]
    if not src.endswith("\n"):
        src += "\n"
    src += "\n\n# --- " + py_name + " ---\n\n" + test_body.lstrip() + "\n"
    TEST_PY.write_text(src)


def _name_map_has_row(py_name: str) -> bool:
    """Check if name-map already has a row for this py_name."""
    src = NAME_MAP.read_text()
    return bool(re.search(rf"^\|\s*{re.escape(py_name)}\s*\|", src, re.MULTILINE))


def _append_name_map_row(py_name: str, bash_name: str, sig: str, notes: str = "") -> None:
    """Append a row to migration-name-map.md."""
    row = f"| {py_name} | {bash_name} | {sig} | {notes} | {TODAY} |\n"
    src = NAME_MAP.read_text()
    if not src.endswith("\n"):
        src += "\n"
    src += row
    NAME_MAP.write_text(src)


def _extract_signature(func_src: str, py_name: str) -> str:
    """Pull the `def <py_name>(...)` signature line for the name-map row."""
    m = re.search(rf"^def\s+{re.escape(py_name)}\s*\(([^)]*)\)\s*->.*?:", func_src, re.MULTILINE)
    if m:
        return f"{py_name}({m.group(1).strip()})"
    m = re.search(rf"^def\s+{re.escape(py_name)}\s*\(([^)]*)\):", func_src, re.MULTILINE)
    if m:
        return f"{py_name}({m.group(1).strip()})"
    return py_name + "(?)"


TEST_BASH_MAP: dict[str, str] = {
    "tmux_launcherTests": "tmux_launcher_tests",
    "tmux_layoutTests": "tmux_layout_tests",
    "tmux_paneTests": "tmux_pane_tests",
    "tmux_sendKeysTests": "tmux_send_keys_tests",
    "tmux_sessionTests": "tmux_session_tests",
    "tmux_setOptionTests": "tmux_set_option_tests",
    "tmux_windowTests": "tmux_window_tests",
    "tmux_cancelAndSendTests": "tmux_cancel_and_send_tests",
}


def _swap_test_marker(bash_name: str, py_name: str) -> bool:
    """Swap [PENDING] above bash *_tests to [TEST -> ...]. Idempotent."""
    src_lines = BASH.read_text().splitlines(keepends=True)
    pat = re.compile(rf"^{re.escape(bash_name)}\s*\(\s*\)\s*\{{")
    for i, line in enumerate(src_lines):
        if pat.match(line):
            for j in range(i - 1, max(-1, i - 5), -1):
                if "# [PENDING]" in src_lines[j]:
                    indent = re.match(r"(\s*)", src_lines[j]).group(1)
                    src_lines[j] = f"{indent}# [TEST -> test_{py_name} @ {TODAY}]\n"
                    BASH.write_text("".join(src_lines))
                    return True
                if "[TEST -> " in src_lines[j]:
                    return True
            return False
    return False


def merge_test_only(py_name: str) -> tuple[bool, str]:
    """Merge a TEST-only file. py_name is the suffix after _tmp_test_."""
    test_path = WORKSPACE / f"_tmp_test_{py_name}.py"
    if not test_path.exists():
        return False, f"missing {test_path.name}"
    bash_name = TEST_BASH_MAP.get(py_name)
    if not bash_name:
        return False, f"no test bash mapping for {py_name}"

    test_src = test_path.read_text()

    # Reuse rewrite (no alias map needed for tests-only).
    test_body, warnings = _rewrite_test_src(test_src, py_name)

    # Strip top-level `from jot_plugin_orchestrator import *` (already in monolith).
    test_body = re.sub(
        r"^\s*from\s+jot_plugin_orchestrator\s+import\s+\*.*$",
        "",
        test_body,
        flags=re.MULTILINE,
    )
    # Strip workspace sys.path insert variants.
    test_body = re.sub(
        r"^\s*sys\.path\.insert\(0,\s*os\.path\.join\([^)]*\)\)\s*$",
        "",
        test_body,
        flags=re.MULTILINE,
    )

    bad_refs = []
    for m in re.finditer(r'(?:^|[^a-zA-Z0-9_])(_tmp_[A-Za-z_][A-Za-z0-9_]*)(\.[A-Za-z_][A-Za-z0-9_]*|\s+(?:import|as))', test_body):
        bad_refs.append(m.group(0).strip())
    if bad_refs:
        return False, f"test still has _tmp_ refs: {bad_refs[:5]}"

    src = TEST_PY.read_text()
    if not src.endswith("\n"):
        src += "\n"
    src += "\n\n# --- " + py_name + " (TEST cluster) ---\n\n" + test_body.lstrip() + "\n"
    TEST_PY.write_text(src)

    if not _swap_test_marker(bash_name, py_name):
        return False, f"bash test marker not found for {bash_name}"

    test_path.unlink()
    return True, f"merged TEST {py_name}"


def merge_one(py_name: str) -> tuple[bool, str]:
    """Merge one function pair into the monolith. Returns (ok, message)."""
    fn_path = WORKSPACE / f"_tmp_{py_name}.py"
    test_path = WORKSPACE / f"_tmp_test_{py_name}.py"
    if not fn_path.exists() or not test_path.exists():
        return False, f"missing files: {fn_path.name} or {test_path.name}"

    bash_name = PY_TO_BASH.get(py_name)
    if not bash_name:
        return False, f"no bash mapping for {py_name}"

    fn_src = fn_path.read_text()
    test_src = test_path.read_text()

    # Detect import-aliasing patterns: `from jot_plugin_orchestrator import X as Y`.
    # We collect alias map {Y: X} and rewrite Y(...) -> X(...) in the function body.
    alias_map: dict[str, str] = {}
    for m in re.finditer(
        r"^\s*from\s+jot_plugin_orchestrator\s+import\s+(\w+)\s+as\s+(\w+)",
        fn_src,
        re.MULTILINE,
    ):
        alias_map[m.group(2)] = m.group(1)

    # Detect new stdlib imports
    fn_imp = _func_imports(fn_src)
    orch_imp = _orch_existing_imports()
    new_imports = sorted(
        m for m in fn_imp
        if m in STDLIB_ALWAYS_OK and m not in orch_imp and m != "jot_plugin_orchestrator"
    )

    # Strip boilerplate from function body
    body = _strip_function_boilerplate(fn_src)
    if py_name not in body:
        return False, f"def {py_name} not found after boilerplate strip"

    # Rewrite import aliases in the function body: `Y(...)` -> `X(...)`.
    for alias, real in alias_map.items():
        body = re.sub(rf"\b{re.escape(alias)}\b", real, body)

    # Rewrite tests
    test_body, warnings = _rewrite_test_src(test_src, py_name)

    # Check for problematic _tmp_ references (excluding test names that contain _tmp_jot etc).
    # Look for: import statements, string literals, and `_tmp_<name>.attr` access.
    bad_refs: list[str] = []
    for m in re.finditer(r'(?:^|[^a-zA-Z0-9_])(_tmp_[A-Za-z_][A-Za-z0-9_]*)(\.[A-Za-z_][A-Za-z0-9_]*|\s+(?:import|as))', test_body):
        bad_refs.append(m.group(0).strip())
    for m in re.finditer(r'"_tmp_[A-Za-z_][A-Za-z0-9_]*[^"]*"', test_body):
        bad_refs.append(m.group(0))
    if bad_refs:
        return False, f"test still has _tmp_ refs: {bad_refs[:5]}"

    # Idempotence: bail if function already in orchestrator
    if re.search(rf"^def {re.escape(py_name)}\s*\(", ORCH_PY.read_text(), re.MULTILINE):
        # Function body was appended on a prior partial run.
        # Just clean up: swap marker (if pending), append name-map row, delete temps.
        if not _swap_bash_marker(bash_name, py_name):
            return False, f"bash marker not found/swapped for {bash_name}"
        sig = _extract_signature(body, py_name)
        notes = "RELAXED_COVERAGE" if "RELAXED_COVERAGE" in test_src else ""
        if not _name_map_has_row(py_name):
            _append_name_map_row(py_name, bash_name, sig, notes)
        fn_path.unlink()
        test_path.unlink()
        return True, f"recovered partial merge for {py_name}"

    # Append to monolith
    _append_to_orchestrator(body, new_imports)
    _append_to_test_monolith(test_body, py_name)

    # Bash marker swap
    if not _swap_bash_marker(bash_name, py_name):
        return False, f"bash marker not found/swapped for {bash_name}"

    # Name-map row
    sig = _extract_signature(body, py_name)
    notes = "RELAXED_COVERAGE" if "RELAXED_COVERAGE" in test_src else ""
    _append_name_map_row(py_name, bash_name, sig, notes)

    # Delete temp files
    fn_path.unlink()
    test_path.unlink()

    msg = f"merged {py_name}"
    if new_imports:
        msg += f" (+imports: {','.join(new_imports)})"
    if warnings:
        msg += f" [warn: {warnings}]"
    return True, msg


def main(argv: list[str]) -> int:
    test_only_mode = False
    if argv and argv[0] == "--test-only":
        test_only_mode = True
        argv = argv[1:]

    if not argv:
        if test_only_mode:
            names: list[str] = []
            for p in sorted(WORKSPACE.glob("_tmp_test_*.py")):
                stem = p.stem
                name = stem[len("_tmp_test_"):]
                if name in TEST_BASH_MAP:
                    names.append(name)
            argv = names
        else:
            names = []
            for p in sorted(WORKSPACE.glob("_tmp_*.py")):
                stem = p.stem
                if stem.startswith("_tmp_test_"):
                    continue
                name = stem[len("_tmp_"):]
                if name in PY_TO_BASH:
                    names.append(name)
            argv = names

    successes: list[str] = []
    failures: list[tuple[str, str]] = []
    for name in argv:
        if test_only_mode:
            ok, msg = merge_test_only(name)
        else:
            ok, msg = merge_one(name)
        if ok:
            successes.append(msg)
            print(f"OK  {msg}")
        else:
            failures.append((name, msg))
            print(f"SKIP {name}: {msg}")

    print(f"\n=== {len(successes)} merged, {len(failures)} skipped ===")
    if failures:
        print("Skipped (need manual handling):")
        for name, msg in failures:
            print(f"  - {name}: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
