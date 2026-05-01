"""Unit tests for common/scripts/plate/cli.py — argv routing + trailer kwarg propagation.

These tests exercise the CLI dispatcher in isolation: every plate_* function
is mocked, so no git, no temp repos, no transcript files. The underlying
plate_* logic is already covered by helpers.py's 112 tests.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest import mock

# cli.py lives in common/scripts/plate/ alongside plate_lib.py.
# conftest.py has already added that directory to sys.path.
import cli  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _run(argv: list[str]) -> tuple[str, int]:
    """Invoke cli.main(argv), capture stdout, return (stdout_text, exit_code)."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdout", buf):
        rc = cli.main(argv)
    return buf.getvalue().rstrip("\n"), rc


# ──────────────────────────────────────────────────────────────────────
# 1. Variant routing — each variant calls the correct plate_* function
#    with the correct argument shape.
# ──────────────────────────────────────────────────────────────────────

def test_routes_push_to_plate_push() -> None:
    """push <convo_id> <transcript_path> <cwd> → plate_lib.plate_push(repo, convo_id=..., convo_name=..., convo_summary=None).

    convo_summary is always None at push time — the background summary
    agent fills in the trailer asynchronously via set-plate-summary.
    """
    with mock.patch.object(cli.plate_lib, "plate_push", return_value="abc123def456") as mp, \
         mock.patch.object(cli.plate_lib, "extractConvoNameFromTranscript", return_value="my-convo") as mn, \
         mock.patch.object(cli.plate_lib, "getCurrentBranchName", return_value="feature-x"), \
         mock.patch.dict(os.environ, {"PLATE_SKIP_LAUNCH": "1"}):
        out, rc = _run(["push", "sid-123", "/tmp/transcript.jsonl", "/repos/myproj"])
    assert rc == 0
    assert mp.call_count == 1
    args, kwargs = mp.call_args
    assert args == (Path("/repos/myproj"),)
    assert kwargs == {
        "convo_id": "sid-123",
        "convo_name": "my-convo",
        "convo_summary": None,
        "transcript_path": "/tmp/transcript.jsonl",
    }
    # extract* helper called with the transcript path.
    assert mn.call_args.args == (Path("/tmp/transcript.jsonl"),)
    # User-facing return text uses short SHA + branch.
    assert out == "plate: pushed abc123de on feature-x-plate"


def test_routes_done_to_plate_done() -> None:
    with mock.patch.object(cli.plate_lib, "plate_done") as md:
        out, rc = _run(["done", "/repos/myproj"])
    assert rc == 0
    assert md.call_args.args == (Path("/repos/myproj"),)
    assert out == "plate: replayed plate stack onto current branch"


def test_routes_drop_to_plate_drop() -> None:
    session = Path("/repos/myproj/.plate/trash/main/20260501T120000Z_dropped_a3f9c1d")
    with mock.patch.object(cli.plate_lib, "plate_drop", return_value=session) as md:
        out, rc = _run(["drop", "/repos/myproj"])
    assert rc == 0
    assert md.call_args.args == (Path("/repos/myproj"),)
    assert "dropped" in out and "20260501T120000Z_dropped_a3f9c1d" in out


def test_routes_drop_no_plate() -> None:
    """drop returns None → user-facing 'no plate to drop'."""
    with mock.patch.object(cli.plate_lib, "plate_drop", return_value=None):
        out, rc = _run(["drop", "/repos/myproj"])
    assert rc == 0
    assert out == "plate: no plate to drop"


def test_routes_trash_to_plate_trash() -> None:
    """trash <repo> → plate_trash(repo, clean_wt=False)."""
    with mock.patch.object(cli.plate_lib, "plate_trash", return_value=Path("/p.patch")) as mt:
        out, rc = _run(["trash", "/repos/myproj"])
    assert rc == 0
    assert mt.call_args.args == (Path("/repos/myproj"),)
    assert mt.call_args.kwargs == {"clean_wt": False}
    assert "trashed" in out


def test_routes_trash_with_clean_wt_flag() -> None:
    """trash <repo> --clean-wt → plate_trash(repo, clean_wt=True)."""
    with mock.patch.object(cli.plate_lib, "plate_trash", return_value=Path("/p.patch")) as mt:
        out, rc = _run(["trash", "/repos/myproj", "--clean-wt"])
    assert rc == 0
    assert mt.call_args.kwargs == {"clean_wt": True}


def test_routes_recycle_to_plate_recycle() -> None:
    sha = "deadbeef" + "0" * 32
    with mock.patch.object(cli.plate_lib, "plate_recycle", return_value=sha) as mr:
        out, rc = _run(["recycle", "/repos/myproj"])
    assert rc == 0
    assert mr.call_args.args == (Path("/repos/myproj"),)
    assert "recycled" in out and "deadbeef" in out


def test_routes_recycle_list() -> None:
    """recycle <repo> --list → plate_recycle_list(repo)."""
    with mock.patch.object(
        cli.plate_lib, "plate_recycle_list",
        return_value="trash sessions for 'main' (newest last):\n  20260501T120000Z_dropped_a3f9c1d  (dropped, ...)",
    ) as ml:
        out, rc = _run(["recycle", "/repos/myproj", "--list"])
    assert rc == 0
    assert ml.call_args.args == (Path("/repos/myproj"),)
    assert "trash sessions" in out


def test_routes_recycle_named_session() -> None:
    """recycle <repo> <session> → plate_recycle(repo, session=<name>)."""
    sha = "deadbeef" + "0" * 32
    with mock.patch.object(cli.plate_lib, "plate_recycle", return_value=sha) as mr:
        out, rc = _run(["recycle", "/repos/myproj", "20260501T120000Z_dropped_a3f9c1d"])
    assert rc == 0
    assert mr.call_args.args == (Path("/repos/myproj"),)
    assert mr.call_args.kwargs == {"session": "20260501T120000Z_dropped_a3f9c1d"}
    assert "recycled" in out


def test_routes_next_list_mode() -> None:
    """next <repo> (no index) → plate_next(repo) — list mode."""
    with mock.patch.object(cli.plate_lib, "plate_next", return_value="1. plate-a (current)  age: 5m") as mn:
        out, rc = _run(["next", "/repos/myproj"])
    assert rc == 0
    # Called positionally with no index kwarg.
    assert mn.call_args.args == (Path("/repos/myproj"),)
    assert mn.call_args.kwargs == {}
    assert out == "1. plate-a (current)  age: 5m"


def test_routes_next_jump_mode_passes_raw_string() -> None:
    """next <repo> <index> → plate_next(repo, index=<raw string>). No int conversion in CLI."""
    with mock.patch.object(cli.plate_lib, "plate_next", return_value="resume with: ...") as mn:
        out, rc = _run(["next", "/repos/myproj", "3"])
    assert rc == 0
    assert mn.call_args.args == (Path("/repos/myproj"),)
    assert mn.call_args.kwargs == {"index": "3"}  # ← raw string, not int


def test_routes_next_jump_mode_passes_non_numeric_string() -> None:
    """CLI is a pure pass-through — even non-numeric input goes straight to plate_next."""
    with mock.patch.object(
        cli.plate_lib, "plate_next",
        return_value=cli.plate_lib.PLATE_NEXT_NON_NUMERIC_MESSAGE,
    ) as mn:
        out, rc = _run(["next", "/repos/myproj", "abc"])
    assert rc == 0
    assert mn.call_args.kwargs == {"index": "abc"}
    assert out == cli.plate_lib.PLATE_NEXT_NON_NUMERIC_MESSAGE


def test_routes_show_returns_todo_stub() -> None:
    """show <repo> → literal 'TODO' (variant deferred per open-question 1)."""
    out, rc = _run(["show", "/repos/myproj"])
    assert rc == 0
    assert out == "TODO"


def test_set_plate_summary_cli_routing(tmp_path: Path) -> None:
    """set-plate-summary <repo> <branch> <summary-file> reads the file
    and forwards the contents to plate_lib.rewriteBranchTipSummary."""
    summary_file = tmp_path / "summary.txt"
    summary_file.write_text("what:\nthing\n\nwhy:\nreason\n\nhow:\napproach\n\nnext steps:\n- foo\n")
    with mock.patch.object(cli.plate_lib, "rewriteBranchTipSummary", return_value="abc12345deadbeef") as mr:
        out, rc = _run(["set-plate-summary", "/repos/myproj", "feature-x", str(summary_file)])
    assert rc == 0
    assert mr.call_args.args == (Path("/repos/myproj"), "feature-x", summary_file.read_text())
    assert "abc12345" in out and "feature-x-plate" in out


# ──────────────────────────────────────────────────────────────────────
# 2. Trailer kwarg propagation — push correctly threads transcript-derived
#    metadata into plate_push's kwargs (covered partly by test_routes_push
#    above; this section adds None-propagation cases).
# ──────────────────────────────────────────────────────────────────────

def test_push_propagates_none_when_extract_returns_none() -> None:
    """When the transcript extractor returns None (no custom-title in transcript),
    plate_push must receive convo_name=None — not a stringified None."""
    with mock.patch.object(cli.plate_lib, "plate_push", return_value="sha") as mp, \
         mock.patch.object(cli.plate_lib, "extractConvoNameFromTranscript", return_value=None), \
         mock.patch.object(cli.plate_lib, "getCurrentBranchName", return_value="main"), \
         mock.patch.dict(os.environ, {"PLATE_SKIP_LAUNCH": "1"}):
        _run(["push", "sid", "/tmp/tp.jsonl", "/repo"])
    assert mp.call_args.kwargs == {
        "convo_id": "sid",
        "convo_name": None,
        "convo_summary": None,
        "transcript_path": "/tmp/tp.jsonl",
    }


def test_push_with_empty_transcript_path_skips_extractors() -> None:
    """If transcript_path is empty (hook didn't supply one), extractors are
    NOT called and convo_name/convo_summary are None."""
    with mock.patch.object(cli.plate_lib, "plate_push", return_value="sha") as mp, \
         mock.patch.object(cli.plate_lib, "extractConvoNameFromTranscript") as mn, \
         mock.patch.object(cli.plate_lib, "getCurrentBranchName", return_value="main"), \
         mock.patch.dict(os.environ, {"PLATE_SKIP_LAUNCH": "1"}):
        _run(["push", "sid", "", "/repo"])
    assert mn.call_count == 0
    assert mp.call_args.kwargs == {
        "convo_id": "sid",
        "convo_name": None,
        "convo_summary": None,
        "transcript_path": None,
    }


def test_push_no_changes_returns_no_op_message() -> None:
    """plate_push returns None when the WT tree matches the parent — CLI
    surfaces 'no changes to stack' instead of crashing on .[ :8] slicing of None."""
    with mock.patch.object(cli.plate_lib, "plate_push", return_value=None), \
         mock.patch.object(cli.plate_lib, "extractConvoNameFromTranscript", return_value=None), \
         mock.patch.dict(os.environ, {"PLATE_SKIP_LAUNCH": "1"}):
        out, rc = _run(["push", "sid", "", "/repo"])
    assert rc == 0
    assert out == "plate: no changes to stack"


# ──────────────────────────────────────────────────────────────────────
# 3. Bad-input handling at the CLI layer
# ──────────────────────────────────────────────────────────────────────

def test_no_argv_prints_usage_and_exits_zero() -> None:
    out, rc = _run([])
    assert rc == 0
    assert "missing variant" in out


def test_unknown_variant_prints_message_and_exits_zero() -> None:
    out, rc = _run(["bogus", "/repo"])
    assert rc == 0
    assert "unknown variant" in out and "bogus" in out
