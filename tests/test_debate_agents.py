"""Tests for debate_lib -- agents bucket (probes, defaultModel, detect, initAgentModels, agentLaunchCmd, env-fallback)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from common.scripts.util_lib import _valid_kwargs

from common.scripts.debate_lib import (
    DebateContext,
    debate_agentLaunchCmd,
    debate_defaultModel,
    debate_detectAvailableAgents,
    debate_initAgentModels,
    debate_probeCodex,
    debate_probeGemini,
    debate_tmuxOrchestrator,
)


def test_debate_agents_falls_back_to_env() -> None:
    # Scenario: debate_agents="" but DEBATE_AGENTS env var is set; orchestrator uses env value.
    # Setup: inject mock daemon_main and cleanup; set DEBATE_AGENTS env.
    # Test action: call with debate_agents="".
    # Test verification: daemon_main called once; ctx.agents matches env value.
    mock_daemon = MagicMock()
    mock_cleanup = MagicMock()
    with patch.dict(os.environ, {"DEBATE_AGENTS": "claude codex"}, clear=False):
        debate_tmuxOrchestrator(
            **_valid_kwargs(debate_agents=""),
            daemon_main_fn=mock_daemon,
            cleanup_fn=mock_cleanup,
        )
    ctx: DebateContext = mock_daemon.call_args[0][0]
    assert ctx.agents == ["claude", "codex"]


# =====================================================================
# debate_agentLaunchCmd tests
# =====================================================================

def test_gemini_with_model() -> None:
    # Scenario: caller selected an explicit gemini model.
    # Setup: stash CURRENT_MODEL[gemini] = "gemini-2.5-pro".
    current_model = {"gemini": "gemini-2.5-pro"}
    # Test action: build launch cmd for gemini.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: --model flag appears with the chosen model, quoted.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)' "
        "--model 'gemini-2.5-pro'"
    )


def test_gemini_without_model() -> None:
    # Scenario: no model preselected for gemini.
    # Setup: stash CURRENT_MODEL[gemini] = "" (empty).
    current_model = {"gemini": ""}
    # Test action: build launch cmd.
    cmd = debate_agentLaunchCmd(
        agent="gemini",
        current_model=current_model,
        debate_dir="/tmp/x",
        cwd="/tmp/x",
        repo_root="/tmp/x",
        home="/tmp/home",
        settings_file="/tmp/s.json",
    )
    # Test verification: no --model segment present.
    assert cmd == (
        "gemini --allowed-tools "
        "'read_file,write_file,run_shell_command(ls)'"
    )


def test_codex_with_model() -> None:
    # Scenario: codex with explicit model.
    # Setup: model "gpt-5", debate_dir "/repo/Debates/T_slug".
    current_model = {"codex": "gpt-5"}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/T_slug",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: --add-dir uses debate_dir; --model uses provided.
    assert cmd == "codex -a never --add-dir '/repo/Debates/T_slug' --model 'gpt-5'"


def test_codex_without_model() -> None:
    # Scenario: codex without model.
    # Setup: empty model entry.
    current_model = {"codex": ""}
    # Test action.
    cmd = debate_agentLaunchCmd(
        agent="codex",
        current_model=current_model,
        debate_dir="/repo/Debates/X",
        cwd="/repo",
        repo_root="/repo",
        home="/h",
        settings_file="/s.json",
    )
    # Test verification: no --model.
    assert cmd == "codex -a never --add-dir '/repo/Debates/X'"


# =====================================================================
# debate_probeGemini tests
# =====================================================================


def test_returns_empty_when_gemini_binary_missing():
    # Scenario: gemini CLI not installed on this machine.
    # Setup: shutil.which returns None for "gemini"; clear all credential env.
    with patch("common.scripts.debate_lib.shutil.which", return_value=None), \
         patch.dict(os.environ, {}, clear=True), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string signals "unavailable" to caller.
    assert result == ""


def test_returns_empty_when_binary_present_but_no_credentials():
    # Scenario: gemini installed but user never logged in or set API key.
    # Setup: which finds binary; no oauth file; no API-key env vars.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {}, clear=True):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string -- credentials gate failed.
    assert result == ""


def test_returns_model_when_oauth_creds_file_present():
    # Scenario: user authenticated via `gemini auth login` (oauth file).
    # Setup: binary on PATH; oauth_creds.json exists; default model configured.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: model name is returned (caller uses it for spawn).
    assert result == "gemini-2.5-pro"


def test_returns_model_when_gemini_api_key_env_set():
    # Scenario: CI / headless usage with GEMINI_API_KEY env var.
    # Setup: binary present; no oauth file; GEMINI_API_KEY set.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GEMINI_API_KEY": "abc123"}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gemini-2.5-flash"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: env-var credentials path also yields model name.
    assert result == "gemini-2.5-flash"


def test_returns_model_when_google_api_key_env_set():
    # Scenario: alternate env var GOOGLE_API_KEY (Google AI Studio name).
    # Setup: binary present; no oauth file; only GOOGLE_API_KEY set.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GOOGLE_API_KEY": "xyz789"}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: GOOGLE_API_KEY satisfies the credentials gate.
    assert result == "gemini-2.5-pro"


def test_returns_present_sentinel_when_no_model_configured():
    # Scenario: gemini available but models.json has no entry for it.
    # Setup: all gates pass; _default_model returns "" (no model listed).
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/bin/gemini"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value=""):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: literal "present" sentinel -- non-empty so caller's
    # `-s` truthiness check treats gemini as available.
    assert result == "present"


# =====================================================================
# debate_defaultModel tests
# =====================================================================


def _make_plugin_root(tmp_path: Path, payload: dict) -> Path:
    assets = tmp_path / "skills" / "debate" / "scripts" / "assets"
    assets.mkdir(parents=True)
    (assets / "models.json").write_text(json.dumps(payload))
    return tmp_path


def test_returns_first_claude_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "claude".
    # Setup: plugin root with models.json mapping claude -> 3 models.
    root = _make_plugin_root(tmp_path, {
        "claude": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        "gemini": ["gemini-3.1-pro-preview"],
        "codex": ["gpt-5.5"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="claude".
    result = debate_defaultModel("claude")
    # Test verification: index-0 entry for claude is returned verbatim.
    assert result == "claude-opus-4-7"


def test_returns_first_gemini_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "gemini".
    # Setup: plugin root with multi-entry gemini list.
    root = _make_plugin_root(tmp_path, {
        "gemini": ["gemini-3.1-pro-preview", "gemini-3-flash-preview"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: returns the first gemini model only.
    assert result == "gemini-3.1-pro-preview"


def test_returns_first_codex_model(tmp_path, monkeypatch):
    # Scenario: caller asks for the launch-time model for "codex".
    # Setup: plugin root with codex list.
    root = _make_plugin_root(tmp_path, {
        "codex": ["gpt-5.5", "gpt-5.4"],
    })
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="codex".
    result = debate_defaultModel("codex")
    # Test verification: index-0 codex model returned.
    assert result == "gpt-5.5"


def test_unknown_agent_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: caller asks for an agent absent from models.json.
    # Setup: models.json with only claude listed.
    root = _make_plugin_root(tmp_path, {"claude": ["claude-opus-4-7"]})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for an unmapped agent name.
    result = debate_defaultModel("gemini")
    # Test verification: bash `// ""` fallback is "", not None / KeyError.
    assert result == ""


def test_agent_with_empty_list_returns_empty_string(tmp_path, monkeypatch):
    # Scenario: agent key exists but has no models configured.
    # Setup: gemini key maps to an empty array.
    root = _make_plugin_root(tmp_path, {"gemini": []})
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    # Test action: invoke for agent="gemini".
    result = debate_defaultModel("gemini")
    # Test verification: jq `.[$a][0] // ""` returns "" on empty list.
    assert result == ""


def test_missing_plugin_root_env_raises(tmp_path, monkeypatch):
    # Scenario: CLAUDE_PLUGIN_ROOT is unset (plugin harness not active).
    # Setup: clear the env var.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    # Test action + verification: a clear error is raised, not silent "".
    with pytest.raises((KeyError, RuntimeError)):
        debate_defaultModel("claude")


# =====================================================================
# debate_detectAvailableAgents tests
# =====================================================================


def test_only_claude_when_both_probes_unavailable():
    # Scenario: no gemini, no codex installed -> only claude is available.
    # Setup: patch both probes at SUT module boundary to return "" (unavailable).
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value=""), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: claude-only list, both model strings empty.
    assert result["available"] == ["claude"]
    assert result["gemini_model"] == ""
    assert result["codex_model"] == ""


def test_gemini_with_real_model_appended_and_model_recorded():
    # Scenario: gemini probe returns a real model name -> gemini joins list, model captured.
    # Setup: gemini probe returns concrete model; codex probe returns "" (unavailable).
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == ""


def test_gemini_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: gemini probe returns "present" sentinel (binary+creds, no model configured).
    # Setup: probe returns literal "present"; codex unavailable.
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value="present"), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value=""):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: gemini in list, but gemini_model is "" (sentinel suppressed).
    assert result["available"] == ["claude", "gemini"]
    assert result["gemini_model"] == ""


def test_codex_with_real_model_appended_and_model_recorded():
    # Scenario: codex probe returns a real model name -> codex joins list, model captured.
    # Setup: gemini unavailable, codex returns concrete model.
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value=""), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex joins after claude; model captured verbatim.
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == "gpt-5-codex"
    assert result["gemini_model"] == ""


def test_codex_present_sentinel_marks_available_but_leaves_model_blank():
    # Scenario: codex probe returns "present" sentinel.
    # Setup: gemini unavailable, codex returns literal "present".
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value=""), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value="present"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: codex available, codex_model blank (sentinel suppressed).
    assert result["available"] == ["claude", "codex"]
    assert result["codex_model"] == ""


def test_both_probes_available_preserves_order_claude_gemini_codex():
    # Scenario: both auxiliary agents usable -> list order is claude, gemini, codex.
    # Setup: both probes return real model names.
    with patch("common.scripts.debate_lib.debate_probeGemini", return_value="gemini-2.5-pro"), \
         patch("common.scripts.debate_lib.debate_probeCodex", return_value="gpt-5-codex"):
        # Test action: invoke detector.
        result = debate_detectAvailableAgents()
    # Test verification: ordered list and both models captured.
    assert result["available"] == ["claude", "gemini", "codex"]
    assert result["gemini_model"] == "gemini-2.5-pro"
    assert result["codex_model"] == "gpt-5-codex"


# =====================================================================
# debate_initAgentModels tests
# =====================================================================


def test_returns_dict_with_current_model_and_tried_models_keys():
    # Scenario: caller invokes with no env overrides
    # Setup: empty env dict
    # Test action: call with empty env
    # Test verification: returned mapping has both top-level keys
    result = debate_initAgentModels(env={})
    assert "CURRENT_MODEL" in result
    assert "TRIED_MODELS" in result


def test_all_three_agents_present_in_both_subdicts():
    # Scenario: bash loop initializes gemini/codex/claude entries
    # Setup: empty env
    # Test action: call function
    # Test verification: every agent key exists in both subdicts
    result = debate_initAgentModels(env={})
    for agent in ("gemini", "codex", "claude"):
        assert agent in result["CURRENT_MODEL"]
        assert agent in result["TRIED_MODELS"]


def test_gemini_picks_up_GEMINI_MODEL_env():
    # Scenario: GEMINI_MODEL env var set
    # Setup: env with GEMINI_MODEL
    # Test action: call function with that env
    # Test verification: gemini current/tried both equal that value
    result = debate_initAgentModels(env={"GEMINI_MODEL": "gemini-2.5-pro"})
    assert result["CURRENT_MODEL"]["gemini"] == "gemini-2.5-pro"
    assert result["TRIED_MODELS"]["gemini"] == "gemini-2.5-pro"


def test_codex_picks_up_CODEX_MODEL_env():
    # Scenario: CODEX_MODEL env var set
    # Setup: env with CODEX_MODEL
    # Test action: call function with that env
    # Test verification: codex current/tried both equal that value
    result = debate_initAgentModels(env={"CODEX_MODEL": "gpt-5"})
    assert result["CURRENT_MODEL"]["codex"] == "gpt-5"
    assert result["TRIED_MODELS"]["codex"] == "gpt-5"


def test_unset_gemini_env_yields_empty_string_not_missing_key():
    # Scenario: bash uses ${GEMINI_MODEL:-} which expands to "" when unset
    # Setup: env without GEMINI_MODEL
    # Test action: call function
    # Test verification: gemini entry is "" (not None, not absent)
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["gemini"] == ""
    assert result["TRIED_MODELS"]["gemini"] == ""


def test_unset_codex_env_yields_empty_string():
    # Scenario: CODEX_MODEL unset
    # Setup: env without CODEX_MODEL
    # Test action: call function
    # Test verification: codex entry is ""
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["codex"] == ""
    assert result["TRIED_MODELS"]["codex"] == ""


def test_independent_calls_return_independent_dicts():
    # Scenario: ABSORBED idiom - caller owns state, no shared globals
    # Setup: two separate calls
    # Test action: mutate first result
    # Test verification: second result is unaffected
    a = debate_initAgentModels(env={})
    a["CURRENT_MODEL"]["gemini"] = "mutated"
    b = debate_initAgentModels(env={})
    assert b["CURRENT_MODEL"]["gemini"] == ""


def test_env_defaults_to_os_environ_when_omitted(monkeypatch):
    # Scenario: caller omits env arg; function reads os.environ
    # Setup: monkeypatch GEMINI_MODEL in os.environ
    # Test action: call without env kwarg
    # Test verification: gemini entry reflects the patched env
    monkeypatch.setenv("GEMINI_MODEL", "from-os-env")
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    result = debate_initAgentModels()
    assert result["CURRENT_MODEL"]["gemini"] == "from-os-env"


# =====================================================================
# debate_probeCodex tests
# =====================================================================


def test_returns_empty_when_codex_binary_missing():
    # Scenario: codex CLI is not installed on PATH.
    # Setup: shutil.which("codex") returns None; credentials irrelevant.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" (unavailable sentinel, mirrors bash empty stdout).
    with patch("common.scripts.debate_lib.shutil.which", return_value=None), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == ""


def test_returns_empty_when_no_credentials_present():
    # Scenario: codex binary exists but no auth.json and no OPENAI_API_KEY.
    # Setup: which returns a path; auth.json absent; env var unset.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" because credentials gate fails.
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch.dict(os.environ, env, clear=True):
        result = debate_probeCodex()
    assert result == ""


def test_returns_present_when_available_but_no_model_configured():
    # Scenario: codex binary + credentials exist, but models.json has no codex entry.
    # Setup: which -> path; auth.json present; _default_model returns "".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "present" sentinel so outer `-s` check passes.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value=""):
        result = debate_probeCodex()
    assert result == "present"


def test_returns_model_name_when_configured():
    # Scenario: codex binary + credentials exist AND models.json lists a model.
    # Setup: which -> path; auth.json present; _default_model returns "gpt-5".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns the model name verbatim.
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=True), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gpt-5"):
        result = debate_probeCodex()
    assert result == "gpt-5"


def test_openai_api_key_alone_satisfies_credentials_gate():
    # Scenario: no auth.json on disk, but OPENAI_API_KEY env var is set.
    # Setup: which -> path; isfile -> False; env has OPENAI_API_KEY.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns model name (proves env-var path is honored).
    with patch("common.scripts.debate_lib.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("common.scripts.debate_lib.os.path.isfile", return_value=False), \
         patch("common.scripts.debate_lib.debate_defaultModel", return_value="gpt-5"), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == "gpt-5"
