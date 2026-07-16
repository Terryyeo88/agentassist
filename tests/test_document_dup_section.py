"""
tests/test_document_dup_section.py — FAILING-FIRST renderer tests for the NEW
same-day duplicate-purchase surfacer section.

RED by design: report.sections.DocumentDupSection / build_document_dup_section do not
exist yet (ImportError on collection), and the four honest-status caveats are not yet
rendered anywhere in the PDF (assertion failure once the section-derivation tests pass).

build_document_dup_section mirrors render_listing_findings_section's three-state
derivation (report/sections.py:846-889):
  - document_dup_status.level == "unavailable" -> status "unavailable", reason carried;
  - else "document_dup_findings" key present   -> status "examined";
  - else key absent                            -> status "not_examined".

Hermetic: no live SAP, no anthropic. The caveat test renders a real PDF (mirrors the
pdfminer full-render proof in tests/test_report_redesign_severity_removed.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from report.sections import DocumentDupSection, build_document_dup_section


_FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"

_DUP_FINDING = {
    "check": "DUP_SAME_DAY",
    "card_name": "Acme Supplies Pte Ltd",
    "doc_total": 1200.00,
    "doc_date": "2024-08-01",
    "doc_nums": [501, 502],
    "description": (
        "Consider reviewing whether DocNums 501 and 502 (same supplier, same total, "
        "same day) represent the same purchase entered twice."
    ),
    "note": "candidate for reviewer attention",
}


# ---------------------------------------------------------------------------
# build_document_dup_section — three-state derivation
# ---------------------------------------------------------------------------

class TestBuildDocumentDupSection:

    def test_findings_present_nonempty_is_examined(self):
        co = {"document_dup_findings": [_DUP_FINDING]}
        sec = build_document_dup_section(co)
        assert isinstance(sec, DocumentDupSection)
        assert sec.status == "examined"
        assert len(sec.findings) == 1
        assert sec.findings[0]["check"] == "DUP_SAME_DAY"

    def test_findings_present_empty_is_examined(self):
        co = {"document_dup_findings": []}
        sec = build_document_dup_section(co)
        assert sec.status == "examined"
        assert sec.findings == []

    def test_key_absent_is_not_examined(self):
        sec = build_document_dup_section({})
        assert sec.status == "not_examined"

    def test_unavailable_status_carries_reason(self):
        co = {
            "document_dup_findings": None,
            "document_dup_status": {
                "level": "unavailable",
                "reason": "same-day dup check failed to run: boom",
            },
        }
        sec = build_document_dup_section(co)
        assert sec.status == "unavailable"
        assert sec.reason == "same-day dup check failed to run: boom"

    def test_read_only_over_compile_output(self):
        import copy
        co = {"document_dup_findings": [_DUP_FINDING]}
        before = copy.deepcopy(co)
        build_document_dup_section(co)
        assert co == before


# ---------------------------------------------------------------------------
# Honest-status caveats — rendered VERBATIM in the section header
# ---------------------------------------------------------------------------

class TestHonestStatusCaveats:
    """The four honest-status caveats must appear VERBATIM in the rendered report."""

    _CAVEATS = (
        "built",
        "not accuracy-validated",
        "same-day only pending a worksheet-derived window",
        "over-firing untestable pending a must-spare fixture",
    )

    def _make_cfg(self) -> Any:
        from config.loader import ClientConfig
        return ClientConfig(
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

    def _render_text(self, tmp_path: Path) -> str:
        from pdfminer.high_level import extract_text
        from report.contract import load_compile_output
        from report.render import render_pdf
        from report.report import build_report

        co = dict(load_compile_output(_FIXTURE))
        co["document_dup_findings"] = [_DUP_FINDING]

        model = build_report(co, self._make_cfg(),
                             generated_at="2026-07-16T00:00:00+00:00")
        out = tmp_path / "document_dup.pdf"
        render_pdf(model, out)
        return extract_text(str(out))

    def test_all_four_caveats_present_in_rendered_pdf(self, tmp_path):
        text = self._render_text(tmp_path)
        missing = [c for c in self._CAVEATS if c not in text]
        assert not missing, (
            f"rendered report must carry these honest-status caveats verbatim; "
            f"missing: {missing}"
        )
