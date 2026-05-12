"""
Audit a Python module for bare function-call identifiers that are neither
defined locally nor imported. Such identifiers are latent NameError bugs
inherited from the bash port (where helpers were called via the bash
function namespace with no explicit declaration).

Strategy:
  1. Parse the module AST.
  2. Collect all locally-defined names (def, class, assignments, params).
  3. Collect all imported names (from ... import X, import X, import X as Y).
  4. Walk Call nodes; for each Call whose .func is a bare Name, check whether
     that Name is in (locals | imports | builtins). If not, report it with
     the source line.
"""

import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) | {
    # Module-level dunders Python injects into every module's namespace.
    "__file__", "__name__", "__doc__", "__package__", "__loader__",
    "__spec__", "__builtins__", "__cached__", "__path__", "__all__",
}


SEARCH_ROOTS = [
    Path("/Users/matkatmusicllc/Programming/jot/common/scripts"),
    Path("/Users/matkatmusicllc/Programming/jot/common/scripts/plate"),
    Path("/Users/matkatmusicllc/Programming/jot/common/scripts/jot"),
]


def resolve_module(modname: str) -> Path | None:
    """Resolve a dotted module name to a file path under SEARCH_ROOTS."""
    parts = modname.split(".")
    leaf = parts[-1]
    candidates = []
    for root in SEARCH_ROOTS:
        candidates.append(root / f"{leaf}.py")
        candidates.append(root / Path(*parts) / "__init__.py")
        candidates.append(root.parent / Path(*parts).with_suffix(".py"))
        candidates.append(root.parent.parent / Path(*parts).with_suffix(".py"))
    for c in candidates:
        if c.exists():
            return c
    return None


def public_names_of(modpath: Path) -> set[str]:
    """Return the set of names a `from <modpath> import *` would expose."""
    try:
        src = modpath.read_text()
        tree = ast.parse(src)
    except Exception:
        return set()
    # Honor __all__ if defined as a literal list/tuple.
    for node in ast.iter_child_nodes(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            return {
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    # Otherwise: all top-level public names (no leading underscore).
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and not tgt.id.startswith("_"):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                n = alias.asname or alias.name
                if n != "*" and not n.startswith("_"):
                    names.add(n)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                n = alias.asname or alias.name.split(".")[0]
                if not n.startswith("_"):
                    names.add(n)
    return names


def collect_scopes(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return (defined_names, imported_names) at module scope.

    Imported names include those expanded from `from X import *` whenever X
    can be resolved to a file under SEARCH_ROOTS.
    """
    defined: set[str] = set()
    imported: set[str] = set()

    def absorb_import(node: ast.AST) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    target = resolve_module(module)
                    if target is not None:
                        imported.update(public_names_of(target))
                    continue
                imported.add(alias.asname or alias.name)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    defined.add(tgt.id)
                elif isinstance(tgt, ast.Tuple):
                    for elt in tgt.elts:
                        if isinstance(elt, ast.Name):
                            defined.add(elt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            absorb_import(node)
        elif isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    absorb_import(sub)
    return defined, imported


def _collect_target_names(target: ast.AST) -> set[str]:
    """Recursively collect Name.id from an assignment / for / with target,
    including arbitrarily nested tuples and starred unpacking."""
    out: set[str] = set()
    if isinstance(target, ast.Name):
        out.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            out |= _collect_target_names(elt)
    elif isinstance(target, ast.Starred):
        out |= _collect_target_names(target.value)
    return out


def _walk_scope_bindings(node: ast.AST, locals_: set[str]) -> None:
    """Walk children of a function/lambda/comprehension scope. Does NOT descend
    into nested function/lambda/comprehension bodies (those have their own scopes)."""
    for child in ast.iter_child_nodes(node):
        # Nested scopes — record the *binding name* if any, but don't recurse
        # into the nested body (its locals are private to it).
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            locals_.add(child.name)
            continue
        if isinstance(child, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            continue
        # Bindings in the current scope.
        if isinstance(child, ast.Assign):
            for tgt in child.targets:
                locals_ |= _collect_target_names(tgt)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            locals_.add(child.target.id)
        elif isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name):
            locals_.add(child.target.id)
        elif isinstance(child, (ast.For, ast.AsyncFor)):
            locals_ |= _collect_target_names(child.target)
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                if item.optional_vars:
                    locals_ |= _collect_target_names(item.optional_vars)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            locals_.add(child.name)
        elif isinstance(child, ast.ImportFrom):
            for alias in child.names:
                locals_.add(alias.asname or alias.name)
        elif isinstance(child, ast.Import):
            for alias in child.names:
                locals_.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(child, ast.NamedExpr) and isinstance(child.target, ast.Name):
            locals_.add(child.target.id)
        # Recurse into compound statements that don't open a new scope
        # (if/else/try/while/for-body/with-body).
        _walk_scope_bindings(child, locals_)


def walk_function_locals(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Local names introduced inside a function body (params, assignments, nested def/class).
    Does NOT include names that bind only inside nested function / lambda / comprehension scopes."""
    locals_: set[str] = set()
    for arg in (
        fn.args.args
        + fn.args.posonlyargs
        + fn.args.kwonlyargs
    ):
        locals_.add(arg.arg)
    if fn.args.vararg:
        locals_.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        locals_.add(fn.args.kwarg.arg)
    for stmt in fn.body:
        _walk_scope_bindings(stmt, locals_)
    return locals_


def _comprehension_locals(node: ast.GeneratorExp | ast.ListComp | ast.SetComp | ast.DictComp) -> set[str]:
    out: set[str] = set()
    for gen in node.generators:
        out |= _collect_target_names(gen.target)
    return out


def _lambda_locals(node: ast.Lambda) -> set[str]:
    out: set[str] = set()
    for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
        out.add(arg.arg)
    if node.args.vararg:
        out.add(node.args.vararg.arg)
    if node.args.kwarg:
        out.add(node.args.kwarg.arg)
    return out


def _collect_all_bindings(tree: ast.AST) -> set[str]:
    """Flat set of every name that gets bound anywhere in the file: module-level
    defs, function/method params, comprehension targets, lambda params, for/with
    targets, except handlers, walrus targets, nested functions, and class methods.
    Over-permissive on purpose — the goal is to *not* false-positive on legit
    locals, even at the cost of missing some intra-scope shadowing bugs."""
    bindings: set[str] = set()
    for sub in ast.walk(tree):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.add(sub.name)
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in sub.args.args + sub.args.posonlyargs + sub.args.kwonlyargs:
                    bindings.add(arg.arg)
                if sub.args.vararg:
                    bindings.add(sub.args.vararg.arg)
                if sub.args.kwarg:
                    bindings.add(sub.args.kwarg.arg)
        elif isinstance(sub, ast.Lambda):
            for arg in sub.args.args + sub.args.posonlyargs + sub.args.kwonlyargs:
                bindings.add(arg.arg)
            if sub.args.vararg:
                bindings.add(sub.args.vararg.arg)
            if sub.args.kwarg:
                bindings.add(sub.args.kwarg.arg)
        elif isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                bindings |= _collect_target_names(tgt)
        elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
            bindings.add(sub.target.id)
        elif isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name):
            bindings.add(sub.target.id)
        elif isinstance(sub, (ast.For, ast.AsyncFor)):
            bindings |= _collect_target_names(sub.target)
        elif isinstance(sub, (ast.With, ast.AsyncWith)):
            for item in sub.items:
                if item.optional_vars:
                    bindings |= _collect_target_names(item.optional_vars)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            bindings.add(sub.name)
        elif isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
            bindings.add(sub.target.id)
        elif isinstance(sub, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            for gen in sub.generators:
                bindings |= _collect_target_names(gen.target)
        elif isinstance(sub, ast.ImportFrom):
            for alias in sub.names:
                if alias.name == "*":
                    continue
                bindings.add(alias.asname or alias.name)
        elif isinstance(sub, ast.Import):
            for alias in sub.names:
                bindings.add(alias.asname or alias.name.split(".")[0])
    return bindings


def audit(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line, name, context) for suspect bare Name references.

    Strategy: build a single flat scope = (module defs + module imports +
    every name bound anywhere in the file + builtins). Walk every ast.Name
    in Load context; any id absent from that scope is a candidate bare ref.

    This intentionally over-includes local names so the audit cannot
    false-positive on comprehension/lambda/nested-function locals; the
    cost is missing rare intra-scope shadowing bugs, which are not the
    bash-port class of bug we're hunting."""
    src = path.read_text()
    tree = ast.parse(src, filename=str(path))
    _, mod_imports = collect_scopes(tree)
    all_bindings = _collect_all_bindings(tree)
    known = all_bindings | mod_imports | BUILTINS | {"self", "cls"}

    src_lines = src.splitlines()
    findings: list[tuple[int, str, str]] = []
    for sub in ast.walk(tree):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            if sub.id not in known:
                line = src_lines[sub.lineno - 1].strip() if 0 < sub.lineno <= len(src_lines) else ""
                findings.append((sub.lineno, sub.id, line))
    return findings


def main(targets: list[str]) -> int:
    total = 0
    for target in targets:
        path = Path(target)
        print(f"\n=== {path} ===")
        findings = audit(path)
        if not findings:
            print("  (clean)")
            continue
        # Deduplicate by (name, lineno)
        seen: set[tuple[int, str]] = set()
        for line, name, ctx in findings:
            key = (line, name)
            if key in seen:
                continue
            seen.add(key)
            print(f"  L{line}  {name:30s}  {ctx}")
            total += 1
    print(f"\nTotal suspect references: {total}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
