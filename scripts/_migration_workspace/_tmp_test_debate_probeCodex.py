"""RED tests for debate_probeCodex (migrated from bash `_probe_codex`).

No paired bash _tests existed — RELAXED_COVERAGE. Tests authored from intent
+ docstring of the bash source (jot-plugin-orchestrator.sh:2192-2213):

  "Presence check only (binary + credentials). Empty stdout → unavailable.
   Non-empty stdout → the configured model name (or 'present' if no models
   configured)."

Boundary mocked: shutil.which (binary lookup), os.path.isfile (auth file),
environment (OPENAI_API_KEY), and the _default_model lookup.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(
    0,
    "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts",
)
sys.path.insert(
    0,
    "/Users/matkatmusicllc/Programming/jot-worktrees/python-migration/scripts/_migration_workspace",
)

from _tmp_debate_probeCodex import debate_probeCodex  # noqa: E402


def test_returns_empty_when_codex_binary_missing():
    # Scenario: codex CLI is not installed on PATH.
    # Setup: shutil.which("codex") returns None; credentials irrelevant.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" (unavailable sentinel, mirrors bash empty stdout).
    with patch("_tmp_debate_probeCodex.shutil.which", return_value=None), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == ""


def test_returns_empty_when_no_credentials_present():
    # Scenario: codex binary exists but no auth.json and no OPENAI_API_KEY.
    # Setup: which returns a path; auth.json absent; env var unset.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "" because credentials gate fails.
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    with patch("_tmp_debate_probeCodex.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("_tmp_debate_probeCodex.os.path.isfile", return_value=False), \
         patch.dict(os.environ, env, clear=True):
        result = debate_probeCodex()
    assert result == ""


def test_returns_present_when_available_but_no_model_configured():
    # Scenario: codex binary + credentials exist, but models.json has no codex entry.
    # Setup: which → path; auth.json present; _default_model returns "".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns "present" sentinel so outer `-s` check passes.
    with patch("_tmp_debate_probeCodex.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("_tmp_debate_probeCodex.os.path.isfile", return_value=True), \
         patch("_tmp_debate_probeCodex._default_model", return_value=""):
        result = debate_probeCodex()
    assert result == "present"


def test_returns_model_name_when_configured():
    # Scenario: codex binary + credentials exist AND models.json lists a model.
    # Setup: which → path; auth.json present; _default_model returns "gpt-5".
    # Test action: invoke debate_probeCodex().
    # Test verification: returns the model name verbatim.
    with patch("_tmp_debate_probeCodex.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("_tmp_debate_probeCodex.os.path.isfile", return_value=True), \
         patch("_tmp_debate_probeCodex._default_model", return_value="gpt-5"):
        result = debate_probeCodex()
    assert result == "gpt-5"


def test_openai_api_key_alone_satisfies_credentials_gate():
    # Scenario: no auth.json on disk, but OPENAI_API_KEY env var is set.
    # Setup: which → path; isfile → False; env has OPENAI_API_KEY.
    # Test action: invoke debate_probeCodex().
    # Test verification: returns model name (proves env-var path is honored).
    with patch("_tmp_debate_probeCodex.shutil.which", return_value="/usr/local/bin/codex"), \
         patch("_tmp_debate_probeCodex.os.path.isfile", return_value=False), \
         patch("_tmp_debate_probeCodex._default_model", return_value="gpt-5"), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
        result = debate_probeCodex()
    assert result == "gpt-5"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
