"""Tests for common/scripts/bg_permissions_lib.py - the shared loader that
materializes background-agent permission configs for /jot, /todo, /plate,
/debate from one bundled JSON file."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from common.scripts import bg_permissions_lib
from common.scripts.bg_permissions_lib import (
    bgPermissions_loadClaude,
    bgPermissions_loadCodex,
    bgPermissions_loadGemini,
    bgPermissions_warnLegacyFiles,
)


# ---------------------------------------------------------------------------
# Fixtures: build a tmp_path-scoped bundle + plugin_data so we can exercise
# the seed-on-first-use behavior end-to-end without touching real plugin dirs.
# ---------------------------------------------------------------------------


_SAMPLE_BUNDLE: dict = {
    "_doc": "test bundle",
    "jot_permissions": {
        "claude": {
            "allow": [
                "Read(**)",
                "Write(//${REPO_ROOT}/Todos/**)",
                "Edit(//${REPO_ROOT}/Todos/**)",
                "Read(${HOME}/.claude/projects/**)",
                "Bash(grep:*)",
                "Bash(rtk grep:*)",
            ]
        }
    },
    "todo_permissions": {
        "claude": {
            "allow": [
                "Read(//${REPO_ROOT}/Todos/**)",
                "Bash(head:*)",
            ]
        }
    },
    "plate_permissions": {
        "claude": {
            "allow": [
                "Bash(git log:*)",
                "Bash(rtk git log:*)",
            ]
        }
    },
    "debate_permissions": {
        "claude": {
            "allow": [
                "Read(**)",
                "Write(//${REPO_ROOT}/Debates/**)",
                "Bash(ls:*)",
            ]
        },
        "gemini": {
            "allowed_tools": ["read_file", "write_file", "run_shell_command(ls)"]
        },
        "codex": {
            "approval": "never",
            "sandbox_mode": "workspace-write",
            "extra_flags": []
        }
    }
}


@pytest.fixture
def perms_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    # Setup: synthesize a CLAUDE_PLUGIN_ROOT/assets/bg_agent_permissions.json
    # and matching .sha256 sidecar, plus an empty CLAUDE_PLUGIN_DATA dir.
    plugin_root = tmp_path / "plugin"
    plugin_data = tmp_path / "data"
    assets = plugin_root / "assets"
    assets.mkdir(parents=True)
    plugin_data.mkdir()

    bundle_json = assets / "bg_agent_permissions.json"
    bundle_sha = assets / "bg_agent_permissions.json.sha256"
    bundle_text = json.dumps(_SAMPLE_BUNDLE, indent=2)
    bundle_json.write_text(bundle_text)
    bundle_sha.write_text(hashlib.sha256(bundle_text.encode()).hexdigest() + "\n")

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data))
    return {
        "plugin_root": plugin_root,
        "plugin_data": plugin_data,
        "bundle_json": bundle_json,
        "bundle_sha": bundle_sha,
        "installed_json": plugin_data / "bg_agent_permissions.local.json",
        "installed_sha": plugin_data / "bg_agent_permissions.default.sha256",
    }


# ---------------------------------------------------------------------------
# bgPermissions_loadClaude
# ---------------------------------------------------------------------------


class TestLoadClaude:
    def test_returns_json_array_string(self, perms_bundle):
        # Scenario: loader output must be a json-encoded array.
        # Setup:
        env = {"REPO_ROOT": "/Users/me/repo", "HOME": "/Users/me", "CWD": "/Users/me/repo"}
        # Test action:
        result = bgPermissions_loadClaude("jot", env=env)
        # Test verification:
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert all(isinstance(item, str) for item in parsed)

    def test_repo_root_leading_slash_stripped(self, perms_bundle):
        # Scenario: ${REPO_ROOT} substitution must lstrip leading '/' so rules
        # slot into Claude Code's '//${REPO_ROOT}/...' absolute-path form.
        # Setup:
        env = {"REPO_ROOT": "/Users/me/repo", "HOME": "/Users/me", "CWD": "/Users/me/repo"}
        # Test action:
        parsed = json.loads(bgPermissions_loadClaude("jot", env=env))
        # Test verification: the Todos entries embed the lstripped form
        assert "Write(//Users/me/repo/Todos/**)" in parsed
        assert "Edit(//Users/me/repo/Todos/**)" in parsed

    def test_home_substituted_verbatim(self, perms_bundle):
        # Scenario: ${HOME} is substituted as-is (no slash strip).
        # Setup:
        env = {"REPO_ROOT": "/r", "HOME": "/Users/me", "CWD": "/r"}
        # Test action:
        parsed = json.loads(bgPermissions_loadClaude("jot", env=env))
        # Test verification:
        assert "Read(/Users/me/.claude/projects/**)" in parsed

    def test_extra_allow_appended_verbatim(self, perms_bundle):
        # Scenario: dynamic per-invocation rules merge in at the end without substitution.
        # Setup:
        env = {"REPO_ROOT": "/r", "HOME": "/h", "CWD": "/c"}
        extra = ["Read(//Users/me/output/**)", "Write(//Users/me/output/**)"]
        # Test action:
        parsed = json.loads(bgPermissions_loadClaude("plate", env=env, extra_allow=extra))
        # Test verification:
        assert parsed[-2] == "Read(//Users/me/output/**)"
        assert parsed[-1] == "Write(//Users/me/output/**)"

    def test_unknown_tool_raises_keyerror(self, perms_bundle):
        # Scenario: tool name with no corresponding <tool>_permissions key fails loudly.
        # Setup:
        env = {"REPO_ROOT": "/r", "HOME": "/h", "CWD": "/c"}
        # Test action / verification:
        with pytest.raises(KeyError, match="bogus_permissions"):
            bgPermissions_loadClaude("bogus", env=env)

    def test_seed_creates_installed_runtime_file_on_first_call(self, perms_bundle):
        # Scenario: first load must seed bg_agent_permissions.local.json from bundle.
        # Setup: installed file does not exist
        assert not perms_bundle["installed_json"].exists()
        env = {"REPO_ROOT": "/r", "HOME": "/h", "CWD": "/c"}
        # Test action:
        bgPermissions_loadClaude("jot", env=env)
        # Test verification:
        assert perms_bundle["installed_json"].is_file()
        assert json.loads(perms_bundle["installed_json"].read_text()) == _SAMPLE_BUNDLE

    def test_seed_writes_prior_sha_sidecar(self, perms_bundle):
        # Scenario: prior-sha sidecar tracks the bundled-default sha for upgrade detection.
        # Setup:
        env = {"REPO_ROOT": "/r", "HOME": "/h", "CWD": "/c"}
        expected_sha = perms_bundle["bundle_sha"].read_text().strip()
        # Test action:
        bgPermissions_loadClaude("jot", env=env)
        # Test verification:
        assert perms_bundle["installed_sha"].read_text().strip() == expected_sha


# ---------------------------------------------------------------------------
# bgPermissions_loadGemini
# ---------------------------------------------------------------------------


class TestLoadGemini:
    def test_returns_comma_joined_string(self, perms_bundle):
        # Scenario: gemini --allowed-tools wants a comma-joined string.
        # Test action:
        result = bgPermissions_loadGemini()
        # Test verification:
        assert result == "read_file,write_file,run_shell_command(ls)"

    def test_missing_gemini_section_raises(self, perms_bundle):
        # Scenario: tool with no gemini sub-key (e.g. jot) raises KeyError.
        # Test action / verification:
        with pytest.raises(KeyError, match="gemini"):
            bgPermissions_loadGemini(tool="jot")


# ---------------------------------------------------------------------------
# bgPermissions_loadCodex
# ---------------------------------------------------------------------------


class TestLoadCodex:
    def test_returns_dict_with_expected_keys(self, perms_bundle):
        # Scenario: codex section returns flag config for CLI assembly.
        # Test action:
        result = bgPermissions_loadCodex()
        # Test verification:
        assert result == {
            "approval": "never",
            "sandbox_mode": "workspace-write",
            "extra_flags": [],
        }

    def test_defaults_applied_when_keys_missing(self, perms_bundle, monkeypatch):
        # Scenario: partial codex section (only approval set) still returns full dict.
        # Setup: rewrite installed file with a stripped-down codex section
        installed = perms_bundle["installed_json"]
        # Seed first so the file exists, then mutate it
        bgPermissions_loadCodex()
        data = json.loads(installed.read_text())
        data["debate_permissions"]["codex"] = {"approval": "untrusted"}
        installed.write_text(json.dumps(data))
        # Test action:
        result = bgPermissions_loadCodex()
        # Test verification:
        assert result["approval"] == "untrusted"
        assert result["sandbox_mode"] == "workspace-write"  # default
        assert result["extra_flags"] == []


# ---------------------------------------------------------------------------
# Legacy-file warning
# ---------------------------------------------------------------------------


class TestWarnLegacyFiles:
    def test_no_legacy_files_returns_empty_list(self, perms_bundle):
        # Scenario: clean install, no pre-consolidation files present.
        # Test action / verification:
        assert bgPermissions_warnLegacyFiles() == []

    def test_detects_old_per_skill_files(self, perms_bundle, tmp_path):
        # Scenario: an old install with per-skill runtime files lingering.
        # Setup:
        (perms_bundle["plugin_data"] / "permissions.local.json").write_text("{}")
        (perms_bundle["plugin_data"] / "debate-permissions.local.json").write_text("{}")
        log_file = tmp_path / "log.txt"
        # Test action:
        found = bgPermissions_warnLegacyFiles(log_file=str(log_file))
        # Test verification:
        assert len(found) == 2
        assert any(f.endswith("permissions.local.json") for f in found)
        assert any(f.endswith("debate-permissions.local.json") for f in found)
        # Test verification: warning written to log file
        log_text = log_file.read_text()
        assert "legacy per-skill runtime files" in log_text


# ---------------------------------------------------------------------------
# Environment-error paths
# ---------------------------------------------------------------------------


class TestEnvErrors:
    def test_missing_plugin_root_raises(self, monkeypatch, tmp_path):
        # Scenario: CLAUDE_PLUGIN_ROOT unset and no explicit bundle_path.
        # Setup:
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
        # Test action / verification:
        with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_ROOT not set"):
            bgPermissions_loadClaude("jot", env={"REPO_ROOT": "/r", "HOME": "/h", "CWD": "/c"})

    def test_missing_plugin_data_raises(self, monkeypatch, tmp_path):
        # Scenario: CLAUDE_PLUGIN_DATA unset.
        # Setup:
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
        # Test action / verification:
        with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_DATA not set"):
            bgPermissions_loadClaude("jot", env={"REPO_ROOT": "/r", "HOME": "/h", "CWD": "/c"})
