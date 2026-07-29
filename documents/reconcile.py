"""documents/reconcile.py — PDF-vs-listing reconciliation, J+ candidate surfacing.

Public API:
    reconcile(extracted, line_item, period_start, period_end) -> list[DocumentCandidate]

The caller has already joined on doc_num; this module compares one matched pair
and emits DocumentCandidate items for a human reviewer to adjudicate.

Framing invariant
-----------------
Every output is a CANDIDATE for review — never an assertion of an error.
The four checks are deterministic, but they operate on probabilistically-extracted
values (from the born-digital or multimodal ingestion path), so the strongest
determinability claim they can carry is J+ (documents showing a discrepancy that
warrants specialist review), except for the period check which is labelled
D+ conditional on the extraction accuracy of the invoice date.

All messages are phrased "Consider reviewing whether…" so a reviewer can
adjudicate without the output pre-judging the outcome.

Containment invariant
---------------------
This module imports nothing from orchestrator/, audit_bundle/, boxes, gates, or
the calculate path.  It is pure Python (no network, no anthropic SDK).
Reconciliation candidates never enter Layer 1 (the F5 boxes) or the five gates;
they are a separate output stream handled by the caller.

Checks emitted
--------------
check_id                  | what is compared
--------------------------+--------------------------------------------------
gst_amount_mismatch       | extracted.gst_amount vs line_item["tax_total"]
correct_period            | extracted.invoice_date vs [period_start, period_end]
total_inconsistency       | extracted total vs (extracted excl + extracted GST)
reg11_supplier_gst_absent | fields_present["supplier_gst_regno"] is False

Note on reg11_supplier_gst_absent:
  This is a DOCUMENT check — the GST reg number does not appear on the invoice
  face.  It is DISTINCT from the deterministic NO_GST_REG check produced by the
  detect step (which reads SAP FederalTaxID).  Different check_id, different
  evidence source, different remediation action.  Do not merge or conflate them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from documents.ingest import ExtractedInvoice

# ---------------------------------------------------------------------------
# Tolerance — two values that agree to the cent are considered matching.
# 0.01 is the smallest meaningful monetary discrepancy (one Singapore cent).
# ---------------------------------------------------------------------------
AMOUNT_TOLERANCE: float = 0.01


def coerce_doc_num(value):
    """Tolerant doc_num coercion (T-E(2) widening; Gate-2 proved byte-identical seals
    for int inputs — A1==B 66d0a4fc…, A1-show==B-show-widened 2b8bdd0b…).

    An int returns UNCHANGED; a numeric string coerces to int (the historical SAP
    behaviour); a non-numeric reference ("BILL-3002", the Xero path) passes through
    VERBATIM — the full reference is the document's own identity (D-34/D-42).
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


# ---------------------------------------------------------------------------
# Output data model
# ---------------------------------------------------------------------------

@dataclass
class DocumentCandidate:
    # int on the SAP path; the verbatim reference string on the Xero path (T-E(2)).
    doc_num: "int | str"
    check_id: str
    severity: str
    message: str
    extracted_value: Any
    listing_value: Any
    extraction_source: Literal["born_digital", "multimodal"]
    determinability: str
    validation_status: str = "unvalidated"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reconcile(
    extracted: ExtractedInvoice,
    line_item: dict,
    period_start: str,
    period_end: str,
) -> list[DocumentCandidate]:
    """Compare one matched (extracted PDF, SAP line-item) pair and emit candidates.

    Args:
        extracted:    Result of documents.ingest.ingest() for one invoice PDF.
        line_item:    One dict from reasoning/sap_lines._extract_si_lines() with keys:
                      doc_num, doc_type, doc_date, card_name, line_index, vat_group,
                      line_description, line_total, tax_total.
        period_start: Audit period start date, YYYY-MM-DD inclusive.
        period_end:   Audit period end date, YYYY-MM-DD inclusive.

    Returns:
        List of DocumentCandidate items (empty when all checks pass).
        Every candidate carries validation_status="unvalidated" and is framed
        as a candidate for human review, never as a compliance assertion.
    """
    candidates: list[DocumentCandidate] = []
    doc_num = coerce_doc_num(line_item["doc_num"])
    src = extracted.source

    def _make(
        check_id: str,
        severity: str,
        message: str,
        ev: Any,
        lv: Any,
        det: str,
    ) -> DocumentCandidate:
        return DocumentCandidate(
            doc_num=doc_num,
            check_id=check_id,
            severity=severity,
            message=message,
            extracted_value=ev,
            listing_value=lv,
            extraction_source=src,
            determinability=det,
            validation_status="unvalidated",
        )

    # ── Check 1: gst_amount_mismatch ─────────────────────────────────────────
    # Compares the GST amount on the invoice face against the SAP-posted
    # TaxTotal.  A discrepancy may indicate a data-entry or coding error on
    # either side; both possibilities remain open for the reviewer.
    if extracted.gst_amount is not None:
        pdf_gst = extracted.gst_amount
        sap_gst = float(line_item["tax_total"])
        diff = abs(pdf_gst - sap_gst)
        if diff > AMOUNT_TOLERANCE:
            candidates.append(_make(
                check_id="gst_amount_mismatch",
                severity="MEDIUM",
                message=(
                    f"Consider reviewing whether the GST amount on the invoice face "
                    f"({pdf_gst:.2f}) agrees with the SAP-posted tax total "
                    f"({sap_gst:.2f}); the difference of {diff:.2f} may indicate an "
                    f"input or coding error."
                ),
                ev=pdf_gst,
                lv=sap_gst,
                det="J+",
            ))

    # ── Check 2: correct_period ───────────────────────────────────────────────
    # Compares the invoice date extracted from the PDF face against the audit
    # period bounds.  An out-of-period invoice included in the run is a period
    # attribution issue.  Determinability is D+ conditional on extraction
    # accuracy: if the date was misread the check itself may be unreliable.
    if extracted.invoice_date is not None:
        d = extracted.invoice_date
        if d < period_start or d > period_end:
            candidates.append(_make(
                check_id="correct_period",
                severity="MEDIUM",
                message=(
                    f"Consider reviewing whether this invoice (date {d}) falls within "
                    f"the audit period {period_start} to {period_end}; if outside the "
                    f"period, it should not be included in this F5 return."
                ),
                ev=d,
                lv=f"{period_start} to {period_end}",
                det="D+ (conditional on extraction)",
            ))

    # ── Check 3: total_inconsistency ─────────────────────────────────────────
    # Checks the PDF's OWN arithmetic: does excl. GST + GST amount = total?
    # This check does NOT reference the SAP listing — it is an internal
    # consistency check of the extracted values on the document face.
    if (
        extracted.total_excl_gst is not None
        and extracted.gst_amount is not None
        and extracted.total_incl_gst is not None
    ):
        expected_total = extracted.total_excl_gst + extracted.gst_amount
        actual_total = extracted.total_incl_gst
        diff = abs(actual_total - expected_total)
        if diff > AMOUNT_TOLERANCE:
            candidates.append(_make(
                check_id="total_inconsistency",
                severity="MEDIUM",
                message=(
                    f"Consider reviewing whether the invoice total ({actual_total:.2f}) "
                    f"is arithmetically consistent with its components (excl. GST "
                    f"{extracted.total_excl_gst:.2f} + GST {extracted.gst_amount:.2f} "
                    f"= {expected_total:.2f}); the discrepancy of {diff:.2f} may "
                    f"indicate an error on the invoice face."
                ),
                ev=actual_total,
                lv=expected_total,
                det="J+",
            ))

    # ── Check 4: reg11_supplier_gst_absent ───────────────────────────────────
    # Document check: the supplier's GST registration number does not appear
    # on the invoice face (IRAS para 7.1.4(d)).  Without this particular, the
    # input tax claim under Regulation 11 may be disallowable.
    #
    # DISTINCT from the deterministic NO_GST_REG check emitted by the detect
    # step, which reads SAP FederalTaxID.  That check is evidence that SAP
    # has no registered number on record.  This check is evidence that the
    # physical invoice document lacks the mandatory particular — different
    # evidence source, different remediation action.
    if not extracted.fields_present.get("supplier_gst_regno", True):
        candidates.append(_make(
            check_id="reg11_supplier_gst_absent",
            severity="HIGH",
            message=(
                "Consider reviewing whether this invoice satisfies IRAS para "
                "7.1.4(d): the supplier's GST registration number does not appear "
                "on the invoice face. Without this particular, the input tax claim "
                "under Regulation 11 may be disallowable."
            ),
            ev=extracted.supplier_gst_regno,
            lv=None,
            det="J+",
        ))

    return candidates
