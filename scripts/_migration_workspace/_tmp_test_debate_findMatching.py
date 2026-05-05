"""RED tests for debate_findMatching (migrated from bash find_matching_debate).

Authored from intent + bash docstring; no paired bash _tests existed.
Tag: RELAXED_COVERAGE.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _tmp_debate_findMatching import debate_findMatching


def _make_debate(repo_root: Path, ts: str, topic_text: str) -> Path:
    # Helper: create Debates/<ts>/topic.md with given text. Returns dir path.
    d = repo_root / "Debates" / ts
    d.mkdir(parents=True)
    (d / "topic.md").write_text(topic_text)
    return d


def test_returns_none_when_no_debates_dir(tmp_path):
    # Scenario: repo has no Debates/ directory at all.
    # Setup: empty tmp repo root.
    repo = tmp_path
    # Test action: call debate_findMatching with any topic.
    result = debate_findMatching(str(repo), "anything")
    # Test verification: returns None (no match).
    assert result is None


def test_returns_none_when_no_topic_matches(tmp_path):
    # Scenario: Debates/ has dirs but none has matching topic.md content.
    # Setup: one debate dir with different topic text.
    repo = tmp_path
    _make_debate(repo, "2026-01-01_120000_a", "different topic\n")
    # Test action: search for unrelated topic.
    result = debate_findMatching(str(repo), "looking for this\n")
    # Test verification: returns None.
    assert result is None


def test_returns_dir_path_for_single_match(tmp_path):
    # Scenario: exactly one debate has a topic.md byte-equal to query.
    # Setup: matching topic written verbatim (incl. trailing newline appended by printf '%s\n').
    repo = tmp_path
    topic = "Discuss async patterns"
    d = _make_debate(repo, "2026-02-02_100000_x", topic + "\n")
    # Test action: query with the same topic (function appends \n internally like `printf '%s\n'`).
    result = debate_findMatching(str(repo), topic)
    # Test verification: returns that debate dir as a string, no trailing slash.
    assert result == str(d)


def test_skips_dirs_missing_topic_md(tmp_path):
    # Scenario: a Debates/<ts>/ dir exists with no topic.md file.
    # Setup: one dir without topic.md, one with matching topic.md.
    repo = tmp_path
    (repo / "Debates" / "2026-03-03_111111_no_topic").mkdir(parents=True)
    d_match = _make_debate(repo, "2026-03-03_222222_yes", "hello\n")
    # Test action.
    result = debate_findMatching(str(repo), "hello")
    # Test verification: skips topic-less dir, returns the one with topic.md.
    assert result == str(d_match)


def test_most_recent_timestamp_wins_on_multiple_matches(tmp_path):
    # Scenario: multiple debates have identical topic.md; lexicographically-greatest dir name wins.
    # Setup: three matching debates with sortable timestamps.
    repo = tmp_path
    topic = "shared topic"
    _make_debate(repo, "2025-01-01_000000_a", topic + "\n")
    _make_debate(repo, "2026-06-15_120000_b", topic + "\n")
    d_newest = _make_debate(repo, "2027-12-31_235959_c", topic + "\n")
    # Test action.
    result = debate_findMatching(str(repo), topic)
    # Test verification: returns lexicographically-greatest (newest) match.
    assert result == str(d_newest)


def test_multiline_topic_byte_exact_match(tmp_path):
    # Scenario: topic spans multiple lines; cmp-style byte-exact compare must succeed.
    # Setup: write multi-line topic with embedded newlines.
    repo = tmp_path
    topic = "line one\nline two\nline three"
    d = _make_debate(repo, "2026-04-04_090000_m", topic + "\n")
    # Test action: pass same multi-line topic.
    result = debate_findMatching(str(repo), topic)
    # Test verification: matches despite multi-line content.
    assert result == str(d)


def test_partial_substring_does_not_match(tmp_path):
    # Scenario: topic.md contains query as substring but is not byte-equal.
    # Setup: topic.md is a superstring.
    repo = tmp_path
    _make_debate(repo, "2026-05-05_100000_p", "prefix hello suffix\n")
    # Test action: query a substring.
    result = debate_findMatching(str(repo), "hello")
    # Test verification: byte-exact match required, returns None.
    assert result is None
