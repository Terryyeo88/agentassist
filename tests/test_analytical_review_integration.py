"""
Hermetic tests for T2.17b — T2.17 fluctuation detection wired into the
T2.16 Annual Analytical Review section.

All tests are pure Python — no SAP calls, no live data, no anthropic import.

Coverage:
    [FQ1] filter_populated_quarters: all-zero quarter excluded
    [FQ2] filter_populated_quarters: quarter with only box_5 non-zero retained
    [FQ3] filter_populated_quarters: empty input → empty output
    [FL1] fluctuation findings only from populated quarters (Q4 all-zero excluded)
    [FL2] populated-quarter movements produce the expected findings
    [FL3] fluctuation findings use candidate language (ASK §1.3a, "non-regulatory")
    [FS1] AnalyticalReviewSection has fluctuation_findings field (list)
    [FS2] build_analytical_review_section passes fluctuation_findings from pass output
    [FS3] build_analytical_review_section with show=False produces empty fluctuation_findings
    [FR1] render_analytical_review_section includes 1.3a heading when findings present
    [FR2] render_analytical_review_section includes "no material" text when findings empty
    [FE1] PDF renders without error when fluctuation_findings populated
    [FE2] F5 boxes unchanged: AnalyticalReviewSection never mutates quarter_boxes values
"""
from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest

from orchestrator.check_analytical_review import (
    QuarterBoxes,
    filter_populated_quarters,
)
from orchestrator.check_period_fluctuation import FluctuationFinding
from report.render import render_analytical_review_section, render_pdf
from report.report import ReportModel, build_report
from report.contract import load_compile_output
from report.sections import AnalyticalReviewSection, build_analytical_review_section
from config.loader import ClientConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _qb(ps, pe, b1, b2, b3, b5) -> QuarterBoxes:
    return QuarterBoxes(
        period_start=ps, period_end=pe,
        box_1=Decimal(str(b1)), box_2=Decimal(str(b2)),
        box_3=Decimal(str(b3)), box_5=Decimal(str(b5)),
    )


def _ff(box, fps, fpe, tps, tpe, pct, desc="candidate for review") -> FluctuationFinding:
    return FluctuationFinding(
        box=box,
        from_period_start=fps, from_period_end=fpe,
        to_period_start=tps, to_period_end=tpe,
        pct_movement=pct,
        description=desc,
    )


_POPULATED_QUARTERS = [
    _qb("2024-01-01", "2024-03-31", 228163.35, 0, 0, 93666.97),
    _qb("2024-04-01", "2024-06-30", 379963.76, 0, 0, 216027.82),
    _qb("2024-07-01", "2024-09-30", 369589.97, 10000, 6000, 191077.76),
    _qb("2024-10-01", "2024-12-31", 0, 0, 0, 0),   # all-zero Q4
]

_FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"


def _make_cfg(**overrides) -> ClientConfig:
    base = dict(
        client_id="sbodemosg",
        client_name="SBODEMOSG Demo",
        gst_registration_number="M12345678X",
        applicable_gst_rate=0.07,
        service_layer_url="https://fake",
        company_db="SBODEMOSG",
        username="manager",
        password="manager",
        ssl_verify=False,
        fiscal_year_start_month=1,
        custom_vat_groups={},
        completeness_threshold=0.1,
        reviewer_name="Terry Yeo",
        firm_name="AgentAssist Pte Ltd",
    )
    base.update(overrides)
    return ClientConfig(**base)


# ---------------------------------------------------------------------------
# [FQ] filter_populated_quarters
# ---------------------------------------------------------------------------

def test_fq1_all_zero_quarter_excluded():
    """[FQ1] A quarter with box_1=box_2=box_3=box_5=0 is excluded."""
    quarters = [
        _qb("2024-01-01", "2024-03-31", 100, 0, 0, 50),
        _qb("2024-10-01", "2024-12-31", 0, 0, 0, 0),
    ]
    result = filter_populated_quarters(quarters)
    assert len(result) == 1
    assert result[0]["period_start"] == "2024-01-01"


def test_fq2_quarter_with_only_box5_nonzero_retained():
    """[FQ2] A quarter with box_1/2/3=0 but box_5 non-zero is populated."""
    quarters = [
        _qb("2024-01-01", "2024-03-31", 0, 0, 0, 93666.97),
    ]
    result = filter_populated_quarters(quarters)
    assert len(result) == 1


def test_fq3_empty_input_returns_empty():
    """[FQ3] Empty input list → empty output."""
    assert filter_populated_quarters([]) == []


# ---------------------------------------------------------------------------
# [FL] Fluctuation findings from populated quarters
# ---------------------------------------------------------------------------

def test_fl1_q4_all_zero_excluded_no_minus100_artefacts():
    """[FL1] filter+detect on demo quarters: Q4 all-zero excluded, no -100% artefacts."""
    from orchestrator.check_period_fluctuation import detect_period_fluctuations

    populated = filter_populated_quarters(_POPULATED_QUARTERS)
    assert len(populated) == 3, "Q4 should be filtered out"
    # Last populated quarter is Q3; no Q4 → no -100% findings for Q3→Q4
    findings = detect_period_fluctuations(populated)
    descriptions = [f.description for f in findings]
    assert not any("-100" in d for d in descriptions), (
        "No -100% artefact findings expected when Q4 is excluded"
    )


def test_fl2_expected_four_findings_from_demo_quarters():
    """[FL2] filter+detect on FY2024 demo data produces exactly the 4 expected findings."""
    from orchestrator.check_period_fluctuation import detect_period_fluctuations

    populated = filter_populated_quarters(_POPULATED_QUARTERS)
    findings = detect_period_fluctuations(populated)

    assert len(findings) == 4, (
        f"Expected exactly 4 fluctuation findings, got {len(findings)}: "
        + str([(f.box, f.pct_movement) for f in findings])
    )

    # Q1→Q2 box_1: large positive (>50%)
    f_q1q2_b1 = next((f for f in findings
                      if f.box == "box_1" and f.from_period_start == "2024-01-01"), None)
    assert f_q1q2_b1 is not None, "Q1→Q2 box_1 finding missing"
    assert f_q1q2_b1.pct_movement is not None and f_q1q2_b1.pct_movement > Decimal("50")

    # Q1→Q2 box_5: large positive (>50%)
    f_q1q2_b5 = next((f for f in findings
                      if f.box == "box_5" and f.from_period_start == "2024-01-01"), None)
    assert f_q1q2_b5 is not None, "Q1→Q2 box_5 finding missing"
    assert f_q1q2_b5.pct_movement is not None and f_q1q2_b5.pct_movement > Decimal("50")

    # Q2→Q3 box_2: from=0 surfaced finding (pct_movement=None)
    f_q2q3_b2 = next((f for f in findings
                      if f.box == "box_2" and f.from_period_start == "2024-04-01"), None)
    assert f_q2q3_b2 is not None, "Q2→Q3 box_2 finding missing"
    assert f_q2q3_b2.pct_movement is None

    # Q2→Q3 box_3: from=0 surfaced finding (pct_movement=None)
    f_q2q3_b3 = next((f for f in findings
                      if f.box == "box_3" and f.from_period_start == "2024-04-01"), None)
    assert f_q2q3_b3 is not None, "Q2→Q3 box_3 finding missing"
    assert f_q2q3_b3.pct_movement is None


def test_fl3_fluctuation_findings_have_candidate_language():
    """[FL3] FluctuationFinding descriptions reference ASK §1.3a and non-regulatory."""
    from orchestrator.check_period_fluctuation import detect_period_fluctuations

    populated = filter_populated_quarters(_POPULATED_QUARTERS)
    findings = detect_period_fluctuations(populated)
    assert findings, "Need at least one finding to check language"
    for f in findings:
        desc = f.description.lower()
        assert "1.3a" in desc, f"ASK §1.3a not in description: {f.description!r}"
        assert "non-regulatory" in desc, f"'non-regulatory' not in description: {f.description!r}"


# ---------------------------------------------------------------------------
# [FS] AnalyticalReviewSection — field and builder
# ---------------------------------------------------------------------------

def test_fs1_analytical_review_section_has_fluctuation_findings_field():
    """[FS1] AnalyticalReviewSection dataclass has a fluctuation_findings field."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(AnalyticalReviewSection)}
    assert "fluctuation_findings" in fields, (
        "AnalyticalReviewSection is missing 'fluctuation_findings' field"
    )


def test_fs2_build_analytical_review_section_passes_fluctuation_findings():
    """[FS2] builder passes fluctuation_findings list from pass output dict."""
    ff = _ff("box_1", "2024-01-01", "2024-03-31", "2024-04-01", "2024-06-30",
             Decimal("66.5327"), "standard-rated supplies: candidate for review per ASK §1.3a.")
    data = {
        "fy_start": "2024-01-01",
        "fy_end": "2024-12-31",
        "quarter_boxes": [],
        "fy_box_4": "500",
        "fy_box_5": "250",
        "ratio": "0.5000",
        "findings": [],
        "fluctuation_findings": [ff],
    }
    section = build_analytical_review_section(data, show=True)
    assert len(section.fluctuation_findings) == 1
    assert section.fluctuation_findings[0].box == "box_1"


def test_fs3_build_with_show_false_produces_empty_fluctuation_findings():
    """[FS3] show=False → fluctuation_findings is empty list."""
    section = build_analytical_review_section(None, show=False)
    assert section.fluctuation_findings == []


# ---------------------------------------------------------------------------
# [FR] Render helpers
# ---------------------------------------------------------------------------

def test_fr1_render_includes_fluctuation_heading_when_findings_present():
    """[FR1] render_analytical_review_section includes ASK 1.3a heading when findings exist."""
    ff = _ff("box_1", "2024-01-01", "2024-03-31", "2024-04-01", "2024-06-30",
             Decimal("66.5327"),
             "standard-rated supplies (Box 1): 2024-01-01–2024-03-31 → 2024-04-01–2024-06-30: "
             "movement +66.5327% (from 228163.35 to 379963.76). "
             "Candidate for reviewer explanation per ASK §1.3a. "
             "Surfacing threshold: ±50% (non-regulatory tuning parameter, not an IRAS rule).")
    section = AnalyticalReviewSection(
        show=True,
        fy_start="2024-01-01", fy_end="2024-12-31",
        quarter_boxes=[], fy_box_4="500000", fy_box_5="250000",
        ratio="0.5000", findings=[],
        fluctuation_findings=[ff],
    )
    text = render_analytical_review_section(section)
    assert "1.3a" in text, f"'1.3a' not found in render output:\n{text}"


def test_fr2_render_includes_no_material_text_when_findings_empty():
    """[FR2] render_analytical_review_section reports 'no material' when findings empty."""
    section = AnalyticalReviewSection(
        show=True,
        fy_start="2024-01-01", fy_end="2024-12-31",
        quarter_boxes=[], fy_box_4="500000", fy_box_5="250000",
        ratio="0.5000", findings=[],
        fluctuation_findings=[],
    )
    text = render_analytical_review_section(section)
    assert "no material" in text.lower(), (
        f"Expected 'no material' in render output:\n{text}"
    )


# ---------------------------------------------------------------------------
# [FE] End-to-end isolation
# ---------------------------------------------------------------------------

def test_fe1_pdf_renders_with_fluctuation_findings(tmp_path):
    """[FE1] ReportModel with fluctuation_findings renders a valid PDF."""
    raw = load_compile_output(_FIXTURE)
    cfg = _make_cfg()
    model = build_report(raw, cfg, generated_at=_GENERATED_AT)

    ff = _ff("box_1", "2024-01-01", "2024-03-31", "2024-04-01", "2024-06-30",
             Decimal("66.5327"),
             "standard-rated supplies (Box 1): candidate per ASK §1.3a. "
             "Surfacing threshold: ±50% (non-regulatory tuning parameter, not an IRAS rule).")
    ar = AnalyticalReviewSection(
        show=True,
        fy_start="2024-01-01", fy_end="2024-12-31",
        quarter_boxes=[], fy_box_4="993717", fy_box_5="500772",
        ratio="0.5040", findings=[],
        fluctuation_findings=[ff],
    )
    import dataclasses
    model_with_ar = dataclasses.replace(model, analytical_review=ar)

    out = tmp_path / "test_ar_fluctuation.pdf"
    render_pdf(model_with_ar, out)
    assert out.exists()
    assert out.stat().st_size > 5 * 1024
    assert out.read_bytes()[:4] == b"%PDF"


def test_fe2_quarter_boxes_not_mutated_by_filter():
    """[FE2] filter_populated_quarters does not mutate the input list."""
    original = copy.deepcopy(_POPULATED_QUARTERS)
    filter_populated_quarters(_POPULATED_QUARTERS)
    assert _POPULATED_QUARTERS == original
