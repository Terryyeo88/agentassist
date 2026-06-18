"""feeders/extract_schema.py — canonical column ⇄ field schema for the T2.12 extract feeder.

Single source of truth for:
  * the column names a client Excel/CSV GST export is expected to carry, and
  * the canonical, typed field each column maps to — the SAME shaped records the
    deterministic checking core already consumes from the live-SAP feeder
    (``SapChainReader``).

The core reads only a small subset of the ~250-field SAP OData envelope (verified in
the T2.23 recon):

  * per document line — ``VatGroup``, ``LineTotal``, ``TaxTotal``
  * per document       — ``DocNum``, ``DocDate``, ``CardName``, ``CardCode``,
                         ``DocCurrency``, ``DocTotal`` (and ``DocumentLines``)
  * BusinessPartner    — ``FederalTaxID``
  * listing headers    — ``DocNum``, ``Series``, ``Cancelled`` (+ ``CardCode``,
                         ``NumAtCard``, ``DocTotal`` for the period purchases listing)

That subset IS the canonical contract this feeder normalises an export down to.

Tax codes are emitted VERBATIM into ``VatGroup``: normalisation stays in the checking
core's ``normalize_vat_group`` (T2.19). The feeder never re-implements it — one machine,
two feeders.

SYNTHETIC-FORMAT NOTE: the export column shape modelled here is this slice's *guess* at a
client SAP B1 GST-listing export (a combined transaction register with sales/purchase and
invoice/credit-note discriminator columns, plus a BP master and a document-number listing).
It is validated end-to-end against the frozen ground truth via a synthetic exporter, NOT
against a real client export. See the T2.12a session report.

Pure stdlib. No network, no SAP, no anthropic.
"""
from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Typed cell coercers — used BOTH to project the frozen native-typed surfaces and
# to parse export cells (always strings). Accepting either input keeps the
# projection (expected) and the reader (actual) byte-convergent across the
# native → CSV-text → native round trip.
# ---------------------------------------------------------------------------


def to_int(raw: Any) -> Optional[int]:
    """Coerce to int; blank/None → None."""
    if raw is None or raw == "":
        return None
    return int(raw)


def to_float(raw: Any) -> Optional[float]:
    """Coerce to float; blank/None → None."""
    if raw is None or raw == "":
        return None
    return float(raw)


def to_str(raw: Any) -> str:
    """Coerce to str; None → "" (a required-but-empty cell is the empty string)."""
    if raw is None:
        return ""
    return str(raw)


def to_opt_str(raw: Any) -> Optional[str]:
    """Coerce to str but PRESERVE None: blank cell / JSON null → None.

    Used for nullable fields (``NumAtCard``, ``FederalTaxID``) where None is
    semantically distinct from "" downstream (detect_dup_claims skips None
    NumAtCard; NO_GST_REG treats a missing FederalTaxID as unregistered).
    """
    if raw is None:
        return None
    s = str(raw)
    return s if s != "" else None


def ser(value: Any) -> str:
    """Serialise a typed canonical value to a stable export cell string.

    None → "" (round-trips back to None / "" via the field's parser). ``str`` on a
    Python float yields the shortest round-trippable repr, so floats survive
    text → float → text unchanged on every platform.
    """
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Export column names (the modelled client GST-export shape).
# ---------------------------------------------------------------------------

# documents.csv / "documents" sheet — line-level transaction register. One row per
# document line; header fields repeat across a document's lines.
DOC_TYPE_COL = "doc_type"      # "sales" | "purchase"
DOC_KIND_COL = "doc_kind"      # "invoice" | "credit_note"
LINE_INDEX_COL = "line_index"  # 0-based line order within the document
DOCUMENT_COLUMNS = [
    DOC_TYPE_COL, DOC_KIND_COL,
    "DocNum", "DocDate", "CardCode", "CardName", "DocCurrency", "DocTotal",
    LINE_INDEX_COL, "VatGroup", "LineTotal", "TaxTotal",
]

# business_partners.csv / "business_partners" sheet — BP master (S3).
BUSINESS_PARTNER_COLUMNS = ["CardCode", "CardName", "FederalTaxID"]

# listing.csv / "listing" sheet — document-number register for the S5 listing checks.
SCOPE_COL = "scope"  # "period" | "all"
LISTING_COLUMNS = [
    SCOPE_COL, DOC_TYPE_COL,
    "DocNum", "Series", "Cancelled", "CardCode", "NumAtCard", "DocTotal",
]

# Sheet / file base names shared by the reader and the synthetic exporter.
DOCUMENTS_SHEET = "documents"
BUSINESS_PARTNERS_SHEET = "business_partners"
LISTING_SHEET = "listing"

# ---------------------------------------------------------------------------
# Entity / scope routing constants.
# ---------------------------------------------------------------------------

# count() / fetch_invoices() entity names → (doc_type, doc_kind).
ENTITY_ROUTING = {
    "Invoices": ("sales", "invoice"),
    "PurchaseInvoices": ("purchase", "invoice"),
    "CreditNotes": ("sales", "credit_note"),
    "PurchaseCreditNotes": ("purchase", "credit_note"),
}

# fetch_credit_notes() entity_type → doc_type.
CREDIT_NOTE_TYPE_ROUTING = {"sales": "sales", "purchases": "purchase"}


# ---------------------------------------------------------------------------
# Canonical projections — the exact shaped records the checking core consumes.
# Applied to the FROZEN surfaces to build expected values, and mirrored by the
# reader (which builds the same shapes from export cells).
# ---------------------------------------------------------------------------


def project_line(raw: dict) -> dict:
    """Project one DocumentLines entry to its canonical line shape."""
    return {
        "VatGroup": to_str(raw.get("VatGroup")),
        "LineTotal": to_float(raw.get("LineTotal")),
        "TaxTotal": to_float(raw.get("TaxTotal")),
    }


def project_document(raw: dict, *, is_credit_note: bool = False) -> dict:
    """Project a full SAP document to the canonical invoice/credit-note shape.

    Credit-note documents carry ``is_credit_note=True`` (the tag the SAP feeder bakes
    in inside its paginator); callers sign-flip on it downstream.
    """
    doc = {
        "DocNum": to_int(raw.get("DocNum")),
        "DocDate": to_str(raw.get("DocDate")),
        "CardCode": to_str(raw.get("CardCode")),
        "CardName": to_str(raw.get("CardName")),
        "DocCurrency": to_str(raw.get("DocCurrency")),
        # Doc-level money total. The core reads this for the FX-conversion advisory
        # list (calculate_f5_return → fx_invoices_requiring_conversion); it feeds no
        # F5 box and no finding. Float-coerced like the listing DocTotal.
        "DocTotal": to_float(raw.get("DocTotal")),
        "DocumentLines": [project_line(ln) for ln in raw.get("DocumentLines", [])],
    }
    if is_credit_note:
        doc["is_credit_note"] = True
    return doc


def project_business_partner(raw: dict) -> dict:
    """Project a BusinessPartner master record to the canonical S3 shape.

    Carries only what the core reads off it (``FederalTaxID``), keyed by ``CardCode``.
    """
    return {
        "CardCode": to_str(raw.get("CardCode")),
        "FederalTaxID": to_opt_str(raw.get("FederalTaxID")),
    }


def project_listing_sales(raw: dict) -> dict:
    """Sales listing header (period & company-wide) and company-wide purchases."""
    return {
        "DocNum": to_int(raw.get("DocNum")),
        "Series": to_int(raw.get("Series")),
        "Cancelled": to_str(raw.get("Cancelled")),
    }


# all_sales / all_purch / period_sales share the 3-field header shape.
project_listing_headers_min = project_listing_sales


def project_listing_period_purch(raw: dict) -> dict:
    """Period purchases listing header — carries the DUP_CLAIM key fields."""
    return {
        "DocNum": to_int(raw.get("DocNum")),
        "Series": to_int(raw.get("Series")),
        "Cancelled": to_str(raw.get("Cancelled")),
        "CardCode": to_str(raw.get("CardCode")),
        "NumAtCard": to_opt_str(raw.get("NumAtCard")),
        "DocTotal": to_float(raw.get("DocTotal")),
    }


# The four listing buckets fetch_listing must return, and the projector for each.
LISTING_BUCKETS = {
    "period_sales_headers": ("period", "sales", project_listing_sales),
    "period_purch_headers": ("period", "purchase", project_listing_period_purch),
    "all_sales_headers": ("all", "sales", project_listing_sales),
    "all_purch_headers": ("all", "purchase", project_listing_sales),
}


# ---------------------------------------------------------------------------
# Coverage universe — the canonical fields a complete export must populate, mapped
# to the export sheet + column that feeds each. The coverage seam (emission only;
# 2B maps coverage → check status) reports which of these the loaded export carried.
#
# T2.12 slice 2B: keyed by (surface, field), NOT a bare field name. A bare-field key
# silently COLLAPSED the two DocTotal surfaces — Gap A put DocTotal on both the doc-level
# surface (the FX-conversion advisory in calculate_f5_return) and the listing-purchase
# surface (the DUP_CLAIM key) — into a single entry that could only point at one sheet.
# The (surface, field) key keeps them distinct. ``surface`` is the export sheet a field
# is read from; the value (sheet, column) is where the loader finds it.
# ---------------------------------------------------------------------------

COVERAGE_FIELDS = {
    # (surface, field) → (sheet, column)
    (DOCUMENTS_SHEET, "DocNum"): (DOCUMENTS_SHEET, "DocNum"),
    (DOCUMENTS_SHEET, "DocDate"): (DOCUMENTS_SHEET, "DocDate"),
    (DOCUMENTS_SHEET, "CardCode"): (DOCUMENTS_SHEET, "CardCode"),
    (DOCUMENTS_SHEET, "CardName"): (DOCUMENTS_SHEET, "CardName"),
    (DOCUMENTS_SHEET, "DocCurrency"): (DOCUMENTS_SHEET, "DocCurrency"),
    (DOCUMENTS_SHEET, "VatGroup"): (DOCUMENTS_SHEET, "VatGroup"),
    (DOCUMENTS_SHEET, "LineTotal"): (DOCUMENTS_SHEET, "LineTotal"),
    (DOCUMENTS_SHEET, "TaxTotal"): (DOCUMENTS_SHEET, "TaxTotal"),
    # Doc-level DocTotal — feeds the FX-conversion advisory list (was dropped by the
    # bare-field key; restored here as a distinct surface).
    (DOCUMENTS_SHEET, "DocTotal"): (DOCUMENTS_SHEET, "DocTotal"),
    (BUSINESS_PARTNERS_SHEET, "FederalTaxID"): (BUSINESS_PARTNERS_SHEET, "FederalTaxID"),
    (LISTING_SHEET, "Series"): (LISTING_SHEET, "Series"),
    (LISTING_SHEET, "Cancelled"): (LISTING_SHEET, "Cancelled"),
    (LISTING_SHEET, "NumAtCard"): (LISTING_SHEET, "NumAtCard"),
    # Listing-purchase DocTotal — the DUP_CLAIM key.
    (LISTING_SHEET, "DocTotal"): (LISTING_SHEET, "DocTotal"),
}
