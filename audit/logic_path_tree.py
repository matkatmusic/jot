#!/usr/bin/env python3
"""Logic-path tree builder.

Walks the entry function depth-first, recursing through every in-repo callee
and subprocess. Emits one Leaf per terminus encountered anywhere in the call
tree (return / raise / sys.exit / fallthrough / seen-recursion / depth-limit).

Reuses Pass 1 indexer state from build_call_graph (defined_names,
imports_by_file, dispatch_tables, filename_fullpath_map, file_ast,
subprocess_aliases) and its resolver helpers (_resolve_call,
_resolve_local_name).

Spec: ~/.claude/plans/open-point-1-calls-delegated-starlight.md
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class Completion(Enum):
    RETURN = "return"
    RAISE = "raise"
    SYS_EXIT = "sys_exit"
    NORMAL_FALLTHROUGH = "normal_fallthrough"
    SEEN_RECURSION = "seen_recursion"
    DEPTH_LIMIT = "depth_limit"


@dataclass
class CallFrame:
    """Public, JSON-friendly call-stack frame (paths as relative strings)."""
    file: str
    fn_name: str
    line: int


@dataclass
class Leaf:
    leaf_id: int
    call_stack: list[CallFrame]
    branch_path: list[str]
    completion: str
    return_expr: Optional[str]
    file: str
    line: int


@dataclass
class _Frame:
    """Internal call-stack frame holding a Path (so we can compute relpaths)."""
    file: Path
    fn_name: str
    line: int


# Module-level collectors. Reset by build_tree().
_leaves: list[Leaf] = []
_tree_lines: list[str] = []
_unresolvable: list[tuple[str, int, str]] = []
_indirect: list[str] = []

MAX_DEPTH = 20
INDENT = "  "

# Lazy import of build_call_graph (sibling module). Avoids circular import.
_BCG = None


def _bcg():
    global _BCG
    if _BCG is None:
        import build_call_graph as bcg
        _BCG = bcg
    return _BCG


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(_bcg().REPO))
    except ValueError:
        return str(p)


def _emit_tree(depth: int, text: str) -> None:
    _tree_lines.append(INDENT * depth + text)


def _emit_leaf(
    call_stack: list[_Frame],
    branch_path: list[str],
    completion: Completion,
    return_expr: Optional[str],
    file: Path,
    line: int,
    depth: int,
) -> None:
    leaf_id = len(_leaves) + 1
    _leaves.append(
        Leaf(
            leaf_id=leaf_id,
            call_stack=[CallFrame(_rel(f.file), f.fn_name, f.line) for f in call_stack],
            branch_path=list(branch_path),
            completion=completion.value,
            return_expr=return_expr,
            file=_rel(file),
            line=line,
        )
    )
    expr_part = f" {return_expr}" if return_expr is not None else ""
    _emit_tree(depth, f"-> L#{leaf_id} [{completion.value}]{expr_part}  ({_rel(file)}:{line})")


def _is_sys_exit_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        if f.value.id == "sys" and f.attr == "exit":
            return True
        if f.value.id == "os" and f.attr == "_exit":
            return True
    if isinstance(f, ast.Name) and f.id in ("exit", "quit"):
        return True
    return False


def _has_function_terminator(stmts: list[ast.stmt]) -> bool:
    """True iff any stmt can terminate the enclosing function (Return / Raise
    / sys.exit / os._exit). Recurses through compound statements but NOT
    through nested function / class definitions (their bodies belong to
    different functions)."""
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(stmt, (ast.Return, ast.Raise)):
            return True
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and _is_sys_exit_call(stmt.value)
        ):
            return True
        for attr in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, attr, None)
            if isinstance(inner, list) and _has_function_terminator(inner):
                return True
        if isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                if _has_function_terminator(handler.body):
                    return True
    return False


def _calls_in_expr(expr: ast.AST) -> list[ast.Call]:
    """Every Call node inside an expression tree, source order."""
    out: list[ast.Call] = []
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Call):
            out.append(sub)
    return out


def _calls_in_simple_stmt(stmt: ast.stmt) -> list[ast.Call]:
    """Calls inside a non-compound statement. Compound statements (If/Try/
    For/While/With/Match) are handled by walk_block directly."""
    if isinstance(
        stmt,
        (
            ast.If,
            ast.Try,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.With,
            ast.AsyncWith,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Match,
        ),
    ):
        return []
    return _calls_in_expr(stmt)


def _dispatch_table_for_iter(iter_node: ast.AST) -> Optional[str]:
    """Return the dispatch-table variable name if `iter_node` iterates one;
    handles `TABLE`, `sorted(TABLE, ...)`, `TABLE.items()`, etc."""
    table_names = _bcg().DISPATCH_TABLE_NAMES
    if isinstance(iter_node, ast.Name) and iter_node.id in table_names:
        return iter_node.id
    if isinstance(iter_node, ast.Call):
        # sorted(TABLE, ...) / reversed(TABLE, ...) / list(TABLE)
        fn_name: Optional[str] = None
        f = iter_node.func
        if isinstance(f, ast.Name):
            fn_name = f.id
        elif isinstance(f, ast.Attribute):
            fn_name = f.attr
        if fn_name in ("sorted", "reversed", "list", "iter") and iter_node.args:
            inner = iter_node.args[0]
            if isinstance(inner, ast.Name) and inner.id in table_names:
                return inner.id
        # TABLE.items() / TABLE.values() / TABLE.keys()
        if isinstance(f, ast.Attribute):
            base = f.value
            if isinstance(base, ast.Name) and base.id in table_names:
                return base.id
    return None


def walk_function(
    file: Path,
    fn: ast.FunctionDef,
    branch_path: list[str],
    call_stack: list[_Frame],
    seen: frozenset[str],
    depth: int,
) -> None:
    """Walk one function. Emits a tree header, then leaves for every terminus
    in fn.body, including an implicit fallthrough leaf if control reaches the
    end of the body."""
    fn_id = f"{file}::{fn.name}"
    if fn_id in seen:
        _emit_tree(depth, f"(seen: {fn.name})")
        _emit_leaf(call_stack, branch_path, Completion.SEEN_RECURSION, None, file, fn.lineno, depth)
        return
    if depth >= MAX_DEPTH:
        _emit_tree(depth, f"(depth limit {MAX_DEPTH} at {fn.name})")
        _emit_leaf(call_stack, branch_path, Completion.DEPTH_LIMIT, None, file, fn.lineno, depth)
        return

    new_seen = seen | {fn_id}
    new_stack = call_stack + [_Frame(file=file, fn_name=fn.name, line=fn.lineno)]

    _emit_tree(depth, f"{fn.name}()  [{_rel(file)}:{fn.lineno}]")
    fellthrough = walk_block(file, fn.body, branch_path, new_stack, new_seen, depth + 1)
    if fellthrough:
        last_line = fn.body[-1].lineno if fn.body else fn.lineno
        _emit_leaf(new_stack, branch_path, Completion.NORMAL_FALLTHROUGH, None, file, last_line, depth + 1)


def walk_block(
    file: Path,
    stmts: list[ast.stmt],
    branch_path: list[str],
    call_stack: list[_Frame],
    seen: frozenset[str],
    depth: int,
) -> bool:
    """Walk a list of statements. Returns True if control falls through to the
    end of `stmts`; False if every reachable path terminated (e.g. unconditional
    return in both branches of an `if`/`else`)."""
    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            # Walk calls inside the return expression first: catches recursion,
            # records subprocess invocations, lets unhandled raises propagate.
            if stmt.value is not None:
                for c in _calls_in_expr(stmt.value):
                    _handle_call(file, c, branch_path, call_stack, seen, depth)
            expr = ast.unparse(stmt.value) if stmt.value is not None else None
            _emit_leaf(call_stack, branch_path, Completion.RETURN, expr, file, stmt.lineno, depth)
            return False

        if isinstance(stmt, ast.Raise):
            if stmt.exc is not None:
                for c in _calls_in_expr(stmt.exc):
                    _handle_call(file, c, branch_path, call_stack, seen, depth)
            expr = ast.unparse(stmt.exc) if stmt.exc is not None else "(re-raise)"
            _emit_leaf(call_stack, branch_path, Completion.RAISE, expr, file, stmt.lineno, depth)
            return False

        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and _is_sys_exit_call(stmt.value)
        ):
            expr = ast.unparse(stmt.value)
            _emit_leaf(call_stack, branch_path, Completion.SYS_EXIT, expr, file, stmt.lineno, depth)
            return False

        if isinstance(stmt, ast.If):
            # Walk calls in the test expression first (predicates are real calls).
            for c in _calls_in_expr(stmt.test):
                _handle_call(file, c, branch_path, call_stack, seen, depth)
            test_repr = ast.unparse(stmt.test)
            then_label = f"if {test_repr}:"
            _emit_tree(depth, then_label)
            then_ft = walk_block(
                file, stmt.body, branch_path + [then_label], call_stack, seen, depth + 1
            )

            if stmt.orelse:
                # `elif` is a single nested If in orelse — flatten so it
                # renders as a sibling branch at the same indent.
                if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                    else_ft = walk_block(
                        file, stmt.orelse, branch_path, call_stack, seen, depth
                    )
                else:
                    else_label = f"else: (of {test_repr})"
                    _emit_tree(depth, else_label)
                    else_ft = walk_block(
                        file,
                        stmt.orelse,
                        branch_path + [else_label],
                        call_stack,
                        seen,
                        depth + 1,
                    )
            else:
                else_ft = True  # implicit else: control just continues

            if not then_ft and not else_ft:
                return False
            continue

        if isinstance(stmt, ast.Try):
            _emit_tree(depth, "try:")
            try_ft = walk_block(
                file, stmt.body, branch_path + ["try:"], call_stack, seen, depth + 1
            )
            any_handler_ft = False
            for handler in stmt.handlers:
                exc_name = ast.unparse(handler.type) if handler.type else "Exception"
                eh_label = f"except {exc_name}:"
                _emit_tree(depth, eh_label)
                h_ft = walk_block(
                    file, handler.body, branch_path + [eh_label], call_stack, seen, depth + 1
                )
                if h_ft:
                    any_handler_ft = True
            if stmt.orelse:
                _emit_tree(depth, "else: (try-else)")
                walk_block(
                    file,
                    stmt.orelse,
                    branch_path + ["try-else:"],
                    call_stack,
                    seen,
                    depth + 1,
                )
            if stmt.finalbody:
                _emit_tree(depth, "finally:")
                walk_block(
                    file,
                    stmt.finalbody,
                    branch_path + ["finally:"],
                    call_stack,
                    seen,
                    depth + 1,
                )
            if not try_ft and not any_handler_ft:
                return False
            continue

        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            for c in _calls_in_expr(stmt.iter):
                _handle_call(file, c, branch_path, call_stack, seen, depth)
            iter_repr = ast.unparse(stmt.iter)
            target_repr = ast.unparse(stmt.target)
            loop_label = f"for {target_repr} in {iter_repr}:"
            _emit_tree(depth, loop_label)

            terminating = _has_function_terminator(stmt.body)
            dispatch_var = _dispatch_table_for_iter(stmt.iter)

            if not terminating:
                # Pass-through: walk body once for any in-body calls/decisions
                # but do not enqueue per-iteration paths.
                _emit_tree(depth + 1, "(pass-through loop)")
                walk_block(
                    file,
                    stmt.body,
                    branch_path + [loop_label + " (pass-through)"],
                    call_stack,
                    seen,
                    depth + 1,
                )
                continue

            if dispatch_var is not None:
                entries = _bcg().dispatch_tables.get((file, dispatch_var), [])
                for key, target_name, _call in entries:
                    entry_label = f"{loop_label} matched key={key} -> {target_name}()"
                    _emit_tree(depth + 1, entry_label)
                    walk_block(
                        file,
                        stmt.body,
                        branch_path + [entry_label],
                        call_stack,
                        seen,
                        depth + 2,
                    )
                _emit_tree(depth + 1, f"{loop_label} (loop exhausted, no match)")
                continue

            # Generic terminating loop: walk body once with branches enqueued.
            walk_block(
                file,
                stmt.body,
                branch_path + [loop_label + " body:"],
                call_stack,
                seen,
                depth + 1,
            )
            _emit_tree(depth + 1, f"{loop_label} (loop exhausted)")
            continue

        if isinstance(stmt, ast.While):
            for c in _calls_in_expr(stmt.test):
                _handle_call(file, c, branch_path, call_stack, seen, depth)
            test_repr = ast.unparse(stmt.test)
            loop_label = f"while {test_repr}:"
            _emit_tree(depth, loop_label)
            terminating = _has_function_terminator(stmt.body)
            if not terminating:
                _emit_tree(depth + 1, "(pass-through loop)")
                walk_block(
                    file,
                    stmt.body,
                    branch_path + [loop_label + " (pass-through)"],
                    call_stack,
                    seen,
                    depth + 1,
                )
            else:
                walk_block(
                    file,
                    stmt.body,
                    branch_path + [loop_label + " body:"],
                    call_stack,
                    seen,
                    depth + 1,
                )
                _emit_tree(depth + 1, f"{loop_label} (loop exhausted)")
            continue

        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                for c in _calls_in_expr(item.context_expr):
                    _handle_call(file, c, branch_path, call_stack, seen, depth)
            inner_ft = walk_block(file, stmt.body, branch_path, call_stack, seen, depth)
            if not inner_ft:
                return False
            continue

        # Default: simple statement — walk every Call it contains.
        for c in _calls_in_simple_stmt(stmt):
            _handle_call(file, c, branch_path, call_stack, seen, depth)

    return True


def _handle_call(
    file: Path,
    call: ast.Call,
    branch_path: list[str],
    call_stack: list[_Frame],
    seen: frozenset[str],
    depth: int,
) -> None:
    """Resolve a Call and recurse, rendering subprocess / dispatch fan-out / unresolved."""
    bcg = _bcg()
    res = bcg._resolve_call(file, call)
    if res is None:
        return

    if res.kind == "in_repo":
        assert res.target_file is not None and res.target_node is not None
        _emit_tree(depth, f"call: {res.label}")
        walk_function(
            res.target_file,
            res.target_node,
            branch_path + [f"call {res.label}"],
            call_stack,
            seen,
            depth + 1,
        )
        return

    if res.kind == "subproc":
        if res.py_target is not None:
            label = f"{_rel(res.py_target)}::main() {res.tag}"
            _emit_tree(depth, f"subproc: {label}")
            _expand_py_subproc(
                res.py_target,
                res.py_argv,
                branch_path + [f"subproc {label}"],
                call_stack,
                seen,
                depth + 1,
            )
        else:
            _emit_tree(depth, f"subproc: {res.label} {res.tag}")
        return

    if res.kind == "unresolved":
        lineno = getattr(call, "lineno", 0)
        _unresolvable.append((_rel(file), lineno, res.src_line))
        _emit_tree(depth, f"{res.tag} <unresolved argv>  ({_rel(file)}:{lineno})")
        return

    if res.kind == "dispatch_table":
        table_name = res.label
        entries = bcg.dispatch_tables.get((file, table_name), [])
        if not entries:
            # Look up the table in any file (some scripts reference tables defined elsewhere).
            for (fpath, tn), ents in bcg.dispatch_tables.items():
                if tn == table_name:
                    entries = ents
                    break
        _emit_tree(depth, f"via {table_name}:")
        for key, target_name, _call in entries:
            resolved = bcg._resolve_local_name(file, target_name)
            if resolved is None:
                _indirect.append(
                    f"{_rel(file)}: {table_name}[{key}] -> {target_name}() not found in defined_names"
                )
                continue
            tgt_file, tgt_node = resolved
            _emit_tree(depth + 1, f"{table_name}[{key}] -> {target_name}()")
            walk_function(
                tgt_file,
                tgt_node,
                branch_path + [f"{table_name}[{key}]={target_name}"],
                call_stack,
                seen,
                depth + 2,
            )
        return


def _expand_py_subproc(
    py_target: Path,
    argv: list[str],
    branch_path: list[str],
    call_stack: list[_Frame],
    seen: frozenset[str],
    depth: int,
) -> None:
    """Expand a subprocess-launched .py target. Handles orchestrator argv re-entry,
    target's own _DISPATCH table, and fallback to target's main()."""
    bcg = _bcg()

    if py_target == bcg.ENTRY_FILE and argv:
        key = argv[0].strip().strip("'\"")
        entries = bcg.dispatch_tables.get((bcg.ENTRY_FILE, "_ARGV_DISPATCH"), [])
        for k_repr, target_name, _call in entries:
            if k_repr.strip("'\"") == key:
                resolved = bcg._resolve_local_name(bcg.ENTRY_FILE, target_name)
                if resolved is not None:
                    tgt_file, tgt_node = resolved
                    _emit_tree(depth, f"orchestrator argv {key!r} -> {target_name}()")
                    walk_function(
                        tgt_file,
                        tgt_node,
                        branch_path + [f"orchestrator argv={key}"],
                        call_stack,
                        seen,
                        depth + 1,
                    )
                    return

    for (fpath, var_name), entries in bcg.dispatch_tables.items():
        if fpath != py_target or var_name != "_DISPATCH":
            continue
        if not argv:
            break
        key = argv[0].strip().strip("'\"")
        for k_repr, target_name, _call in entries:
            if k_repr.strip("'\"") == key:
                resolved = bcg._resolve_local_name(py_target, target_name)
                if resolved is not None:
                    tgt_file, tgt_node = resolved
                    _emit_tree(depth, f"{py_target.name} argv {key!r} -> {target_name}()")
                    walk_function(
                        tgt_file,
                        tgt_node,
                        branch_path + [f"{py_target.name} argv={key}"],
                        call_stack,
                        seen,
                        depth + 1,
                    )
                    return
        break

    for fpath, node in bcg.defined_names.get("main", []):
        if fpath == py_target:
            _emit_tree(depth, "main()")
            walk_function(
                fpath,
                node,
                branch_path + [f"{py_target.name}::main()"],
                call_stack,
                seen,
                depth + 1,
            )
            return

    _emit_tree(depth, "(no resolvable entry function in target)")


def build_tree(
    entry_file: Path, entry_fn: ast.FunctionDef
) -> tuple[list[str], list[Leaf], list[tuple[str, int, str]], list[str]]:
    """Reset collectors, walk from the entry function, return all output."""
    _leaves.clear()
    _tree_lines.clear()
    _unresolvable.clear()
    _indirect.clear()
    walk_function(entry_file, entry_fn, [], [], frozenset(), 0)
    return list(_tree_lines), list(_leaves), list(_unresolvable), list(_indirect)


# ---------------------------------------------------------------------------
# Per-leaf tree renderer
# ---------------------------------------------------------------------------
#
# Post-processes Leaf records into one self-contained tree per terminus,
# rooted at the entry function and ending at the leaf's terminating
# statement. Replaces the older shared `## Tree` section in the markdown
# output. Pure function of Leaf records — no walker state required.

_RE_DISPATCH_TBL = re.compile(r"^(_[A-Z_]+)\[(.+)\]=(.+)$")
_RE_FOR_LOOP = re.compile(
    r"^(for .+? in .+?):( matched key=.+| body:| \(pass-through\))$"
)
_RE_WHILE_LOOP = re.compile(r"^(while .+?):( body:| \(pass-through\))$")
_RE_PY_ARGV = re.compile(r"^(\S+\.py) argv=(.+)$")
_RE_PY_MAIN = re.compile(r"^(\S+\.py)::main\(\)$")
_RE_CALL = re.compile(r"^call (.+)$")
_RE_SUBPROC = re.compile(r"^subproc (.+)$")
_RE_ORCH_ARGV = re.compile(r"^orchestrator argv=(.+)$")


def _fn_header(frame: CallFrame) -> str:
    return f"{frame.fn_name}()  [{frame.file}:{frame.line}]"


def _render_one_leaf(leaf: Leaf) -> list[str]:
    """Render one leaf as a vertical sequence of indented tree lines.

    The first line is the entry-function header at depth 0; the last line
    is the leaf-marker at the path's final depth. Frame entries from
    `leaf.call_stack` are interleaved with decision labels from
    `leaf.branch_path` in source order.
    """
    out: list[str] = []
    frames = leaf.call_stack
    fidx = 1  # frames[0] is the entry; subsequent frames consumed by pop entries

    def emit(d: int, text: str) -> None:
        out.append(INDENT * d + text)

    emit(0, _fn_header(frames[0]))
    cur = 1  # depth at which the next branch_path entry sits

    for entry in leaf.branch_path:
        m = _RE_CALL.match(entry)
        if m:
            emit(cur, f"call: {m.group(1)}")
            emit(cur + 1, _fn_header(frames[fidx]))
            fidx += 1
            cur += 2
            continue

        m = _RE_DISPATCH_TBL.match(entry)
        if m:
            table, key, target = m.group(1), m.group(2), m.group(3)
            emit(cur, f"via {table}:")
            emit(cur + 1, f"{table}[{key}] -> {target}()")
            emit(cur + 2, _fn_header(frames[fidx]))
            fidx += 1
            cur += 3
            continue

        m = _RE_ORCH_ARGV.match(entry)
        if m:
            key = m.group(1)
            tgt = frames[fidx].fn_name
            emit(cur, f"orchestrator argv {key!r} -> {tgt}()")
            emit(cur + 1, _fn_header(frames[fidx]))
            fidx += 1
            cur += 2
            continue

        m = _RE_PY_ARGV.match(entry)
        if m:
            pyfile, key = m.group(1), m.group(2)
            tgt = frames[fidx].fn_name
            emit(cur, f"{pyfile} argv {key!r} -> {tgt}()")
            emit(cur + 1, _fn_header(frames[fidx]))
            fidx += 1
            cur += 2
            continue

        m = _RE_PY_MAIN.match(entry)
        if m:
            emit(cur, "main()")
            emit(cur + 1, _fn_header(frames[fidx]))
            fidx += 1
            cur += 2
            continue

        m = _RE_SUBPROC.match(entry)
        if m:
            emit(cur, f"subproc: {m.group(1)}")
            cur += 1
            continue

        m = _RE_FOR_LOOP.match(entry)
        if m:
            head, suffix = m.group(1) + ":", m.group(2)
            if suffix == " body:":
                emit(cur, head)
                cur += 1
            elif suffix == " (pass-through)":
                emit(cur, head)
                emit(cur + 1, "(pass-through loop)")
                cur += 2
            else:  # " matched key=... -> ...()"
                emit(cur, head)
                emit(cur + 1, head + suffix)
                cur += 2
            continue

        m = _RE_WHILE_LOOP.match(entry)
        if m:
            head, suffix = m.group(1) + ":", m.group(2)
            if suffix == " body:":
                emit(cur, head)
                cur += 1
            else:  # " (pass-through)"
                emit(cur, head)
                emit(cur + 1, "(pass-through loop)")
                cur += 2
            continue

        # Default: if/elif/else/try/except/try-else/finally and similar —
        # already complete syntax, emit verbatim.
        emit(cur, entry)
        cur += 1

    expr_part = f" {leaf.return_expr}" if leaf.return_expr is not None else ""
    emit(
        cur,
        f"-> L#{leaf.leaf_id} [{leaf.completion}]{expr_part}  "
        f"({leaf.file}:{leaf.line})",
    )
    return out


def render_per_leaf_trees(leaves: list[Leaf]) -> list[str]:
    """Return markdown lines: one ## L#N section per leaf, each wrapping
    a fenced code block containing that leaf's complete tree."""
    out: list[str] = []
    for leaf in leaves:
        expr_part = f" {leaf.return_expr}" if leaf.return_expr is not None else ""
        out.append(f"### L#{leaf.leaf_id}  [{leaf.completion}]{expr_part}")
        out.append("")
        out.append("```")
        out.extend(_render_one_leaf(leaf))
        out.append("```")
        out.append("")
    return out
