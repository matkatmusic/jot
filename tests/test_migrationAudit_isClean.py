"""Section 6 of plans/python-migration-complete.md.

Asserts that regenerating MIGRATION_TO_PYTHON.md via ``audit_gen.py``
produces a document with no remaining ``NEEDS_*`` migration markers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DOC = REPO_ROOT / "MIGRATION_TO_PYTHON.md"
AUDIT_GEN = REPO_ROOT / "audit_gen.py"


def audit_regenerateMigrationDocument() -> str:
    """Run ``python3 audit_gen.py`` and return the regenerated audit text.

    The script prints the AST-derived audit to stdout. The plan documents
    the regeneration command as ``python3 audit_gen.py > MIGRATION_TO_PYTHON.md``;
    this helper performs that redirection in-process by overwriting the file
    with stdout, then returning the same text for inspection.
    """
    completed = subprocess.run(
        ["python3", str(AUDIT_GEN)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    AUDIT_DOC.write_text(completed.stdout, encoding="utf-8")
    return completed.stdout


def test_migrationAuditDocument_hasNoNeedsMarkers() -> None:
    # Scenario: the regenerated MIGRATION_TO_PYTHON.md must contain zero
    # outstanding NEEDS_* migration markers once every prior plan section
    # has landed.
    # Setup: regenerate the audit document from the live AST via audit_gen.py.
    audit_text = audit_regenerateMigrationDocument()
    # Test action: scan the regenerated text for any NEEDS_ marker token.
    needs_markers_present = "NEEDS_" in audit_text
    # Test verification: zero markers remain in the regenerated document.
    assert not needs_markers_present, (
        "Regenerated MIGRATION_TO_PYTHON.md still contains NEEDS_* markers; "
        "close every gap surfaced by audit_gen.py before this test can pass."
    )
