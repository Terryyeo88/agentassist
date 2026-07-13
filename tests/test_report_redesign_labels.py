"""
Report redesign (Avinash feedback) — Change 1: internal error codes -> IRAS labels.

Presentation-layer only. Section 3 (Findings) and Section 4 (Cross-Findings) must
show each finding's existing ``appendix1_category`` (IRAS ASK Appendix 1 wording,
already computed in report.enrich) as the PRIMARY human label, keeping the raw
``error_code`` as a small parenthetical tag for auditor traceability — e.g.
"Wrong classification of supplies made (E1)".

These tests are RED before the render redesign: today the "Code" column renders the
bare ``error_code`` ("E1", "NO_GST_REG") with no IRAS wording and no "(CODE)" tag.

No model change: the box figures and enrich output are untouched (BOX-ISOLATION /
Invariant 3+4). Reuses the same fixture as tests/test_sections.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import report.render as R
from config.loader import ClientConfig
from report.contract import load_compile_output
from report.report import build_report

FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
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


def _walk(node, out: list) -> None:
    """Collect plain text from every Paragraph in a flowable tree (Tables,
    KeepTogether, nested cell lists, and bare strings included)."""
    from reportlab.platypus import Paragraph, Table
    from reportlab.platypus.flowables import KeepTogether

    if isinstance(node, Paragraph):
        out.append(node.getPlainText())
    elif isinstance(node, Table):
        for row in node._cellvalues:
            for cell in row:
                _walk(cell, out)
    elif isinstance(node, KeepTogether):
        for c in node._content:
            _walk(c, out)
    elif isinstance(node, (list, tuple)):
        for c in node:
            _walk(c, out)
    elif isinstance(node, str):
        out.append(node)


def _texts_from(fn, model) -> list[str]:
    story: list = []
    fn(model, story)
    out: list[str] = []
    _walk(story, out)
    return out


@pytest.fixture(scope="module")
def raw_data() -> dict:
    return load_compile_output(FIXTURE)


@pytest.fixture(scope="module")
def model(raw_data):
    return build_report(raw_data, _make_cfg(), generated_at=_GENERATED_AT)


# ── Section 3 findings: IRAS wording primary, raw code as (CODE) tag ──────────

class TestFindingsLabels:
    def test_e1_shows_iras_wording_as_primary_label(self, model):
        texts = _texts_from(R._findings, model)
        assert any("Wrong classification of supplies made" in t for t in texts), (
            "Section 3 must show the E1 Appendix-1 wording, not the bare code"
        )

    def test_e1_keeps_raw_code_as_parenthetical_tag(self, model):
        texts = _texts_from(R._findings, model)
        assert any("(E1)" in t for t in texts), (
            "raw error_code must remain discoverable as a (E1) tag"
        )

    def test_no_gst_reg_shows_iras_wording_and_code_tag(self, model):
        texts = _texts_from(R._findings, model)
        assert any("non-GST registered suppliers" in t for t in texts), (
            "Section 3 must show the NO_GST_REG Appendix-1 wording"
        )
        assert any("(NO_GST_REG)" in t for t in texts), (
            "NO_GST_REG raw code must remain discoverable as a tag"
        )

    def test_bare_code_not_shown_without_wording(self, model):
        # The old behaviour rendered a standalone cell whose entire text was the
        # bare code. After the redesign no cell should be exactly "E1".
        texts = [t.strip() for t in _texts_from(R._findings, model)]
        assert "E1" not in texts, "bare 'E1' cell must be replaced by IRAS wording + tag"


# ── Section 4 cross-findings: same primary-wording + code-tag treatment ───────

class TestCrossFindingLabels:
    def test_cross_findings_show_wording_and_code_tag(self, model):
        texts = _texts_from(R._cross_findings, model)
        # doc 605 carries E2 + NO_GST_REG in the SBODEMOSG fixture.
        assert any("non-GST registered suppliers" in t for t in texts), (
            "cross-findings must show IRAS wording, not bare codes"
        )
        assert any("(NO_GST_REG)" in t for t in texts) and any("(E2" in t for t in texts), (
            "cross-findings must keep raw codes as parenthetical tags"
        )


# ── BOX-ISOLATION: relabelling must not touch box figures ─────────────────────

class TestBoxIsolationUnderLabels:
    def test_box_values_byte_identical_to_compile_output(self, raw_data, model):
        assert model.f5_boxes.boxes == raw_data["calculate"]["boxes"], (
            "label redesign must not recompute or alter any F5 box value"
        )
