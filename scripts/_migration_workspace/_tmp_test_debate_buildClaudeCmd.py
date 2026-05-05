"""RED-YELLOW-GREEN tests for debate_buildClaudeCmd.

No paired bash _tests existed — RED tests authored from intent + docstring of
bash `debate_build_claude_cmd` (jot-plugin-orchestrator.sh:2245-2265).

Tagged RELAXED_COVERAGE in name-map.
"""
import json
import os
import sys
from pathlib import Path

# sys.path: workspace dir (for _tmp module) + scripts dir (for monolith).
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from _tmp_debate_buildClaudeCmd import debate_buildClaudeCmd


def test_creates_tmpdir_and_settings_file_path(tmp_path, monkeypatch):
    # Scenario: Function provisions a fresh tmpdir under /tmp and returns a
    # settings.json path inside it.
    # Setup: stub permissions_seed (no-op) and expand_permissions ('[]').
    seeded = []
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()
    (tmp_path / "root" / "skills" / "debate" / "scripts" / "assets").mkdir(parents=True)

    def fake_seed(*args, **kwargs):
        seeded.append(args)

    def fake_expand(perm_file, cwd, repo_root, home):
        return "[]"

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=fake_seed,
        expand_permissions_fn=fake_expand,
    )

    # Test verification: tmpdir exists, settings_file lives inside it.
    assert Path(result["tmpdir_inv"]).is_dir()
    assert result["tmpdir_inv"].startswith("/tmp/debate.")
    assert result["settings_file"] == str(Path(result["tmpdir_inv"]) / "settings.json")


def test_writes_settings_json_with_allow_and_empty_hooks(tmp_path, monkeypatch):
    # Scenario: Settings file is written with permissions.allow from
    # expand_permissions output and an empty hooks object.
    # Setup:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()

    allow_value = '["Bash(echo:*)","Read"]'

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: allow_value,
    )

    # Test verification: parse settings.json round-trip.
    body = json.loads(Path(result["settings_file"]).read_text())
    assert body["permissions"]["allow"] == ["Bash(echo:*)", "Read"]
    assert body["hooks"] == {}


def test_returns_claude_cmd_with_settings_and_add_dir(tmp_path, monkeypatch):
    # Scenario: Returned cmd string contains --settings <file> and --add-dir
    # <cwd>, plus a trailing newline (claude_buildCmd contract).
    # Setup:
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "root"))
    (tmp_path / "data").mkdir()
    cwd = str(tmp_path / "work")
    (tmp_path / "work").mkdir()

    # Test action:
    result = debate_buildClaudeCmd(
        cwd=cwd,
        repo_root=cwd,
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    cmd = result["cmd"]
    assert cmd.endswith("\n")
    assert f"--settings '{result['settings_file']}'" in cmd
    assert f"--add-dir '{cwd}'" in cmd
    assert cmd.startswith("claude ")


def test_invokes_permissions_seed_with_expected_paths(tmp_path, monkeypatch):
    # Scenario: permissions_seed is called once with the documented six args.
    # Setup:
    data = tmp_path / "data"
    root = tmp_path / "root"
    data.mkdir()
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    log = str(tmp_path / "log.txt")
    captured = {}

    def fake_seed(perm_file, default_file, default_sha, prior_sha, log_file, label):
        captured["perm_file"] = perm_file
        captured["default_file"] = default_file
        captured["default_sha"] = default_sha
        captured["prior_sha"] = prior_sha
        captured["log_file"] = log_file
        captured["label"] = label

    # Test action:
    debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=log,
        permissions_seed_fn=fake_seed,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    assert captured["perm_file"] == str(data / "debate-permissions.local.json")
    assert captured["default_file"] == str(
        root / "skills/debate/scripts/assets/permissions.default.json"
    )
    assert captured["default_sha"] == str(
        root / "skills/debate/scripts/assets/permissions.default.json.sha256"
    )
    assert captured["prior_sha"] == str(data / "debate-permissions.default.sha256")
    assert captured["log_file"] == log
    assert captured["label"] == "debate"


def test_creates_claude_plugin_data_dir_if_missing(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_DATA dir does not yet exist; function mkdir -p's it.
    # Setup: data dir intentionally NOT created.
    data = tmp_path / "data_nonexistent"
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))

    # Test action:
    debate_buildClaudeCmd(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        log_file=str(tmp_path / "log.txt"),
        permissions_seed_fn=lambda *a, **k: None,
        expand_permissions_fn=lambda *a, **k: "[]",
    )

    # Test verification:
    assert data.is_dir()
