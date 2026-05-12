#!/usr/bin/env python3
"""Static call-graph generator rooted at dispatch_main() in the jot plugin.

Output sections (markdown):
  1. Tree      indented call graph, source order, inline branch markers
  2. Paths     numbered logic-paths index (one entry per distinct walk to a return)
  3. Unresolvable subprocess invocations
  4. Indirect dispatch (manual review)

Run:
  python3 audit/build_call_graph.py > docs/design/call_graph.md
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
ROOTS = [REPO / "common" / "scripts", REPO / "scripts"]
EXCLUDE_BASENAMES = {"conftest.py"}
EXCLUDE_DIRS = {"__pycache__", "tests"}

# Dispatch-table variable names we special-case.
DISPATCH_TABLE_NAMES = {"_ARGV_DISPATCH", "_PROMPT_DISPATCH", "_DISPATCH"}

# Entry point.
ENTRY_FILE = REPO / "scripts" / "jot_plugin_orchestrator.py"
ENTRY_FN = "dispatch_main"

# subprocess.* method classifications.
SUBPROCESS_BLOCKING = {"run", "check_output", "check_call", "call", "getoutput", "getstatusoutput"}
SUBPROCESS_FAF = {"Popen"}

INDENT = "  "

# ---------------------------------------------------------------------------
# Pass 1 — index
# ---------------------------------------------------------------------------

# defined_names[name] -> list[(file, FunctionDef node)]
defined_names: dict[str, list[tuple[Path, ast.FunctionDef]]] = defaultdict(list)

# imports_by_file[file][local_name] = (module_dotted, original_name_or_None)
imports_by_file: dict[Path, dict[str, tuple[str, str | None]]] = defaultdict(dict)

# dispatch_tables[(file, var_name)] = list of (key_repr, target_fn_name, ast_call_node)
DispatchEntry = tuple[str, str, ast.Call]
dispatch_tables: dict[tuple[Path, str], list[DispatchEntry]] = {}

# filename_fullpath_map[filename.py] -> Path
# One file per basename. _build_filename_fullpath_map() raises on collision.
filename_fullpath_map: dict[str, Path] = {}

# file_ast[file] -> ast.Module (for re-walking during render)
file_ast: dict[Path, ast.Module] = {}

# subprocess_aliases[file][var_name] = subprocess_method_name
# Production code aliases subprocess.run via DI patterns like
#   `run = _subprocess_run or subprocess.run`. Track these so later
#   `run(cmd)` calls are classified as subprocess calls.
subprocess_aliases: dict[Path, dict[str, str]] = defaultdict(dict)


def _iter_py_files() -> Iterable[Path]:
    """Yield every .py file under ROOTS, honouring excludes."""
    for root in ROOTS:
        for p in root.rglob("*.py"):
            if p.name in EXCLUDE_BASENAMES:
                continue
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            yield p


def _collect_function_defs(node: ast.AST, file: Path) -> None:
    """Register every FunctionDef / AsyncFunctionDef found in `node` under defined_names.

    Walks classes (methods registered as bare names) and nested defs.
    """
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined_names[sub.name].append((file, sub))


def _collect_imports(tree: ast.Module, file: Path) -> None:
    """Collect all `import` / `from ... import ...` bindings in this file —
    including those inside function bodies (production code uses function-local
    imports to break circular deps, e.g. plate_cli._cmd_push imports spawn from
    spawn_summary_agent inside the function body).
    """
    imap = imports_by_file[file]
    for sub in ast.walk(tree):
        if isinstance(sub, ast.Import):
            for alias in sub.names:
                local = alias.asname or alias.name.split(".")[0]
                imap[local] = (alias.name, None)
        elif isinstance(sub, ast.ImportFrom):
            module = sub.module or ""
            for alias in sub.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imap[local] = (module, alias.name)


def _collect_dispatch_tables(tree: ast.Module, file: Path) -> None:
    """Find module-level `_ARGV_DISPATCH` / `_PROMPT_DISPATCH` / `_DISPATCH` assignments.

    Extracts each entry's key and target function name from lambda body or direct ref.
    """
    for node in tree.body:
        # Plain assign: NAME = {...} or NAME: type = {...}
        targets: list[ast.AST]
        value: ast.AST | None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue

        for target in targets:
            if not (isinstance(target, ast.Name) and target.id in DISPATCH_TABLE_NAMES):
                continue
            entries = _extract_dispatch_entries(value)
            if entries:
                dispatch_tables[(file, target.id)] = entries


def _extract_dispatch_entries(value: ast.AST | None) -> list[DispatchEntry]:
    """Pull (key_repr, target_fn_name, the_lambda_call) from a Dict or Tuple-of-pairs."""
    if value is None:
        return []
    pairs: list[tuple[ast.AST, ast.AST]] = []
    if isinstance(value, ast.Dict):
        for k, v in zip(value.keys, value.values):
            if k is not None:
                pairs.append((k, v))
    elif isinstance(value, ast.Tuple):
        for elt in value.elts:
            if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                pairs.append((elt.elts[0], elt.elts[1]))
    else:
        return []

    entries: list[DispatchEntry] = []
    for k_node, v_node in pairs:
        key_repr = ast.unparse(k_node) if k_node is not None else "?"
        target_name, target_call = _extract_lambda_target(v_node)
        if target_name is None:
            continue
        entries.append((key_repr, target_name, target_call))
    return entries


def _extract_lambda_target(node: ast.AST) -> tuple[str | None, ast.Call | None]:
    """Given a dispatch entry value (lambda or direct function ref), return
    (target_function_name, the_Call_node_if_lambda).

    Handles:
      lambda argv: jot_sessionStart(*argv)              -> ('jot_sessionStart', Call)
      lambda: jot_main()                                -> ('jot_main', Call)
      jot_main                                           -> ('jot_main', None)  (direct ref)
    """
    if isinstance(node, ast.Lambda):
        # Find the first Call inside the lambda body.
        body = node.body
        if isinstance(body, ast.Call):
            name = _call_target_name(body)
            return name, body
        # Lambda body may be an expression containing a Call.
        for sub in ast.walk(body):
            if isinstance(sub, ast.Call):
                return _call_target_name(sub), sub
        return None, None
    if isinstance(node, ast.Name):
        return node.id, None
    if isinstance(node, ast.Attribute):
        return node.attr, None
    return None, None


def _call_target_name(call: ast.Call) -> str | None:
    """Bare/attribute call target name extraction."""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _build_filename_fullpath_map() -> None:
    """Index every .py filename under REPO so subprocess paths resolve by basename.

    Asserts one file per basename. If a collision is ever introduced, the
    resolver must be redesigned to disambiguate (e.g. by importer's directory).
    """
    for p in REPO.rglob("*.py"):
        if any(part in EXCLUDE_DIRS or part.startswith(".") for part in p.parts):
            continue
        if p.name in EXCLUDE_BASENAMES:
            continue
        prior = filename_fullpath_map.get(p.name)
        if prior is not None and prior != p:
            raise AssertionError(
                f"basename collision: {p.name} matches both\n"
                f"  {prior.relative_to(REPO)}\n"
                f"  {p.relative_to(REPO)}\n"
                "Resolver assumes unique basenames; redesign needed."
            )
        filename_fullpath_map[p.name] = p


def _collect_subprocess_aliases(tree: ast.Module, file: Path) -> None:
    """Find assignments of the form `var = ... subprocess.METHOD ...` and
    register `var` as an alias for `subprocess.METHOD` within this file.

    Catches both direct (`run = subprocess.run`) and DI-default
    (`run = _subprocess_run or subprocess.run`) patterns.
    """
    amap = subprocess_aliases[file]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        # Walk the value expression looking for subprocess.METHOD attribute.
        for sub in ast.walk(node.value):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "subprocess"
                and (sub.attr in SUBPROCESS_BLOCKING or sub.attr in SUBPROCESS_FAF)
            ):
                amap[tgt.id] = sub.attr
                break


def pass1_index() -> None:
    """Build all global indices."""
    _build_filename_fullpath_map()
    for f in _iter_py_files():
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(f))
        except (SyntaxError, OSError):
            continue
        file_ast[f] = tree
        _collect_function_defs(tree, f)
        _collect_imports(tree, f)
        _collect_dispatch_tables(tree, f)
        _collect_subprocess_aliases(tree, f)


# ---------------------------------------------------------------------------
# Pass 2 — call resolver
# ---------------------------------------------------------------------------

# Render-state-record for one resolved call.
class Resolved:
    """Result of resolving an ast.Call. One of:
      - in_repo:    target is a FunctionDef in this codebase
      - subproc:    subprocess.run/Popen/etc.
      - dispatch:   loop-var call iterating a known dispatch table
      - skip:       not in-repo, not subprocess; ignored
      - unresolved: subprocess with dynamic argv (logged to side section)
    """

    __slots__ = (
        "kind",
        "target_file",
        "target_node",
        "label",
        "tag",
        "py_target",
        "py_argv",
        "src_line",
        "kwargs_str",
    )

    def __init__(
        self,
        kind: str,
        target_file: Path | None = None,
        target_node: ast.FunctionDef | None = None,
        label: str = "",
        tag: str = "",
        py_target: Path | None = None,
        py_argv: list[str] | None = None,
        src_line: str = "",
        kwargs_str: str = "",
    ) -> None:
        self.kind = kind
        self.target_file = target_file
        self.target_node = target_node
        self.label = label
        self.tag = tag
        self.py_target = py_target
        self.py_argv = py_argv or []
        self.src_line = src_line
        self.kwargs_str = kwargs_str


def _format_call_args(call: ast.Call) -> str:
    """Render positional args of a Call as a comma-separated string via ast.unparse.

    Spec: for in-repo calls, every positional arg is rendered (string literals
    therefore appear quoted; variables appear bare). Keyword args omitted.
    """
    parts = [ast.unparse(a) for a in call.args]
    return ", ".join(parts)


def _resolve_local_name(file: Path, name: str) -> tuple[Path, ast.FunctionDef] | None:
    """Resolve a bare Name to a FunctionDef defined in this codebase.

    Strategy:
      1. If `name` is in this file's imports → look up the original name in the
         imported module's file (if that module is in-repo). Resolve there.
      2. Else fall back to a global lookup: pick the unique defined_names entry,
         or one in the same file.
    """
    imap = imports_by_file.get(file, {})
    if name in imap:
        module_dotted, original_name = imap[name]
        # Resolve module to file under ROOTS.
        candidate_file = _resolve_module_to_file(module_dotted)
        if candidate_file is not None:
            target_name = original_name or name
            for f, node in defined_names.get(target_name, []):
                if f == candidate_file:
                    return f, node
            # Fall through: original_name may still resolve elsewhere.
            for f, node in defined_names.get(target_name, []):
                return f, node
        # Module unresolved — last-ditch attempt by name.
        target_name = original_name or name
        defs = defined_names.get(target_name, [])
        if len(defs) == 1:
            return defs[0]
        return None

    # Not imported — check if defined in this file itself, or unique globally.
    same_file = [(f, n) for (f, n) in defined_names.get(name, []) if f == file]
    if same_file:
        return same_file[0]
    defs = defined_names.get(name, [])
    if len(defs) == 1:
        return defs[0]
    return None


def _resolve_module_to_file(dotted: str) -> Path | None:
    """Resolve a dotted module path (e.g. common.scripts.jot_lib) to a .py file."""
    if not dotted:
        return None
    parts = dotted.split(".")
    # Try REPO / parts.py
    candidate = REPO.joinpath(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    # Try REPO / parts / __init__.py
    candidate = REPO.joinpath(*parts) / "__init__.py"
    if candidate.exists():
        return candidate
    # Try basename only.
    leaf = parts[-1] + ".py"
    return filename_fullpath_map.get(leaf)


def _resolve_attribute_call(file: Path, call: ast.Call) -> tuple[Path, ast.FunctionDef] | None:
    """`mod.foo(...)` — resolve via this file's imports."""
    f = call.func
    assert isinstance(f, ast.Attribute)
    base = f.value
    if not isinstance(base, ast.Name):
        return None
    mod_local = base.id
    imap = imports_by_file.get(file, {})
    if mod_local not in imap:
        return None
    module_dotted, _ = imap[mod_local]
    candidate_file = _resolve_module_to_file(module_dotted)
    if candidate_file is None:
        return None
    # Look up f.attr in that file's defined names.
    for fpath, node in defined_names.get(f.attr, []):
        if fpath == candidate_file:
            return fpath, node
    return None


def _classify_subprocess(call: ast.Call, file: Path | None = None) -> str | None:
    """If `call` is subprocess.run / subprocess.Popen / etc., return the tag.

    Also recognizes DI-aliased calls (e.g. `run(cmd)` where `run` is bound to
    `subprocess.run` via the alias map for `file`).

    Returns: '[blocking subproc]' / '[FaF subproc]' / None.
    """
    f = call.func
    if isinstance(f, ast.Attribute):
        base = f.value
        if isinstance(base, ast.Name) and base.id == "subprocess":
            if f.attr in SUBPROCESS_BLOCKING:
                return "[blocking subproc]"
            if f.attr in SUBPROCESS_FAF:
                return "[FaF subproc]"
    if isinstance(f, ast.Name) and file is not None:
        method = subprocess_aliases.get(file, {}).get(f.id)
        if method in SUBPROCESS_BLOCKING:
            return "[blocking subproc]"
        if method in SUBPROCESS_FAF:
            return "[FaF subproc]"
    return None


def _extract_argv_list(call: ast.Call) -> list[ast.AST] | None:
    """Return the positional argv list for subprocess.run/Popen.

    Recognizes a plain List literal AND `["..."] + var` (Add BinOp) where the
    left side is a List literal — common pattern for prepending a fixed head
    to a dynamic tail.
    """
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.List):
        return list(first.elts)
    if isinstance(first, ast.BinOp) and isinstance(first.op, ast.Add):
        if isinstance(first.left, ast.List):
            return list(first.left.elts)
    return None


def _resolve_subprocess(file: Path, call: ast.Call) -> Resolved:
    """Build a Resolved for a subprocess.* call."""
    tag = _classify_subprocess(call, file) or "[subproc]"
    argv = _extract_argv_list(call)
    src_line = ast.unparse(call)
    if argv is None:
        return Resolved(kind="unresolved", tag=tag, src_line=src_line)

    # Inspect argv[0]: if "python" / "python3" / matches sys.executable, treat as launcher.
    a0 = argv[0]
    a0_str = _str_value(a0)
    if a0_str in ("python", "python3", "python3.11", "python3.12") or _is_sys_executable(a0):
        # argv[1] should be the .py path.
        if len(argv) < 2:
            return Resolved(kind="unresolved", tag=tag, src_line=src_line)
        py_target = _resolve_py_target(argv[1])
        if py_target is None:
            return Resolved(kind="unresolved", tag=tag, src_line=src_line)
        remaining = [ast.unparse(a) for a in argv[2:]]
        return Resolved(kind="subproc", tag=tag, py_target=py_target, py_argv=remaining,
                        label=f"{py_target.name}::main()")

    # Non-python launcher — render the resolvable head.
    head_parts: list[str] = []
    for a in argv[:3]:
        s = _str_value(a)
        if s is None:
            break
        if s.startswith("-"):
            head_parts.append(s)
            continue
        head_parts.append(s)
        if len(head_parts) >= 2 and not s.startswith("-"):
            break
    head = " ".join(head_parts) if head_parts else "?"
    return Resolved(kind="subproc", tag=tag, label=head)


def _str_value(node: ast.AST) -> str | None:
    """Best-effort string-literal extraction. Supports Constant(str) and JoinedStr
    with all-Constant parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                # FormattedValue — emit a placeholder.
                parts.append("{?}")
        return "".join(parts)
    return None


def _is_sys_executable(node: ast.AST) -> bool:
    """True if `node` is `sys.executable`."""
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
        and node.attr == "executable"
    )


def _resolve_py_target(node: ast.AST) -> Path | None:
    """Resolve an AST node that should be a .py file path to an actual Path.

    Strategies:
      1. String literal "...foo.py" — extract basename, look up in filename_fullpath_map.
      2. f-string "{prefix}/foo.py" — same basename extraction.
      3. str(Path-expression) or Path-expression / "foo.py" — descend to find the literal.
      4. A bare Name like `_ORCHESTRATOR` whose module-level binding is a Path expression — resolve.
    """
    # Direct string / f-string
    s = _str_value(node)
    if s is not None and s.endswith(".py"):
        leaf = Path(s).name
        return filename_fullpath_map.get(leaf)

    # str(X) wrapper — descend into the argument before falling back to
    # the generic .py-constant walk (the arg might be a Name binding).
    if isinstance(node, ast.Call) and _call_target_name(node) == "str" and node.args:
        descended = _resolve_py_target(node.args[0])
        if descended is not None:
            return descended

    # Generic: walk the entire expression for any .py string constant.
    # Handles str(X), os.path.join(...), Path(...) / "foo.py", f-strings, etc.
    if isinstance(node, (ast.Call, ast.BinOp, ast.JoinedStr)):
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and sub.value.endswith(".py")
            ):
                return _resolve_py_target(sub)

    # Name reference to a constant — search every assignment in every file
    # (module-level AND function-local). Returns the first match.
    if isinstance(node, ast.Name):
        for tree in file_ast.values():
            for stmt in ast.walk(tree):
                tgt = None
                val = None
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                    tgt = stmt.targets[0].id
                    val = stmt.value
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    tgt = stmt.target.id
                    val = stmt.value
                if tgt == node.id and val is not None and val is not node:
                    resolved = _resolve_py_target(val)
                    if resolved is not None:
                        return resolved
        return None

    return None


def _resolve_call(file: Path, call: ast.Call) -> Resolved | None:
    """Resolve any ast.Call. Returns None if it should be skipped entirely."""
    # subprocess.* first (includes DI-aliased subprocess calls)
    if _classify_subprocess(call, file) is not None:
        return _resolve_subprocess(file, call)

    f = call.func
    # Dispatch-table attribute access (e.g. `_ARGV_DISPATCH.get(head)`):
    # treat as "table dereferenced here — expand all entries inline".
    if (
        isinstance(f, ast.Attribute)
        and isinstance(f.value, ast.Name)
        and f.value.id in DISPATCH_TABLE_NAMES
    ):
        return Resolved(kind="dispatch_table", label=f.value.id)

    # Bare Name
    if isinstance(f, ast.Name):
        # Could be a builtin / loop var. Filter by defined_names membership or import.
        resolved = _resolve_local_name(file, f.id)
        if resolved is None:
            return None
        tgt_file, tgt_node = resolved
        return Resolved(
            kind="in_repo",
            target_file=tgt_file,
            target_node=tgt_node,
            label=f"{f.id}({_format_call_args(call)})",
        )
    # Attribute mod.foo(...)
    if isinstance(f, ast.Attribute):
        resolved = _resolve_attribute_call(file, call)
        if resolved is None:
            return None
        tgt_file, tgt_node = resolved
        return Resolved(
            kind="in_repo",
            target_file=tgt_file,
            target_node=tgt_node,
            label=f"{tgt_node.name}({_format_call_args(call)})",
        )
    return None


# ---------------------------------------------------------------------------
# Pass 2 — logic-path tree (delegated to logic_path_tree)
# ---------------------------------------------------------------------------

def emit_markdown(
    tree_lines: list[str],
    leaves: list,
    unresolvable: list[tuple[str, int, str]],
    indirect: list[str],
) -> str:
    """Render the indented tree + leaf index + unresolvable + indirect sections."""
    from datetime import date

    today = date.today().isoformat()
    out: list[str] = []
    out.append("# Logic-path tree")
    out.append("")
    out.append(f"Generated by `audit/build_call_graph.py` on {today}.")
    out.append("")
    out.append(f"Entry: `{ENTRY_FN}()` in `{ENTRY_FILE.relative_to(REPO)}`.")
    out.append("")
    out.append(f"Total leaves: **{len(leaves)}**.")
    out.append("")
    out.append("Legend:")
    out.append("- Each `### L#N` section is one self-contained logic path, rooted at")
    out.append(f"  `{ENTRY_FN}()` and ending at its terminating statement.")
    out.append("- `-> L#N [completion] expr` - leaf marker (one test obligation each)")
    out.append("- completions: `return` / `raise` / `sys_exit` / `normal_fallthrough` / `seen_recursion` / `depth_limit`")
    out.append("- `[blocking subproc]` - `subprocess.run` / `check_output` / etc.")
    out.append("- `[FaF subproc]` - `subprocess.Popen` (parent does not wait)")
    out.append("- `(seen: fn)` - recursion guard")
    out.append("")
    out.append("---")
    out.append("")

    # Per-leaf trees: one complete dispatch_main() -> terminus rendering per leaf.
    out.append("## Per-leaf trees")
    out.append("")
    from logic_path_tree import render_per_leaf_trees
    out.extend(render_per_leaf_trees(leaves))

    out.append("## Leaf index")
    out.append("")
    for leaf in leaves:
        out.append(f"### L#{leaf.leaf_id}  [{leaf.completion}]")
        out.append("")
        stack_repr = " -> ".join(
            f"`{f.fn_name}` ({f.file}:{f.line})" for f in leaf.call_stack
        )
        out.append(f"- call_stack: {stack_repr}")
        if leaf.branch_path:
            out.append("- branch_path:")
            for cond in leaf.branch_path:
                out.append(f"  - {cond}")
        else:
            out.append("- branch_path: _(none)_")
        if leaf.return_expr is not None:
            out.append(f"- return: `{leaf.return_expr}`")
        else:
            out.append("- return: _(no expression)_")
        out.append(f"- source: `{leaf.file}:{leaf.line}`")
        out.append("")

    out.append("## Unresolvable subprocess invocations")
    out.append("")
    if not unresolvable:
        out.append("_(none)_")
    else:
        for f, lineno, src in unresolvable:
            out.append(f"- `{f}:{lineno}`  `{src}`")
    out.append("")

    out.append("## Indirect dispatch (manual review)")
    out.append("")
    if not indirect:
        out.append("_(none)_")
    else:
        for note in indirect:
            out.append(f"- {note}")
    out.append("")
    return "\n".join(out)


def emit_json(
    leaves: list,
    unresolvable: list[tuple[str, int, str]],
    indirect: list[str],
) -> str:
    """Machine-readable sidecar (consumed by future test-coverage tools)."""
    import json
    from dataclasses import asdict

    data = {
        "leaves": [asdict(leaf) for leaf in leaves],
        "unresolvable": [
            {"file": f, "line": lineno, "source": src} for (f, lineno, src) in unresolvable
        ],
        "indirect": list(indirect),
    }
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    pass1_index()

    entry_tree = file_ast.get(ENTRY_FILE)
    if entry_tree is None:
        sys.stderr.write(f"ERROR: entry file not parsed: {ENTRY_FILE}\n")
        return 1

    entry_node: ast.FunctionDef | None = None
    for node in entry_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == ENTRY_FN:
            entry_node = node
            break
    if entry_node is None:
        sys.stderr.write(f"ERROR: {ENTRY_FN} not found in {ENTRY_FILE}\n")
        return 1

    # When run as __main__, this module is registered under that name only.
    # logic_path_tree lazy-imports `build_call_graph` and would otherwise see
    # a freshly-loaded copy with empty indices. Alias so the lazy import
    # binds to this populated instance.
    sys.path.insert(0, str(Path(__file__).parent))
    sys.modules.setdefault("build_call_graph", sys.modules[__name__])
    import logic_path_tree as lpt

    tree_lines, leaves, unresolvable, indirect = lpt.build_tree(ENTRY_FILE, entry_node)

    md = emit_markdown(tree_lines, leaves, unresolvable, indirect)
    js = emit_json(leaves, unresolvable, indirect)

    md_path = REPO / "docs" / "design" / "call_graph.md"
    json_path = REPO / "docs" / "design" / "call_graph.json"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(js, encoding="utf-8")

    sys.stderr.write(
        f"wrote {md_path.relative_to(REPO)} ({len(tree_lines)} tree lines, {len(leaves)} leaves)\n"
    )
    sys.stderr.write(f"wrote {json_path.relative_to(REPO)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())


