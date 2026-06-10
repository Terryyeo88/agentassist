"""
Hermetic tests for the T2.9 declared-vs-computed F5 report section.

Two states under test:
    (a) Findings present  → render_declared_f5_section returns content with the
                            expected rows; build_not_examined_section suppresses
                            the "Declared-vs-computed F5 comparison" item.
    (b) No findings       → render_declared_f5_section returns ""; the
                            "Declared-vs-computed F5 comparison" item is present
                            in Section 6.

All tests are hermetic — no SAP calls, no live chain, no PDF rendering.
"""
from __future__ import annotations

import pytest

from report.constants import NOT_EXAMINED_ITEMS
from report.render import render_declared_f5_section
from report.sections import (
    DeclaredF5Section,
    build_declared_f5_section,
    build_not_examined_section,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_COMPILE_NO_FINDINGS = {
    "deduplicated_anomalies": [],
    "declared_f5_findings": [],
}

_COMPILE_WITH_FINDINGS = {
    "deduplicated_anomalies": [],
    "declared_f5_findings": [
        {
            "check": "B",
            "finding_type": "declared_vs_computed_divergence",
            "box": "box_1",
            "box_label": "Total value of standard-rated supplies",
            "declared": 12000.0,
            "computed": 10000.0,
            "delta": 2000.0,
            "direction": "over_declared",
            "tolerance_applied": 1.0,
            "basis": "IRAS ASK Annual Review Guide s10.1(d)(iii) fn33",
            "hypothesis": (
                "possible over/under-declaration of standard-rated supplies "
                "— for reviewer confirmation"
            ),
        },
        {
            "check": "B",
            "finding_type": "declared_vs_computed_divergence",
            "box": "box_6",
            "box_label": "Output tax due",
            "declared": 1080.0,
            "computed": 900.0,
            "delta": 180.0,
            "direction": "over_declared",
            "tolerance_applied": 1.0,
            "basis": "IRAS ASK Annual Review Guide s10.1(d)(iii) fn33",
            "hypothesis": (
                "possible over-claim of output tax OR unrecorded credit note "
                "— for reviewer confirmation"
            ),
        },
    ],
}

_COMPILE_WITH_CHECK_A = {
    "deduplicated_anomalies": [],
    "declared_f5_findings": [
        {
            "check": "A",
            "finding_type": "declared_internal_inconsistency",
            "rule": "Box 4 must equal Box 1 + Box 2 + Box 3",
            "box": "box_4",
            "declared_box4": 10600.0,
            "expected_box4": 10500.0,
            "delta": 100.0,
            "description": (
                "Declared Box 4 (10600.0) does not equal "
                "Box1+Box2+Box3 (10000.0+500.0+0.0=10500.0); delta=+100.00."
            ),
        },
    ],
}

# Minimal ClientConfig stub — avoids importing full config.loader.
class _FakeCfg:
    custom_vat_groups: dict = {}


_CFG = _FakeCfg()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _not_examined_text(compile_output: dict, findings: list[dict] | None = None) -> str:
    """Return a single string of all not-examined items joined by spaces."""
    section = build_not_examined_section(
        compile_output, _CFG, declared_f5_findings=findings
    )
    return " ".join(section.items).lower()


def _decl_f5_item_present(compile_output: dict, findings: list[dict] | None = None) -> bool:
    """Return True if the 'Declared-vs-computed' item appears in Section 6."""
    section = build_not_examined_section(
        compile_output, _CFG, declared_f5_findings=findings
    )
    return any(
        item.startswith("Declared-vs-computed F5 comparison")
        for item in section.items
    )


# ---------------------------------------------------------------------------
# (a) Findings present — render + Not-Examined suppression
# ---------------------------------------------------------------------------

class TestWithFindings:
    def test_render_returns_nonempty_string(self):
        """render_declared_f5_section returns a non-empty string when findings exist."""
        section = build_declared_f5_section(_COMPILE_WITH_FINDINGS)
        text = render_declared_f5_section(section)
        assert text != ""

    def test_render_contains_header(self):
        """Output starts with the section header."""
        section = build_declared_f5_section(_COMPILE_WITH_FINDINGS)
        text = render_declared_f5_section(section)
        assert "Declared-vs-Computed F5 Comparison" in text

    def test_render_contains_box1_row(self):
        """box_1 finding appears in the text dump."""
        section = build_declared_f5_section(_COMPILE_WITH_FINDINGS)
        text = render_declared_f5_section(section)
        assert "box_1" in text

    def test_render_contains_check_b(self):
        """Check B tag appears in the text dump."""
        section = build_declared_f5_section(_COMPILE_WITH_FINDINGS)
        text = render_declared_f5_section(section)
        assert "[B]" in text

    def test_render_contains_delta(self):
        """Delta value for box_1 appears in the text dump."""
        section = build_declared_f5_section(_COMPILE_WITH_FINDINGS)
        text = render_declared_f5_section(section)
        assert "+2000" in text or "2000" in text

    def test_not_examined_suppresses_declared_f5_line(self):
        """When findings are present, Section 6 omits the placeholder."""
        findings = _COMPILE_WITH_FINDINGS["declared_f5_findings"]
        assert not _decl_f5_item_present(_COMPILE_WITH_FINDINGS, findings)

    def test_not_examined_retains_other_items(self):
        """Other Section 6 items are unaffected by suppression."""
        findings = _COMPILE_WITH_FINDINGS["declared_f5_findings"]
        text = _not_examined_text(_COMPILE_WITH_FINDINGS, findings)
        assert "manual journal" in text
        assert "partial-exemption" in text
        assert "export evidence" in text

    def test_check_a_render_shows_rule(self):
        """Check A finding renders its rule string."""
        section = build_declared_f5_section(_COMPILE_WITH_CHECK_A)
        text = render_declared_f5_section(section)
        assert "[A]" in text
        assert "box_4" in text

    def test_build_section_returns_correct_count(self):
        """build_declared_f5_section preserves all finding dicts."""
        section = build_declared_f5_section(_COMPILE_WITH_FINDINGS)
        assert len(section.findings) == 2

    def test_build_section_from_check_a(self):
        """build_declared_f5_section works for Check A findings."""
        section = build_declared_f5_section(_COMPILE_WITH_CHECK_A)
        assert len(section.findings) == 1
        assert section.findings[0]["check"] == "A"


# ---------------------------------------------------------------------------
# (b) No findings — render noop + Not-Examined intact
# ---------------------------------------------------------------------------

class TestWithoutFindings:
    def test_render_returns_empty_string_when_no_findings(self):
        """render_declared_f5_section returns '' when findings list is empty."""
        section = build_declared_f5_section(_COMPILE_NO_FINDINGS)
        assert render_declared_f5_section(section) == ""

    def test_render_returns_empty_string_for_empty_section(self):
        """Direct DeclaredF5Section(findings=[]) also returns ''."""
        section = DeclaredF5Section(findings=[])
        assert render_declared_f5_section(section) == ""

    def test_not_examined_retains_declared_f5_line_when_no_findings(self):
        """Section 6 keeps the placeholder when no findings were produced."""
        assert _decl_f5_item_present(_COMPILE_NO_FINDINGS, [])

    def test_not_examined_retains_line_with_none_findings(self):
        """Passing declared_f5_findings=None also preserves the placeholder."""
        assert _decl_f5_item_present(_COMPILE_NO_FINDINGS, None)

    def test_not_examined_retains_line_no_arg(self):
        """Calling build_not_examined_section without the kwarg preserves the placeholder."""
        section = build_not_examined_section(_COMPILE_NO_FINDINGS, _CFG)
        assert any(
            item.startswith("Declared-vs-computed F5 comparison")
            for item in section.items
        )

    def test_section_6_item_count_unchanged_vs_constants(self):
        """With no findings and no anomalies, item count equals NOT_EXAMINED_ITEMS."""
        section = build_not_examined_section(_COMPILE_NO_FINDINGS, _CFG)
        assert len(section.items) == len(NOT_EXAMINED_ITEMS)

    def test_section_6_item_count_decreases_by_one_with_findings(self):
        """With findings, item count is NOT_EXAMINED_ITEMS minus the suppressed line."""
        findings = _COMPILE_WITH_FINDINGS["declared_f5_findings"]
        section = build_not_examined_section(
            _COMPILE_WITH_FINDINGS, _CFG, declared_f5_findings=findings
        )
        assert len(section.items) == len(NOT_EXAMINED_ITEMS) - 1
