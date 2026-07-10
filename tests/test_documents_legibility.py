"""tests/test_documents_legibility.py — T2.14 document legibility gate.

RED-first tests for the per-document legibility gate that runs BETWEEN ingest()
and reconcile() in run_documents_pass. An illegible document is routed to
"manual review required" and is NOT fed to reconcile, so no confident-wrong
candidate is surfaced from an unreadable PDF.

Three-times rule (Invariant 7): the legibility rule is stated in the module
docstring/message (prompt), in documents/legibility.py (code), and here (test).

Approved leans exercised (Terry to flip in the PR):
  Q1 — max_null_fields=3; the null-count rule applies to MULTIMODAL extraction
       only. Born-digital is governed by key-field absence.
  Q2 — key fields are EXACTLY gst_amount + invoice_date; supplier_gst_regno
       absence is NOT illegibility (it is a legitimate reconcile trigger).
  Q3 — a regex-passing but calendar-invalid date (2024-13-45) is illegible;
       GST-ratio plausibility stays in reconcile (out of scope here).
  Q4/Q6 — the manual-review row is a coverage-style row on the ungated
       Deterministic Check Coverage surface, NOT a DocumentCandidate behind the
       show_ai_candidates gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from config.loader import ClientConfig
from documents.doc_pass import run_documents_pass
from documents.ingest import ExtractedInvoice
from documents.legibility import (
    KEY_FIELDS,
    LEGIBLE,
    MANUAL_REVIEW_REQUIRED,
    MAX_NULL_FIELDS,
    LegibilityStatus,
    assess_legibility,
)
from documents.reconcile import reconcile
from report.render import render_check_coverage_section
from report.report import build_report

# ---------------------------------------------------------------------------
# Shared constants and builders
# ---------------------------------------------------------------------------

_CHAIN_FIXTURE = Path(__file__).parent / "fixtures" / "chain-run-sample.json"
_GENERATED_AT = "2026-06-01T09:11:28+00:00"
_PERIOD_START = "2024-07-01"
_PERIOD_END = "2024-09-30"

_ALL_FIELDS = (
    "supplier_name", "supplier_gst_regno", "invoice_number", "invoice_date",
    "total_excl_gst", "gst_rate", "gst_amount", "total_incl_gst",
)


def _legible_invoice(**overrides) -> ExtractedInvoice:
    """A fully-legible born-digital ExtractedInvoice; override any field to perturb."""
    base = dict(
        supplier_name="TechSupply Solutions Pte Ltd",
        supplier_gst_regno="M12345678X",
        invoice_number="INV-3001",
        invoice_date="2024-07-15",
        total_excl_gst=5000.0,
        gst_rate="7%",
        gst_amount=350.0,
        total_incl_gst=5350.0,
        source="born_digital",
        validation_status="unvalidated",
    )
    base.update(overrides)
    vals = {k: base[k] for k in _ALL_FIELDS}
    return ExtractedInvoice(
        **vals,
        source=base["source"],
        validation_status=base["validation_status"],
        fields_present={k: v is not None for k, v in vals.items()},
    )


def _line_item(doc_num: int = 3001) -> dict:
    return dict(
        doc_num=doc_num,
        doc_type="purchase_invoice",
        doc_date="2024-07-15",
        card_name="TechSupply Solutions Pte Ltd",
        line_index=0,
        vat_group="SI",
        line_description="Professional IT Consulting Services - July 2024",
        line_total=5000.0,
        tax_total=350.0,
    )


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


class _StubProvider:
    """Returns a dummy path for one doc_num; None otherwise. ingest() is patched,
    so the path is never opened."""

    def __init__(self, doc_num: int) -> None:
        self._doc = doc_num

    def get_document(self, doc_num: int):
        return Path(f"stub-{doc_num}.pdf") if doc_num == self._doc else None


# ---------------------------------------------------------------------------
# assess_legibility — key-field absence (Q2)
# ---------------------------------------------------------------------------

def test_gst_amount_absent_routes_to_manual_review():
    status = assess_legibility(_legible_invoice(gst_amount=None))
    assert status.level == MANUAL_REVIEW_REQUIRED
    assert status.needs_manual_review is True
    assert "gst_amount" in status.reason


def test_invoice_date_absent_routes_to_manual_review():
    status = assess_legibility(_legible_invoice(invoice_date=None))
    assert status.level == MANUAL_REVIEW_REQUIRED
    assert "invoice_date" in status.reason


def test_supplier_gst_regno_absent_is_not_illegibility():
    # Q2 guard: absence of the GST reg number is a legitimate reg11 reconcile
    # trigger, NOT an illegibility signal — the doc must stay legible.
    status = assess_legibility(_legible_invoice(supplier_gst_regno=None))
    assert status.level == LEGIBLE


def test_key_fields_are_exactly_gst_amount_and_invoice_date():
    assert KEY_FIELDS == ("gst_amount", "invoice_date")
    assert "supplier_gst_regno" not in KEY_FIELDS
    assert MAX_NULL_FIELDS == 3


# ---------------------------------------------------------------------------
# assess_legibility — multimodal null-count (Q1)
# ---------------------------------------------------------------------------

def test_multimodal_over_threshold_nulls_routes_to_manual_review():
    # 4 of 8 fields null (> 3), key fields kept present so the null-count rule
    # is the isolated trigger.
    inv = _legible_invoice(
        source="multimodal",
        supplier_name=None, supplier_gst_regno=None,
        invoice_number=None, gst_rate=None,
    )
    status = assess_legibility(inv)
    assert status.level == MANUAL_REVIEW_REQUIRED
    assert "null" in status.reason.lower()


def test_multimodal_at_threshold_is_legible():
    # Exactly 3 nulls — at the threshold, not over it — stays legible.
    inv = _legible_invoice(
        source="multimodal",
        supplier_name=None, supplier_gst_regno=None, invoice_number=None,
    )
    assert assess_legibility(inv).level == LEGIBLE


def test_born_digital_over_threshold_nulls_but_keys_present_is_legible():
    # Q1: the null-count rule is multimodal-only. A born-digital doc with 4
    # nulls but both key fields present is NOT routed to manual review.
    inv = _legible_invoice(
        source="born_digital",
        supplier_name=None, supplier_gst_regno=None,
        invoice_number=None, gst_rate=None,
    )
    assert assess_legibility(inv).level == LEGIBLE


# ---------------------------------------------------------------------------
# assess_legibility — calendar validity (Q3) and legible baseline
# ---------------------------------------------------------------------------

def test_calendar_invalid_date_routes_to_manual_review():
    status = assess_legibility(_legible_invoice(invoice_date="2024-13-45"))
    assert status.level == MANUAL_REVIEW_REQUIRED
    assert "2024-13-45" in status.reason


def test_valid_calendar_date_outside_period_is_legible():
    # 2024-10-05 is a real date (mirrors fixture 3006 date_outside_period): the
    # legibility gate is structural, not a period check — reconcile handles period.
    assert assess_legibility(_legible_invoice(invoice_date="2024-10-05")).level == LEGIBLE


def test_clean_invoice_is_legible_and_reconcile_unchanged():
    assert assess_legibility(_legible_invoice()).level == LEGIBLE
    # A legible GST mismatch still produces its reconcile candidate (unchanged).
    inv = _legible_invoice(gst_amount=900.0)
    assert assess_legibility(inv).level == LEGIBLE
    direct = reconcile(inv, _line_item(), _PERIOD_START, _PERIOD_END)
    assert any(c.check_id == "gst_amount_mismatch" for c in direct)


# ---------------------------------------------------------------------------
# LegibilityStatus honesty discipline (mirrors 2B full/degraded/unavailable)
# ---------------------------------------------------------------------------

def test_status_discipline_reason_required_for_manual_review():
    with pytest.raises(ValueError):
        LegibilityStatus(MANUAL_REVIEW_REQUIRED, "")   # non-empty reason required
    with pytest.raises(ValueError):
        LegibilityStatus(LEGIBLE, "should be empty")   # legible carries no reason
    with pytest.raises(ValueError):
        LegibilityStatus("bogus-level", "x")           # unknown level rejected


def test_coverage_row_shape_carries_manual_review_and_unvalidated():
    row = LegibilityStatus(MANUAL_REVIEW_REQUIRED, "key field(s) absent: gst_amount").as_coverage_row(3009)
    assert row["level"] == "unavailable"                       # coverage vocabulary
    assert "manual review required" in row["reason"].lower()   # DoD phrasing
    assert "3009" in row["check"]
    assert row["validation_status"] == "unvalidated"           # asserts no verdict


# ---------------------------------------------------------------------------
# Integration over run_documents_pass
# ---------------------------------------------------------------------------

def test_run_documents_pass_routes_illegible_and_skips_reconcile():
    li = _line_item(3001)
    illegible = _legible_invoice(gst_amount=None)
    rows: list = []
    with patch("documents.doc_pass.ingest", return_value=illegible):
        cands = run_documents_pass(
            [li], _StubProvider(3001), _PERIOD_START, _PERIOD_END,
            legibility_rows=rows,
        )
    assert cands == []                 # zero reconcile candidates for the illegible doc
    assert len(rows) == 1              # exactly one manual-review row
    assert rows[0]["level"] == "unavailable"
    assert "manual review required" in rows[0]["reason"].lower()
    assert "3001" in rows[0]["check"]


def test_run_documents_pass_legible_is_byte_identical_to_reconcile():
    li = _line_item(3001)
    legible = _legible_invoice(gst_amount=900.0)   # legible mismatch
    rows: list = []
    with patch("documents.doc_pass.ingest", return_value=legible):
        cands = run_documents_pass(
            [li], _StubProvider(3001), _PERIOD_START, _PERIOD_END,
            legibility_rows=rows,
        )
    direct = reconcile(legible, li, _PERIOD_START, _PERIOD_END)
    assert cands == direct             # unchanged from today's behaviour
    assert rows == []                  # no legibility row for a legible doc


def test_run_documents_pass_default_no_rows_param_still_skips_illegible():
    # Backward-compat: existing callers pass no legibility_rows. The gate still
    # protects reconcile from unreliable fields (illegible doc → no candidate).
    li = _line_item(3001)
    illegible = _legible_invoice(invoice_date=None)
    with patch("documents.doc_pass.ingest", return_value=illegible):
        cands = run_documents_pass([li], _StubProvider(3001), _PERIOD_START, _PERIOD_END)
    assert cands == []


# ---------------------------------------------------------------------------
# Surface: ungated render + box-isolation
# ---------------------------------------------------------------------------

def test_manual_review_row_renders_even_when_show_ai_candidates_false():
    raw = json.loads(_CHAIN_FIXTURE.read_text(encoding="utf-8"))
    cfg = _make_cfg()   # show_ai_candidates defaults to False
    row = LegibilityStatus(
        MANUAL_REVIEW_REQUIRED, "key field(s) absent: gst_amount"
    ).as_coverage_row(3009)
    model = build_report(
        raw, cfg, generated_at=_GENERATED_AT, document_legibility_rows=[row]
    )
    # The gated candidate stream is OFF...
    assert model.unified_candidates.show is False
    # ...but the coverage surface (ungated) carries and renders the legibility row.
    text = render_check_coverage_section(model.check_coverage)
    assert "manual review required" in text.lower()
    assert "3009" in text


def test_box_isolation_legibility_row_does_not_perturb_boxes_or_findings():
    raw = json.loads(_CHAIN_FIXTURE.read_text(encoding="utf-8"))
    cfg = _make_cfg()
    row = LegibilityStatus(
        MANUAL_REVIEW_REQUIRED, "key field(s) absent: gst_amount"
    ).as_coverage_row(3009)
    m_with = build_report(
        raw, cfg, generated_at=_GENERATED_AT, document_legibility_rows=[row]
    )
    m_without = build_report(raw, cfg, generated_at=_GENERATED_AT)
    assert m_with.f5_boxes == m_without.f5_boxes
    assert m_with.findings == m_without.findings
    assert m_with.cross_findings == m_without.cross_findings
