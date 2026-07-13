"""
Report redesign (Avinash feedback) — Change 4: remove severity from the report.

Presentation-layer only. The rendered report must:
  * drop the HIGH/MEDIUM/LOW badge and the "Severity" column,
  * drop the "Sorted HIGH > MEDIUM > LOW" caption mention, and
  * sort the findings table by dollar impact (amount descending) for display.

The enrich-layer ``severity`` field is LEFT INTACT (internal only) — Terry owns
severity semantics; this change only stops rendering it. The model-level sort in
report.sections.build_findings_section is deliberately NOT changed (locked
test_sections.py asserts it), so the amount-descending order is a RENDER-only
re-sort via the pure helpers below.

RED before the redesign: the helpers ``_findings_display_order`` / ``_display_amount``
do not yet exist, and the findings table still renders a "Severity" header/badge.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import report.render as R
from config.loader import ClientConfig
from report.contract import load_compile_output
from report.enrich import enrich
from report.render import render_pdf
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


@pytest.fixture(scope="module")
def raw_data() -> dict:
    return load_compile_output(FIXTURE)


@pytest.fixture(scope="module")
def model(raw_data):
    return build_report(raw_data, _make_cfg(), generated_at=_GENERATED_AT)


# ── Display-order helper: amount descending ───────────────────────────────────

class TestAmountDescendingOrder:
    def test_display_order_is_amount_descending(self, model):
        for grp in model.findings.groups:
            if len(grp.findings) < 2:
                continue
            ordered = R._findings_display_order(grp.findings)
            amounts = [R._display_amount(f) for f in ordered]
            assert amounts == sorted(amounts, reverse=True), (
                "findings must be displayed largest-dollar-impact first"
            )

    def test_display_order_preserves_membership(self, model):
        for grp in model.findings.groups:
            ordered = R._findings_display_order(grp.findings)
            assert sorted(id(f) for f in ordered) == sorted(id(f) for f in grp.findings), (
                "re-sort must not add or drop findings"
            )


# ── Severity is not rendered anywhere in Section 3 ────────────────────────────

class TestSeverityNotRendered:
    def test_findings_table_has_no_severity_header(self, model):
        story: list = []
        R._findings(model, story)
        texts: list = []
        _walk(story, texts)
        assert "Severity" not in [t.strip() for t in texts], (
            "the Severity column header must be gone"
        )

    def test_no_bare_severity_badge_cells(self, model):
        story: list = []
        R._findings(model, story)
        collected: list = []
        _walk(story, collected)
        for tok in ("HIGH", "MEDIUM", "LOW"):
            assert tok not in [t.strip() for t in collected], (
                f"severity badge '{tok}' must not be rendered"
            )

    def test_caption_drops_severity_sort_language(self, model):
        story: list = []
        R._findings(model, story)
        texts: list = []
        _walk(story, texts)
        blob = " ".join(texts)
        assert "HIGH" not in blob and "MEDIUM" not in blob and "LOW" not in blob


# ── Full-render proof via pdfminer: no "Severity" anywhere in the PDF ─────────

class TestFullRenderNoSeverity:
    def test_pdf_text_has_no_severity_column(self, model, tmp_path):
        from pdfminer.high_level import extract_text

        out = tmp_path / "report.pdf"
        render_pdf(model, out)
        text = extract_text(str(out))
        assert "Severity" not in text, "rendered PDF must not contain a Severity column"


# ── enrich severity field remains computed (internal only) ────────────────────

class TestEnrichSeverityIntact:
    def test_every_finding_still_has_valid_severity(self, raw_data):
        findings = enrich(raw_data, actively_makes_exempt=False)
        for f in findings:
            assert f.severity in {"HIGH", "MEDIUM", "LOW"}, (
                "enrich severity assignment must stay intact (internal only)"
            )
