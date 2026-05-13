from __future__ import annotations

from pathlib import Path

import pytest

from common.scripts.git_lib import (
    git_addFile,
    git_checkOutBranch,
    git_createAndCheckoutBranch,
    git_createCommit,
    git_createUserConfig,
    git_getCommitSubject,
    git_getCommitTrailers,
    git_getCurrentBranchName,
    git_makeRepo,
)
from common.scripts.plate import _rebase_reword_summary as reword
from common.scripts.plate import plate_cli
from common.scripts.plate_dispatcher import plate_summaryStop


def makeRepoWithPlateBranch(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    git_makeRepo(repo)
    git_createUserConfig(repo)
    branch = git_getCurrentBranchName(repo)
    plate_branch = f"{branch}-plate"

    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    git_addFile(repo, "file.txt")
    git_createCommit(repo, "base")

    git_createAndCheckoutBranch(repo, plate_branch)
    (repo / "file.txt").write_text("plate\n", encoding="utf-8")
    git_addFile(repo, "file.txt")
    git_createCommit(
        repo,
        f"plate: WIP\n\nconvo-id: agent\nparent-branch: {branch}",
    )

    git_checkOutBranch(repo, branch)
    return repo, branch, plate_branch


def test_plate_cli_set_plate_summary_returns_usage_when_arg_count_is_wrong(
    capsys,
) -> None:
    # Scenario: the set-plate-summary CLI variant is called with too few args.
    # Setup: provide only the repo argument.

    # Test action: route through the CLI entry point.
    result = plate_cli.main(["set-plate-summary", "/repo-only"])

    # Test verification: the CLI prints usage and exits successfully.
    assert result == 0
    assert "usage: set-plate-summary" in capsys.readouterr().out


def test_format_trailer_body_returns_empty_string_for_empty_summary() -> None:
    # Scenario: the summary body is empty or whitespace only.
    # Test action: format the empty body.
    result = reword._format_trailer_body("\n  \n")

    # Test verification: no trailer body text is emitted.
    assert result == ""


def test_format_trailer_body_indents_non_first_lines() -> None:
    # Scenario: the summary body has multiple non-blank lines.
    # Test action: format the body for a git trailer continuation.
    result = reword._format_trailer_body("what:\n  changed\n\nwhy:\n needed\n")

    # Test verification: blank lines are dropped and continuation lines indent.
    assert result == "what:\n changed\n why:\n needed"


def test_replace_subject_keeps_message_when_new_subject_is_empty() -> None:
    # Scenario: the agent payload has no usable subject.
    # Setup: create a commit message with an existing subject.
    message = "old subject\n\nbody\n"

    # Test action: replace with an empty subject.
    result = reword._replace_subject(message, "   ")

    # Test verification: the original message is unchanged.
    assert result == message


def test_replace_subject_truncates_long_subject_to_fifty_chars() -> None:
    # Scenario: the agent supplies a subject longer than the allowed cap.
    # Setup: create a 60-character subject.
    message = "old subject\n\nbody\n"
    long_subject = "x" * 60

    # Test action: replace the message subject.
    result = reword._replace_subject(message, long_subject)

    # Test verification: the first line is capped at 50 characters.
    assert result.splitlines()[0] == "x" * 50


def test_append_summary_trailer_inserts_before_git_comment_block() -> None:
    # Scenario: COMMIT_EDITMSG contains git's comment block after the message.
    # Setup: include an existing trailer and a comment line.
    message = "subject\n\nconvo-id: agent\n\n# Please enter the commit message\n"

    # Test action: append the summary trailer.
    result = reword._append_summary_trailer(message, "what:\nchanged")

    # Test verification: convo-summary stays before the comment block.
    assert "convo-summary: what:\n changed\n\n# Please enter" in result


# Replaces tests/test_plate_set_summary_cli.py::test_invokes_cli_set_plate_summary_with_args
def test_plate_summaryStop_runs_real_set_plate_summary_cli_and_updates_plate_tip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Scenario: plate_summaryStop should execute the real set-plate-summary CLI
    # and update the plate branch tip summary.
    # Setup: create a git repo with a main-plate branch and an agent summary file.
    repo, branch, plate_branch = makeRepoWithPlateBranch(tmp_path)
    summary_file = tmp_path / "summary.txt"
    summary_file.write_text("New summary subject\n\nwhat:\nupdated\n", encoding="utf-8")
    monkeypatch.setenv("PLATE_LOG_FILE", str(tmp_path / "plate.log"))

    # Test action: run the stop hook without mocking subprocess.run.
    result = plate_summaryStop(str(repo), branch, str(summary_file))

    # Test verification: the hook succeeds and the real CLI rewrites the tip.
    assert result == 0
    assert git_getCommitSubject(repo, plate_branch) == "New summary subject"
    assert "convo-summary" in git_getCommitTrailers(repo, plate_branch)
