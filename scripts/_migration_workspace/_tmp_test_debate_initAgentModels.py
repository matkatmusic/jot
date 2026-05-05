"""RED tests for debate_initAgentModels (migrated from bash init_agent_models)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _tmp_debate_initAgentModels import debate_initAgentModels


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


def test_claude_has_empty_string_when_no_env():
    # Scenario: bash never stashes a CLAUDE_MODEL value, only zeroes it
    # Setup: empty env
    # Test action: call function
    # Test verification: claude entries default to ""
    result = debate_initAgentModels(env={})
    assert result["CURRENT_MODEL"]["claude"] == ""
    assert result["TRIED_MODELS"]["claude"] == ""


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
