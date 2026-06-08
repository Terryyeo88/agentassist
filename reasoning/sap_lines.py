"""reasoning/sap_lines.py — SAP fetch helper for Reg 26/27 SI purchase lines.

Provides fetch_si_purchase_lines() which retrieves all SI-coded lines from both
PurchaseInvoices and PurchaseCreditNotes for a given period.  run_agent.py
passes this function as the line_source to run_reg2627_pass().

Dependency note: this module imports sap_b1_server (deferred, inside
_do_fetch_paginated so tests can monkeypatch the helper).  It does NOT import
from orchestrator/ or audit_bundle/.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Line-description field — confirmed on SBODEMOSG 2026-06-02
# ---------------------------------------------------------------------------

# Primary field confirmed present in SAP B1 Service Layer (SBODEMOSG live query).
LINE_DESCRIPTION_FIELD = "ItemDescription"

# Fallback field: legacy SAP B1 Service Layer versions exposed the description
# as "Dscription" (note the single-s spelling).  NOT present on SBODEMOSG but
# retained for resilience against older Service Layer versions.
_LEGACY_DESC_FIELD = "Dscription"

# Last-resort identifier — ItemCode is a stock-keeping identifier, not a
# human-readable description.  Retained only so that lines whose primary and
# legacy description fields are empty still have a non-blank identifier.
_LAST_RESORT_FIELD = "ItemCode"


def _get_line_description(line: dict) -> str:
    return str(
        line.get(LINE_DESCRIPTION_FIELD)
        or line.get(_LEGACY_DESC_FIELD)  # legacy SAP field; absent on SBODEMOSG
        or line.get(_LAST_RESORT_FIELD)  # last-resort identifier, not a true description
        or ""
    ).strip()


def _extract_si_lines(docs: list[dict], doc_type: str) -> list[dict]:
    """Extract SI-coded lines from a list of SAP document dicts."""
    lines: list[dict] = []
    for doc in docs:
        for idx, line in enumerate(doc.get("DocumentLines", [])):
            if str(line.get("VatGroup") or "").strip() != "SI":
                continue
            lines.append({
                "doc_num": int(doc.get("DocNum") or 0),
                "doc_type": doc_type,
                "doc_date": str(doc.get("DocDate", ""))[:10],
                "card_name": str(doc.get("CardName", "")),
                "line_index": idx,
                "vat_group": "SI",
                "line_description": _get_line_description(line),
                "line_total": float(line.get("LineTotal") or 0),
                "tax_total": float(line.get("TaxTotal") or 0),
            })
    return lines


# ---------------------------------------------------------------------------
# Injectable fetch primitive — replaceable in tests via monkeypatch
# ---------------------------------------------------------------------------

def _do_fetch_paginated(entity: str, period_start: str, period_end: str) -> list[dict]:
    """Call sap_b1_server._fetch_invoices_paginated.

    Deferred import: sap_b1_server is only importable after orchestrator has
    added mcp-servers/custom to sys.path and configured the client.
    Tests replace this function via monkeypatch so no live SAP is needed.
    """
    import sap_b1_server as _sap  # noqa: PLC0415 — deferred intentionally
    return _sap._fetch_invoices_paginated(entity, period_start, period_end)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_si_purchase_lines(period_start: str, period_end: str) -> list[dict]:
    """Return all SI-coded lines from PurchaseInvoices + PurchaseCreditNotes.

    Each returned dict has these keys:
        doc_num, doc_type, doc_date, card_name,
        line_index, vat_group ("SI"), line_description,
        line_total, tax_total.

    doc_type is "purchase_invoice" for PurchaseInvoices lines and
    "purchase_credit_note" for PurchaseCreditNotes lines.

    Requires sap_b1_server to be configured before calling (run_chain does this).
    Never filters by doc_type — both document types are included so credit-note
    reversals of previously flagged invoices are also surfaced for review.
    """
    inv_docs = _do_fetch_paginated("PurchaseInvoices", period_start, period_end)
    cn_docs = _do_fetch_paginated("PurchaseCreditNotes", period_start, period_end)

    lines: list[dict] = []
    lines.extend(_extract_si_lines(inv_docs, "purchase_invoice"))
    lines.extend(_extract_si_lines(cn_docs, "purchase_credit_note"))
    return lines
