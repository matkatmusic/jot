"""RED tests for debate_claimSession (migration of bash debate_claim_session).

Bash intent (lines ~2154-2176 of jot-plugin-orchestrator.sh):
  Atomically claim the lowest-unused `debate-N` tmux session by relying on
  `tmux new-session -d -s <name>` as the atomic primitive: it returns
  non-zero on name collision, so iterating N=1..999 until one succeeds is
  race-free across concurrent /debate hooks. Window named `main`, geometry
  -x 200 -y 60, $1 (keepalive_cmd) becomes that window's argv. Returns
  claimed session name; raises (return 1) if no slot found within 999.

Tests exercise behavior via an injectable `tmux_runner` callable so we
do not require a live tmux server in the sandbox.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Standard temp-file header: make workspace + scripts dir importable.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

import pytest

from _tmp_debate_claimSession import debate_claimSession


def test_claims_first_unused_when_all_free(tmp_path):
    # Scenario: no debate-* sessions exist; first attempt at debate-1 succeeds.
    # Setup: fake tmux runner that always returns rc=0 (free slot).
    calls = []

    def fake_tmux(argv):
        calls.append(argv)
        return 0  # success

    # Test action: claim a session.
    result = debate_claimSession("sleep 86400", tmux_runner=fake_tmux)

    # Test verification: returned debate-1 and invoked tmux exactly once.
    assert result == "debate-1"
    assert len(calls) == 1


def test_skips_collisions_until_free_slot(tmp_path):
    # Scenario: debate-1 and debate-2 already exist; debate-3 is free.
    # Setup: runner returns nonzero for first two N, zero for third.
    rcs = iter([1, 1, 0])
    seen = []

    def fake_tmux(argv):
        seen.append(argv)
        return next(rcs)

    # Test action: claim.
    result = debate_claimSession("keepalive", tmux_runner=fake_tmux)

    # Test verification: walked N=1..3, returned debate-3.
    assert result == "debate-3"
    assert len(seen) == 3


def test_passes_keepalive_cmd_and_geometry_to_tmux(tmp_path):
    # Scenario: claim must invoke tmux with -d, -s <name>, -x 200, -y 60,
    #           -n main, and the keepalive_cmd as the final argv.
    # Setup: runner that succeeds and records argv.
    captured = {}

    def fake_tmux(argv):
        captured["argv"] = argv
        return 0

    # Test action: claim with a specific keepalive command.
    debate_claimSession("sleep 99999", tmux_runner=fake_tmux)

    # Test verification: argv contains required flags and keepalive tail.
    argv = captured["argv"]
    assert argv[0] == "tmux"
    assert "new-session" in argv
    assert "-d" in argv
    assert "-s" in argv and argv[argv.index("-s") + 1] == "debate-1"
    assert "-x" in argv and argv[argv.index("-x") + 1] == "200"
    assert "-y" in argv and argv[argv.index("-y") + 1] == "60"
    assert "-n" in argv and argv[argv.index("-n") + 1] == "main"
    assert argv[-1] == "sleep 99999"


def test_raises_when_all_slots_exhausted(tmp_path):
    # Scenario: every N from 1 to 999 collides; function must signal failure.
    # Setup: runner that always returns nonzero.
    attempts = {"n": 0}

    def fake_tmux(argv):
        attempts["n"] += 1
        return 1

    # Test action + verification: RuntimeError raised after 999 attempts.
    with pytest.raises(RuntimeError):
        debate_claimSession("k", tmux_runner=fake_tmux)
    assert attempts["n"] == 999


def test_session_names_are_sequential_debate_n(tmp_path):
    # Scenario: verify the N-th attempt targets `debate-<N>` (1-indexed).
    # Setup: fail first 4, succeed on 5th.
    names = []
    rcs = iter([1, 1, 1, 1, 0])

    def fake_tmux(argv):
        names.append(argv[argv.index("-s") + 1])
        return next(rcs)

    # Test action: claim.
    result = debate_claimSession("cmd", tmux_runner=fake_tmux)

    # Test verification: sequential debate-1..debate-5 attempts, returned debate-5.
    assert names == ["debate-1", "debate-2", "debate-3", "debate-4", "debate-5"]
    assert result == "debate-5"
