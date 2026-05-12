"""Unit tests for audit/logic_path_tree.py.

Each test writes a minimal Python source file into tmp_path, repoints
build_call_graph at it via direct global mutation, runs Pass 1, then asks
logic_path_tree.build_tree to walk from a named entry function. Assertions
are made on the returned leaf set.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Make audit/ importable. The repo root is two levels up from this test file
# (tests/test_logic_path_tree.py -> tests -> repo root).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "audit"))

import build_call_graph as bcg  # noqa: E402
import logic_path_tree as lpt  # noqa: E402


def _reset_indexer_state() -> None:
    """Clear build_call_graph's module-level indices between tests."""
    bcg.defined_names.clear()
    bcg.imports_by_file.clear()
    bcg.dispatch_tables.clear()
    bcg.filename_fullpath_map.clear()
    bcg.file_ast.clear()
    bcg.subprocess_aliases.clear()


def _index_and_walk(
    tmp_path: Path,
    source: str,
    entry_fn_name: str = "foo",
    entry_filename: str = "mod.py",
):
    """Write `source` to tmp_path/<entry_filename>, point build_call_graph at
    it, run Pass 1, then walk from `entry_fn_name`. Returns
    (tree_lines, leaves, unresolvable, indirect)."""
    entry_file = tmp_path / entry_filename
    entry_file.write_text(source, encoding="utf-8")

    _reset_indexer_state()
    # Repoint build_call_graph at the tmp tree.
    bcg.REPO = tmp_path
    bcg.ROOTS = [tmp_path]
    bcg.ENTRY_FILE = entry_file
    bcg.ENTRY_FN = entry_fn_name

    bcg.pass1_index()

    tree = bcg.file_ast[entry_file]
    entry_node = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == entry_fn_name:
            entry_node = node
            break
    assert entry_node is not None, f"{entry_fn_name} not defined in test source"

    return lpt.build_tree(entry_file, entry_node)


def test_single_return_function_produces_one_return_leaf(tmp_path: Path):
    # Scenario: a function whose body is exactly `return 0` should produce
    # exactly one leaf with completion=RETURN and return_expr='0'. No
    # branch_path entries (the return is unconditional).
    # Setup: a trivial single-return function.
    src = "def foo():\n    return 0\n"
    # Test action: index and walk.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: exactly one leaf, RETURN '0', empty branch_path.
    assert len(leaves) == 1
    assert leaves[0].completion == "return"
    assert leaves[0].return_expr == "0"
    assert leaves[0].branch_path == []


def test_passthrough_loop_does_not_fork_the_path(tmp_path: Path):
    # Scenario: `for _ in range(3): pass` followed by `return 1`. The loop is
    # pass-through (body has no Return/Raise/sys.exit), so it must NOT
    # contribute a per-iteration fork to the final leaf's branch_path. The
    # leaf for `return 1` must therefore have an empty branch_path.
    # Setup: pass-through loop preceding a single return.
    src = (
        "def foo():\n"
        "    for _ in range(3):\n"
        "        pass\n"
        "    return 1\n"
    )
    # Test action: index and walk.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: the RETURN '1' leaf exists with empty branch_path.
    return_leaves = [l for l in leaves if l.return_expr == "1"]
    assert len(return_leaves) == 1
    assert return_leaves[0].branch_path == []


def test_terminating_generic_loop_emits_both_branch_and_fallthrough_leaves(tmp_path: Path):
    # Scenario: a generic terminating loop (`for _ in range(3): if cond:
    # return 0`) followed by `return 1` must produce both a `return 0` leaf
    # (cond=True branch inside the loop) and a `return 1` fallthrough leaf
    # (loop exhausted without cond being True).
    # Setup: a loop with an in-body conditional return and a post-loop return.
    src = (
        "def foo(cond):\n"
        "    for _ in range(3):\n"
        "        if cond:\n"
        "            return 0\n"
        "    return 1\n"
    )
    # Test action: index and walk.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: both leaves present with the correct return values.
    return_exprs = [(l.completion, l.return_expr) for l in leaves]
    assert ("return", "0") in return_exprs
    assert ("return", "1") in return_exprs


def test_terminating_dispatch_loop_emits_one_branch_per_dispatch_entry(tmp_path: Path):
    # Scenario: when a function iterates a recognized dispatch table
    # (_DISPATCH), each static entry must contribute a distinct path with the
    # entry's key in the branch_path. A fallthrough leaf for the no-match case
    # must also appear.
    # Setup: literal _DISPATCH with two lambda entries and a fn that iterates.
    src = (
        "def fnA():\n    return 1\n"
        "def fnB():\n    return 2\n"
        "_DISPATCH = {'a': lambda: fnA(), 'b': lambda: fnB()}\n"
        "def foo(key):\n"
        "    for k, f in _DISPATCH.items():\n"
        "        if k == key:\n"
        "            return f()\n"
        "    return 0\n"
    )
    # Test action: index and walk from foo.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: a branch_path entry referencing each dispatch key,
    # plus a fallthrough leaf with return_expr '0'.
    matched_keys = {
        cond
        for leaf in leaves
        for cond in leaf.branch_path
        if "matched key=" in cond
    }
    assert any("'a'" in c for c in matched_keys), f"missing 'a' in {matched_keys}"
    assert any("'b'" in c for c in matched_keys), f"missing 'b' in {matched_keys}"
    assert any(l.return_expr == "0" for l in leaves), "missing fallthrough leaf"


def test_recursive_self_call_emits_seen_recursion_leaf(tmp_path: Path):
    # Scenario: a function that recursively calls itself must produce a
    # SEEN_RECURSION leaf when the second call is encountered, rather than
    # expanding indefinitely.
    # Setup: a simple recursive function.
    src = (
        "def foo(n):\n"
        "    if n <= 0:\n"
        "        return 0\n"
        "    return foo(n - 1)\n"
    )
    # Test action: index and walk from foo.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: at least one leaf has completion=SEEN_RECURSION.
    completions = [l.completion for l in leaves]
    assert "seen_recursion" in completions


def test_return_non_literal_expression_renders_unparsed_source(tmp_path: Path):
    # Scenario: a return statement whose value is a non-literal expression
    # (e.g. `return a + b`) must produce a leaf whose return_expr is the
    # unparsed source of that expression.
    # Setup: a function returning a BinOp.
    src = "def foo(a, b):\n    return a + b\n"
    # Test action: index and walk.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: exactly one leaf, return_expr is 'a + b'.
    assert len(leaves) == 1
    assert leaves[0].return_expr == "a + b"


def test_raise_statement_emits_raise_leaf_with_exc_expression(tmp_path: Path):
    # Scenario: an unconditional `raise ValueError("x")` must produce a leaf
    # with completion=RAISE and return_expr containing the unparsed exception
    # expression.
    # Setup: a function that raises.
    src = "def foo():\n    raise ValueError('x')\n"
    # Test action: index and walk.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: one RAISE leaf, return_expr quotes the exc.
    assert len(leaves) == 1
    assert leaves[0].completion == "raise"
    assert "ValueError" in (leaves[0].return_expr or "")


def test_sys_exit_call_emits_sys_exit_leaf(tmp_path: Path):
    # Scenario: a bare `sys.exit(2)` statement must produce a leaf with
    # completion=SYS_EXIT.
    # Setup: a function that calls sys.exit unconditionally.
    src = "import sys\n\ndef foo():\n    sys.exit(2)\n"
    # Test action: index and walk.
    _, leaves, _, _ = _index_and_walk(tmp_path, src)
    # Test verification: one SYS_EXIT leaf.
    completions = [l.completion for l in leaves]
    assert "sys_exit" in completions
