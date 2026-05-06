"""RED-first spec for scripts/jot-plugin-orchestrator.py migration.

Each test starts with a plain-English scenario, then exercises the module.
The hyphenated module name forbids `import` — load via importlib.

Sub-orchestrator stubs are written into a tmp_path-rooted fake plugin tree
that records each invocation's stdin so dispatch can be asserted without
running the real bash sub-orchestrators.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "jot_plugin_orchestrator.py"

SUBORCHESTRATORS = {
    "/jot":          "skills/jot/scripts/jot-orchestrator.sh",
    "/plate":        "skills/plate/scripts/plate-orchestrator.sh",
    "/debate":       "skills/debate/scripts/debate-orchestrator.sh",
    "/debate-retry": "skills/debate-retry/scripts/debate-retry-orchestrator.sh",
    "/debate-abort": "skills/debate-abort/scripts/debate-abort-orchestrator.sh",
    "/todo":         "skills/todo/scripts/todo-orchestrator.sh",
    "/todo-list":    "skills/todo-list/scripts/todo-list-orchestrator.sh",
}


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("jot_plugin_orchestrator", MODULE_PATH)
    assert spec and spec.loader, f"cannot load {MODULE_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def jpo() -> ModuleType:
    return _load_module()


@pytest.fixture
def fake_plugin_root(tmp_path: Path) -> Path:
    """Build tmp_path/skills/.../X-orchestrator.sh stubs.

    Each stub appends to <stub>.stdin in the same directory. Stubs honor
    a sentinel env var EXIT_CODE so propagation can be exercised.
    """
    for rel in SUBORCHESTRATORS.values():
        stub = tmp_path / rel
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(
            "#!/bin/bash\n"
            'cat > "${BASH_SOURCE[0]}.stdin"\n'
            'exit "${STUB_EXIT_CODE:-0}"\n'
        )
        stub.chmod(0o755)
    return tmp_path


def _read_stub_stdin(plugin_root: Path, prompt_key: str) -> str:
    rel = SUBORCHESTRATORS[prompt_key]
    return (plugin_root / f"{rel}.stdin").read_text()


def _run_main(
    jpo: ModuleType,
    plugin_root: Path,
    stdin: str,
    env: dict[str, str] | None = None,
) -> int:
    """Invoke main() with stdin redirected and CLAUDE_PLUGIN_ROOT set.

    main() is called as the entry-point would call it (no args).
    """
    import io
    saved_stdin = sys.stdin
    saved_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    sys.stdin = io.StringIO(stdin)
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    if env:
        for k, v in env.items():
            os.environ[k] = v
    try:
        return jpo.main()
    finally:
        sys.stdin = saved_stdin
        if saved_env is None:
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        else:
            os.environ["CLAUDE_PLUGIN_ROOT"] = saved_env
        if env:
            for k in env:
                os.environ.pop(k, None)


# ----- normalize_prompt unit tests ---------------------------------------


def test_normalize_empty_input_returns_empty_prompt(jpo: ModuleType) -> None:
    # Scenario: empty string input. Should return empty prompt, raw passes through.
    prompt, forwarded = jpo.normalize_prompt("")
    assert prompt == ""
    assert forwarded == ""


def test_normalize_malformed_json_treated_as_empty(jpo: ModuleType) -> None:
    # Scenario: stdin is not valid JSON. Should swallow error and return empty prompt.
    prompt, forwarded = jpo.normalize_prompt("not json{{{")
    assert prompt == ""
    assert forwarded == "not json{{{"


def test_normalize_missing_prompt_field(jpo: ModuleType) -> None:
    # Scenario: JSON object without `.prompt`.
    prompt, _ = jpo.normalize_prompt('{"other": 1}')
    assert prompt == ""


def test_normalize_null_prompt(jpo: ModuleType) -> None:
    # Scenario: explicit null prompt.
    prompt, _ = jpo.normalize_prompt('{"prompt": null}')
    assert prompt == ""


def test_normalize_strips_leading_whitespace(jpo: ModuleType) -> None:
    # Scenario: leading spaces and tabs preserved-by-bash should also be stripped here.
    prompt, _ = jpo.normalize_prompt('{"prompt": "  /plate --done"}')
    assert prompt == "/plate --done"


def test_normalize_rewrites_jot_colon_form(jpo: ModuleType) -> None:
    # Scenario: "/jot:todo-list" → "/todo-list" both in returned prompt and forwarded JSON.
    prompt, forwarded = jpo.normalize_prompt('{"prompt": "/jot:todo-list"}')
    assert prompt == "/todo-list"
    assert json.loads(forwarded)["prompt"] == "/todo-list"


def test_normalize_passes_non_colon_prompt_unchanged(jpo: ModuleType) -> None:
    # Scenario: ordinary prompt — JSON forwarded unchanged.
    raw = '{"prompt": "/jot foo"}'
    prompt, forwarded = jpo.normalize_prompt(raw)
    assert prompt == "/jot foo"
    assert forwarded == raw


# ----- route() unit tests ------------------------------------------------


@pytest.mark.parametrize("prompt,expected_key", [
    ("/jot",               "/jot"),
    ("/jot foo bar",       "/jot"),
    ("/jot\nmulti",        "/jot"),
    ("/plate",             "/plate"),
    ("/plate --done",      "/plate"),
    ("/debate topic",      "/debate"),
    ("/debate-retry",      "/debate-retry"),
    ("/debate-abort",      "/debate-abort"),
    ("/todo something",    "/todo"),
    ("/todo-list",         "/todo-list"),
])
def test_route_dispatches_each_prefix(
    jpo: ModuleType,
    fake_plugin_root: Path,
    prompt: str,
    expected_key: str,
) -> None:
    target = jpo.route(prompt, fake_plugin_root)
    assert target is not None
    assert target == fake_plugin_root / SUBORCHESTRATORS[expected_key]


def test_route_returns_none_for_unknown(jpo: ModuleType, fake_plugin_root: Path) -> None:
    assert jpo.route("/unknown", fake_plugin_root) is None
    assert jpo.route("", fake_plugin_root) is None


def test_route_does_not_match_prefix_collision(jpo: ModuleType, fake_plugin_root: Path) -> None:
    # Scenario: "/jotfoo" must NOT match "/jot" — bash's case `"/jot "*` requires space/newline.
    assert jpo.route("/jotfoo", fake_plugin_root) is None
    # but "/todo-list" must match its OWN entry, not "/todo".
    target = jpo.route("/todo-list extra", fake_plugin_root)
    assert target == fake_plugin_root / SUBORCHESTRATORS["/todo-list"]


# ----- main() integration tests -----------------------------------------


def test_main_empty_stdin_passes_through(jpo: ModuleType, fake_plugin_root: Path) -> None:
    rc = _run_main(jpo, fake_plugin_root, "")
    assert rc == 0
    # No stub stdin file should exist.
    for rel in SUBORCHESTRATORS.values():
        assert not (fake_plugin_root / f"{rel}.stdin").exists()


def test_main_unknown_prompt_passes_through(jpo: ModuleType, fake_plugin_root: Path) -> None:
    rc = _run_main(jpo, fake_plugin_root, '{"prompt": "/unknown"}')
    assert rc == 0
    for rel in SUBORCHESTRATORS.values():
        assert not (fake_plugin_root / f"{rel}.stdin").exists()


def test_main_dispatches_jot(jpo: ModuleType, fake_plugin_root: Path) -> None:
    raw = '{"prompt": "/jot foo"}'
    rc = _run_main(jpo, fake_plugin_root, raw)
    assert rc == 0
    forwarded = _read_stub_stdin(fake_plugin_root, "/jot")
    assert json.loads(forwarded)["prompt"] == "/jot foo"


def test_main_strips_leading_whitespace_and_dispatches_plate(jpo: ModuleType, fake_plugin_root: Path) -> None:
    rc = _run_main(jpo, fake_plugin_root, '{"prompt": "  /plate --done"}')
    assert rc == 0
    forwarded = _read_stub_stdin(fake_plugin_root, "/plate")
    assert json.loads(forwarded)["prompt"] == "  /plate --done" or \
           json.loads(forwarded)["prompt"] == "/plate --done"
    # Bash version of the dispatcher does not rewrite whitespace in JSON;
    # only the local var. Either preservation OR strip is acceptable as long as
    # the receiving sub-orchestrator can handle it. Prefer preservation to match
    # bash behavior bit-for-bit.


def test_main_normalizes_colon_form_in_forwarded_json(jpo: ModuleType, fake_plugin_root: Path) -> None:
    rc = _run_main(jpo, fake_plugin_root, '{"prompt": "/jot:todo-list"}')
    assert rc == 0
    forwarded = _read_stub_stdin(fake_plugin_root, "/todo-list")
    assert json.loads(forwarded)["prompt"] == "/todo-list"


def test_main_dispatches_newline_form(jpo: ModuleType, fake_plugin_root: Path) -> None:
    raw = '{"prompt": "/jot\\nfoo"}'
    rc = _run_main(jpo, fake_plugin_root, raw)
    assert rc == 0
    forwarded = _read_stub_stdin(fake_plugin_root, "/jot")
    assert "/jot" in json.loads(forwarded)["prompt"]


def test_main_session_end_path_dispatches_plate(jpo: ModuleType, fake_plugin_root: Path) -> None:
    # Scenario: SessionEnd hook injects .prompt = "/plate" before piping.
    rc = _run_main(jpo, fake_plugin_root, '{"prompt": "/plate"}')
    assert rc == 0
    forwarded = _read_stub_stdin(fake_plugin_root, "/plate")
    assert json.loads(forwarded)["prompt"] == "/plate"


def test_main_subprocess_exit_code_propagates(jpo: ModuleType, fake_plugin_root: Path) -> None:
    # Scenario: sub-orchestrator returns nonzero — script must propagate.
    rc = _run_main(jpo, fake_plugin_root, '{"prompt": "/todo"}', env={"STUB_EXIT_CODE": "7"})
    assert rc == 7


def test_main_malformed_json_passes_through(jpo: ModuleType, fake_plugin_root: Path) -> None:
    rc = _run_main(jpo, fake_plugin_root, "this is not json")
    assert rc == 0
    for rel in SUBORCHESTRATORS.values():
        assert not (fake_plugin_root / f"{rel}.stdin").exists()


# ----- end-to-end via bash shim -----------------------------------------


def test_bash_shim_invokes_python(fake_plugin_root: Path) -> None:
    """Once the .sh body is replaced with the exec-python shim, invoking the
    .sh directly should still dispatch correctly.

    Skipped automatically until the shim is in place (the original bash body
    needs `jq` and would still pass; this test specifically exercises the
    shim form by inspecting the .sh content first).
    """
    sh = REPO_ROOT / "scripts" / "jot-plugin-orchestrator.sh"
    body = sh.read_text()
    if "exec python3" not in body:
        pytest.skip("shim not yet installed")
    result = subprocess.run(
        ["bash", str(sh)],
        input='{"prompt": "/jot foo"}',
        text=True,
        capture_output=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(fake_plugin_root)},
    )
    assert result.returncode == 0, result.stderr
    forwarded = _read_stub_stdin(fake_plugin_root, "/jot")
    assert json.loads(forwarded)["prompt"] == "/jot foo"
