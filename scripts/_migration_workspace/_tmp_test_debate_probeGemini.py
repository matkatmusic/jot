"""RED tests for debate_probeGemini.

Migrated from bash `_probe_gemini` in jot-plugin-orchestrator.sh
(lines 2196-2206). RELAXED_COVERAGE: no paired bash _tests existed —
tests authored from intent + docstring.

Intent (from bash):
  Presence check for the gemini CLI agent. Three gates:
    1. `gemini` binary on PATH.
    2. Credentials available: ~/.gemini/oauth_creds.json file OR
       GEMINI_API_KEY env OR GOOGLE_API_KEY env.
    3. Look up configured model via _default_model("gemini"); return that
       model name, or the literal sentinel "present" if no model configured.
  Returns empty string when unavailable (binary missing OR no credentials).
  Caller treats empty string as "agent unavailable".
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _tmp_debate_probeGemini import debate_probeGemini  # noqa: E402


# ── Gate 1: binary presence ────────────────────────────────────────────


def test_returns_empty_when_gemini_binary_missing():
    # Scenario: gemini CLI not installed on this machine.
    # Setup: shutil.which returns None for "gemini"; clear all credential env.
    with patch("_tmp_debate_probeGemini.shutil.which", return_value=None), \
         patch.dict(os.environ, {}, clear=True), \
         patch("_tmp_debate_probeGemini.os.path.isfile", return_value=False):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string signals "unavailable" to caller.
    assert result == ""


# ── Gate 2: credentials present ────────────────────────────────────────


def test_returns_empty_when_binary_present_but_no_credentials():
    # Scenario: gemini installed but user never logged in or set API key.
    # Setup: which finds binary; no oauth file; no API-key env vars.
    with patch("_tmp_debate_probeGemini.shutil.which", return_value="/usr/bin/gemini"), \
         patch("_tmp_debate_probeGemini.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {}, clear=True):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: empty string — credentials gate failed.
    assert result == ""


def test_returns_model_when_oauth_creds_file_present():
    # Scenario: user authenticated via `gemini auth login` (oauth file).
    # Setup: binary on PATH; oauth_creds.json exists; default model configured.
    with patch("_tmp_debate_probeGemini.shutil.which", return_value="/usr/bin/gemini"), \
         patch("_tmp_debate_probeGemini.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("_tmp_debate_probeGemini._default_model", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: model name is returned (caller uses it for spawn).
    assert result == "gemini-2.5-pro"


def test_returns_model_when_gemini_api_key_env_set():
    # Scenario: CI / headless usage with GEMINI_API_KEY env var.
    # Setup: binary present; no oauth file; GEMINI_API_KEY set.
    with patch("_tmp_debate_probeGemini.shutil.which", return_value="/usr/bin/gemini"), \
         patch("_tmp_debate_probeGemini.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GEMINI_API_KEY": "abc123"}, clear=True), \
         patch("_tmp_debate_probeGemini._default_model", return_value="gemini-2.5-flash"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: env-var credentials path also yields model name.
    assert result == "gemini-2.5-flash"


def test_returns_model_when_google_api_key_env_set():
    # Scenario: alternate env var GOOGLE_API_KEY (Google AI Studio name).
    # Setup: binary present; no oauth file; only GOOGLE_API_KEY set.
    with patch("_tmp_debate_probeGemini.shutil.which", return_value="/usr/bin/gemini"), \
         patch("_tmp_debate_probeGemini.os.path.isfile", return_value=False), \
         patch.dict(os.environ, {"GOOGLE_API_KEY": "xyz789"}, clear=True), \
         patch("_tmp_debate_probeGemini._default_model", return_value="gemini-2.5-pro"):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: GOOGLE_API_KEY satisfies the credentials gate.
    assert result == "gemini-2.5-pro"


# ── Gate 3: model lookup / "present" sentinel ──────────────────────────


def test_returns_present_sentinel_when_no_model_configured():
    # Scenario: gemini available but models.json has no entry for it.
    # Setup: all gates pass; _default_model returns "" (no model listed).
    with patch("_tmp_debate_probeGemini.shutil.which", return_value="/usr/bin/gemini"), \
         patch("_tmp_debate_probeGemini.os.path.isfile", return_value=True), \
         patch.dict(os.environ, {}, clear=True), \
         patch("_tmp_debate_probeGemini._default_model", return_value=""):
        # Test action: probe.
        result = debate_probeGemini()
    # Test verification: literal "present" sentinel — non-empty so caller's
    # `-s` truthiness check treats gemini as available.
    assert result == "present"
