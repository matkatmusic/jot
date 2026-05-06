"""Pytest suite for jot_plugin_orchestrator.py.

Migrated incrementally from scripts/test_monolith.sh per
plans/it-is-time-to-jolly-blossom.md.

Every test follows ~/Programming/dotfiles/claude/RED_GREEN_TDD.md "How to write
the tests": a `# Scenario:` header naming what's being verified, then plain-
English step comments explaining what each step proves.
"""
from __future__ import annotations

import glob
import io
import json
import hashlib
import multiprocessing
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

import jot_plugin_orchestrator
from jot_plugin_orchestrator import (
    claude_buildCmd,
    claude_permseedLog,
    claude_seedPermissions,
    DebateContext,
    debate_agentErrorMarkers,
    debate_agentLaunchCmd,
    debate_agentReadyMarker,
    debate_anyLiveLock,
    debate_archive,
    debate_buildClaudeCmd,
    debate_buildClaudePrompts,
    debate_checkResumeFeasibility,
    debate_claimSession,
    debate_cleanStaleLocks,
    debate_cleanup,
    debate_daemonMain,
    debate_defaultModel,
    debate_detectAvailableAgents,
    debate_findMatching,
    debate_initAgentModels,
    debate_initHookContext,
    debate_launch,
    debate_launchAgent,
    debate_launchAgentsParallel,
    debate_liveSession,
    debate_main,
    debate_newEmptyPane,
    debate_nextModel,
    debate_paneHasCapacityError,
    debate_probeCodex,
    debate_probeGemini,
    debate_retryPaneWithNextModel,
    debate_sendPromptToAgent,
    debate_startOrResume,
    debate_tmuxOrchestrator,
    debate_waitForOutputs,
    debate_writeFailed,
    debateAbort_main,
    debateRetry_main,
    dispatch_main,
    FileLock,
    # hookjson_checkRequirements,
    # hookjson_emitBlock,
    # hookjson_installHint,
    jot_buildClaudeCmd,
    jot_collectDiagnostics,
    jot_diagIndent,
    jot_diagKv,
    jot_diagSection,
    jot_initState,
    jot_launchPhase2Window,
    jot_main,
    jot_popFirstFromQueue,
    jot_rotateAudit,
    jot_sendPrompt,
    jot_sessionEnd,
    jot_sessionStart,
    jot_stop,
    LockTimeout,
    plate_main,
    plate_summaryStop,
    plate_summaryWatch,
    ResumeFeasibility,
    shell_runWithTimeout,
    shell_waitForFile,
    terminal_spawnIfNeeded,
    # tmux_cancelAndSend,
    # tmux_capturePane,
    # tmux_ensureKeepalivePane,
    # tmux_ensureSession,
    # tmux_hasSession,
    # tmux_killPane,
    # tmux_killWindow,
    # tmux_listClients,
    # tmux_listPanes,
    # tmux_listWindows,
    # tmux_newPane,
    # tmux_newSession,
    # tmux_newWindow,
    # tmux_paneHasTitle,
    # tmux_requireVersion,
    # tmux_retile,
    # tmux_selectLayout,
    # tmux_selectPane,
    # tmux_sendAndSubmit,
    # tmux_sendCtrlC,
    # tmux_sendEnter,
    # tmux_sendKeys,
    # tmux_setOption,
    # tmux_setOptionForTarget,
    # tmux_setOptionForWindow,
    # tmux_setOptionGlobally,
    # tmux_setPaneTitle,
    # tmux_splitWindow,
    # tmux_splitWorkerPane,
    # tmux_waitForClaudeReadiness,
    # tmux_windowExists,
    todo_scanOpen,
    todo_sessionEnd,
    todo_sessionStart,
    todo_stop,
)

from common.scripts.hookjson import (
    hookjson_checkRequirements,
    hookjson_emitBlock,
    hookjson_installHint
)

from common.scripts.tmux import (
    tmux_cancelAndSend,
    tmux_capturePane,
    tmux_ensureKeepalivePane,
    tmux_ensureSession,
    tmux_hasSession,
    tmux_killPane,
    tmux_killSession,
    tmux_killWindow,
    tmux_listClients,
    tmux_listPanes,
    tmux_listWindows,
    tmux_newPane,
    tmux_newSession,
    tmux_newWindow,
    tmux_paneHasTitle,
    tmux_requireVersion,
    tmux_retile,
    tmux_selectLayout,
    tmux_selectPane,
    tmux_sendAndSubmit,
    tmux_sendCtrlC,
    tmux_sendEnter,
    tmux_sendKeys,
    tmux_setOption,
    tmux_setOptionForTarget,
    tmux_setOptionForWindow,
    tmux_setOptionGlobally,
    tmux_setPaneTitle,
    tmux_splitWindow,
    tmux_splitWorkerPane,
    tmux_waitForClaudeReadiness,
    tmux_windowExists
)


# Module aliases used by appended workspace test blocks for monkeypatch.
mod = jot_plugin_orchestrator
sut = jot_plugin_orchestrator
module = jot_plugin_orchestrator

# --- hookjson_emitBlock ---



# --- hookjson_installHint ---


# --- claude_buildCmd ---








# --- debate_agentErrorMarkers ---







# --- debate_agentLaunchCmd ---


import os

# Standard sys.path insert so the temp module is importable.





# --- debate_archive ---



import pytest




# --- debate_buildClaudeCmd ---

import json
import os

# sys.path: workspace dir (for _tmp module) + scripts dir (for monolith).




# --- debate_buildClaudePrompts ---






# --- debate_claimSession ---


# Standard temp-file header: make workspace + scripts dir importable.

import pytest




# --- debate_cleanStaleLocks ---

from unittest.mock import patch

# Ensure workspace dir on sys.path so we import the in-progress module.



# --- debate_defaultModel ---

import json
import os

import pytest

# Standard temp file headers: insert workspace dir on sys.path so
# the SUT module can be imported by its temp filename.




# --- debate_detectAvailableAgents ---

import os
from unittest.mock import patch

# Wire workspace path so the SUT module is importable.




# --- debate_findMatching ---





# --- debate_initAgentModels ---




# --- debate_initHookContext ---

import io
import os
import subprocess

import pytest

# Standard temp file headers: insert workspace dir on sys.path so we can import.


# ---------- helpers ----------


# ---------- tests ----------



# --- debate_launch ---

from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ===========================================================================
# 1. Always calls debate_main
# ===========================================================================


# ===========================================================================
# 5. PLUGIN_ROOT exported to environment
# ===========================================================================



# --- debate_launchAgent ---

from unittest.mock import MagicMock, call, patch

import pytest




# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_PANE = "%7"
_STAGE = "r1"
_AGENT = "claude"
_CMD = "claude --settings /tmp/s.json --add-dir '/repo'"
_READY = "Claude Code v"



# ---------------------------------------------------------------------------
# RED tests
# ---------------------------------------------------------------------------



# --- debate_liveSession ---


import os
from unittest.mock import MagicMock, patch




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------




# --- debate_nextModel ---

import json

import pytest

# Ensure workspace dir on sys.path so we can import the temp production module.




# --- debate_paneHasCapacityError ---

import os
from unittest.mock import patch


# --- debate_probeCodex ---

import os
from unittest.mock import patch

import pytest





if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))



# --- debate_retryPaneWithNextModel ---

from unittest.mock import MagicMock, call, patch

import pytest

# Workspace path setup mirrors the plan's import block.


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_BASE_KWARGS = dict(
    pane_index=0,
    agent="gemini",
    stage="r1",
    current_pane_id="%10",
    current_model={"gemini": "gemini-pro"},
    tried_models={"gemini": "gemini-pro"},
    window_target="debate:0",
    cwd="/tmp/cwd",
    repo_root="/tmp/repo",
    home="/tmp/home",
    settings_file="/tmp/settings.json",
    debate_dir="/tmp/debate",
    models_json_path="/tmp/models.json",
)






# --- debate_tmuxOrchestrator ---

import os
from unittest.mock import MagicMock, call, patch

import pytest




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# --- debate_waitForOutputs ---

from unittest.mock import MagicMock

import pytest






# --- debate_writeFailed ---

from datetime import datetime, timezone

# Mirror the temp module's sys.path bootstrap so the import resolves regardless of CWD.



# --- jot_collectDiagnostics ---

import os
from typing import Any

import pytest




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



# --- plate_summaryStop ---

import os
from unittest.mock import patch, MagicMock

# Ensure the workspace dir is importable.

import pytest



# --- plate_summaryWatch ---



import pytest



# ---------------------------------------------------------------------------
# Test doubles: deterministic sleep + tmux send injection
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# --- shell_waitForFile ---




# --- todo_scanOpen ---


# Standard temp file header: make _migration_workspace importable.





# --- todo_stop ---

import time
from unittest.mock import MagicMock, call, patch




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Missing-args guard
# ---------------------------------------------------------------------------


# --- debate_cleanup ---





# --- jot_sessionEnd ---

# Workspace temp tests for `jot_sessionEnd`.
# RELAXED_COVERAGE: derived from bash intent/docstring; no paired bash _tests.




# --- debate_anyLiveLock ---


import pytest

# Allow `from jot_plugin_orchestrator import ...` regardless of pytest CWD.



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------



# --- debate_sendPromptToAgent ---


import pytest




# --- jot_stop ---


import pytest

# --- shared fixtures --------------------------------------------------------



# --- tests ------------------------------------------------------------------



# --- todo_launcher ---

import json
import subprocess

# Standard temp file header: keep workspace importable when run directly.


# --- debate_probeGemini ---

import os
from unittest.mock import patch

import pytest






# --- todo_sessionEnd ---

import shutil

import pytest




# ---------------------------------------------------------------------------
# Nonexistent valid-prefix path - silently ignored
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Empty string - treated as invalid prefix
# ---------------------------------------------------------------------------




# --- debate_launchAgentsParallel ---

from unittest.mock import MagicMock, patch

import pytest




# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared patch helper
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------



# --- debate_newEmptyPane ---


import os
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from jot_plugin_orchestrator import tmux_killSession, tmux_newSession, tmux_listPanes




# --- debateAbort_main ---


import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------



# --- jot_main ---


import io
import json
import os
import subprocess

import pytest


# --- todo_main ---

import io
import json

import pytest






# --- tmux_launcherTests (TEST cluster) ---

import os
import subprocess
import pytest




# ---------- helpers ----------



# --- tmux_layoutTests (TEST cluster) ---



import os
import pytest


# --- tmux_paneTests (TEST cluster) ---



import os
import pytest


# --- tmux_sendKeysTests (TEST cluster) ---



import os
import time
import pytest


# --- tmux_sessionTests (TEST cluster) ---



import os
import pytest




# --- tmux_setOptionTests (TEST cluster) ---



import os
import shutil
import subprocess
import pytest



# =====================================================================
# dispatch_main tests (migrated from _failing/test_dispatch_main.py)
# =====================================================================

import io as _io_dispatch  # noqa: E402

_dm = jot_plugin_orchestrator


def _stub_argv(monkeypatch, name, recorder, key):
    # Replace _dm.<name> with a stub and rewire _ARGV_DISPATCH.
    def _fn(*args, **kwargs):
        recorder.append((key, args, kwargs))
        return 0
    monkeypatch.setattr(_dm, name, _fn)
    if key in _dm._ARGV_DISPATCH:
        # monkeypatch the dict entry so cleanup restores it.
        monkeypatch.setitem(_dm._ARGV_DISPATCH, key, _fn)


def _stub_prompt_disp(monkeypatch, name, recorder, key):
    # Stub a stdin-mode entrypoint and rebuild the prompt dispatch tuple.
    def _fn(*args, **kwargs):
        recorder.append((key, sys.stdin.read()))
        return 0
    monkeypatch.setattr(_dm, name, _fn)
    rebuilt = []
    for prefix, original_fn in _dm._PROMPT_DISPATCH:
        if prefix == key:
            rebuilt.append((prefix, lambda f=_fn: f()))
        else:
            rebuilt.append((prefix, original_fn))
    monkeypatch.setattr(_dm, "_PROMPT_DISPATCH", tuple(rebuilt))


@pytest.mark.parametrize(
    "subcmd,fn_name",
    [
        ("jot-session-start", "jot_sessionStart"),
        ("jot-session-end", "jot_sessionEnd"),
        ("jot-stop", "jot_stop"),
        ("scan-open-todos", "todo_scanOpen"),
        ("todo-launcher", "todo_launcher"),
        ("todo-stop", "todo_stop"),
        ("todo-session-start", "todo_sessionStart"),
        ("todo-session-end", "todo_sessionEnd"),
        ("plate-summary-stop", "plate_summaryStop"),
        ("plate-summary-watch", "plate_summaryWatch"),
        ("debate-tmux-orchestrator", "debate_tmuxOrchestrator"),
        ("jot-diag-collect", "jot_collectDiagnostics"),
    ],
)
def test_dispatchMain_argv_subcommand_routes_to_function(monkeypatch, subcmd, fn_name):
    # Scenario: argv[0] is a known subcommand; dispatcher routes to it.
    # Setup: stub the target function and rewire the argv map; stdin empty.
    calls: list = []
    _stub_argv(monkeypatch, fn_name, calls, subcmd)
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(""))
    # Test action:
    rc = dispatch_main([subcmd, "alpha", "beta"])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == subcmd
    assert calls[0][1] == (["alpha", "beta"],)



@pytest.mark.parametrize(
    "prefix,fn_name",
    [
        ("/jot", "jot_main"),
        ("/plate", "plate_main"),
        ("/debate", "debate_launch"),
        ("/debate-retry", "debateRetry_main"),
        ("/debate-abort", "debateAbort_main"),
        ("/todo", "todo_main"),
        ("/todo-list", "todoList_main"),
    ],
)
def test_dispatchMain_prompt_prefix_routes_to_entrypoint(monkeypatch, prefix, fn_name):
    # Scenario: stdin .prompt starts with a known slash command; dispatch routes.
    # Setup: stub the entrypoint; feed JSON with prefix + tail.
    calls: list = []
    _stub_prompt_disp(monkeypatch, fn_name, calls, prefix)
    payload = json.dumps({"prompt": f"{prefix} arg-tail"})
    monkeypatch.setattr(sys, "stdin", _io_dispatch.StringIO(payload))
    # Test action:
    rc = dispatch_main([])
    # Test verification:
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == prefix

