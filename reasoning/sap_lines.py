"""reasoning/sap_lines.py — SAP fetch helpers for reasoning-layer line sources.

Provides two passive line sources, both consumed OUTSIDE the deterministic
chain (Phase 2), never inside run_chain:

  * fetch_si_purchase_lines() — all SI-coded lines from PurchaseInvoices +
    PurchaseCreditNotes.  run_agent.py passes this to run_reg2627_pass().
  * fetch_sales_lines() (T2.28) — ALL sales lines from Invoices + CreditNotes,
    each carrying its own CANONICAL (normalized) VatGroup.  The sales analog of
    the purchase fetcher, for a future sales-side reasoning skill (e.g. exempt
    supply).  It applies NO VatGroup filter — the downstream SkillSpec selects
    the codes it cares about (ES33/ESN33/…).  Not wired into any pass yet.

Dependency note: this module imports sap_b1_server (deferred, inside
_do_fetch_paginated and _normalize_vat_group so tests can monkeypatch them).
It does NOT import from orchestrator/ or audit_bundle/, and never anthropic.
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


# ---------------------------------------------------------------------------
# Sales line source (T2.28) — the sales analog of the purchase fetcher
# ---------------------------------------------------------------------------

# OData sales entity collection names (paired with the purchase entities above).
_SALES_INVOICES_ENTITY = "Invoices"
_SALES_CREDIT_NOTES_ENTITY = "CreditNotes"


def _normalize_vat_group(raw_code) -> str:
    """Canonicalise a raw sales VatGroup via the deterministic core's mapping.

    Deferred import (mirrors _do_fetch_paginated) so tests can monkeypatch this
    seam without a live SAP client.  Delegates to sap_b1_server.normalize_vat_group
    using the same module-level tax-code mappings the deterministic chain uses,
    so a sales line's vat_group is the canonical AgentAssist code.

    For SAP B1 clients the mappings are empty, so normalize is an identity
    passthrough — already-canonical codes (ES33/ESN33/SO/OS/ZR) are returned
    unchanged.  Confirmed against the frozen SBODEMOSG sales extract, whose raw
    "VatGroup" values are already canonical (ES33/SO/OS/ZR).
    """
    import sap_b1_server as _sap  # noqa: PLC0415 — deferred intentionally
    return _sap.normalize_vat_group(str(raw_code or "").strip(), _sap._tax_code_mappings)


def _extract_sales_lines(
    docs: list[dict], doc_type: str, *, normalize=None
) -> list[dict]:
    """Extract ALL sales lines from a list of SAP document dicts.

    Unlike _extract_si_lines this applies NO VatGroup filter: every line is
    emitted, carrying its OWN canonical VatGroup (via the normalize seam).  The
    9-key output shape is identical to the purchase fetcher so the same
    reasoning-layer candidate contract accepts it.

    Args:
        docs:      SAP sales document dicts (each with DocumentLines).
        doc_type:  "sales_invoice" or "sales_credit_note".
        normalize: injectable VatGroup normalizer (raw -> canonical); defaults
                   to _normalize_vat_group.  Injected in unit tests.
    """
    _norm = normalize if normalize is not None else _normalize_vat_group
    lines: list[dict] = []
    for doc in docs:
        for idx, line in enumerate(doc.get("DocumentLines", [])):
            lines.append({
                "doc_num": int(doc.get("DocNum") or 0),
                "doc_type": doc_type,
                "doc_date": str(doc.get("DocDate", ""))[:10],
                "card_name": str(doc.get("CardName", "")),
                "line_index": idx,
                "vat_group": _norm(line.get("VatGroup")),
                "line_description": _get_line_description(line),
                "line_total": float(line.get("LineTotal") or 0),
                "tax_total": float(line.get("TaxTotal") or 0),
            })
    return lines


def fetch_sales_lines(period_start: str, period_end: str) -> list[dict]:
    """Return ALL sales lines from Invoices + CreditNotes for the period.

    The sales analog of fetch_si_purchase_lines.  Each returned dict has the same
    keys:
        doc_num, doc_type, doc_date, card_name,
        line_index, vat_group (canonical), line_description,
        line_total, tax_total.

    doc_type is "sales_invoice" for Invoices lines and "sales_credit_note" for
    CreditNotes lines.  Both entities are fetched via the SAME plain paginated
    helper the purchase fetcher and calculate_f5_return use — there is NO
    credit-note sign-flip (the reasoning skill classifies lines, it does not net
    output tax).  No VatGroup filter is applied: every sales line is surfaced,
    carrying its own canonical VatGroup, so a downstream SkillSpec selects the
    codes it needs (e.g. ES33/ESN33).

    Requires sap_b1_server to be configured before calling (run_chain does this).
    """
    inv_docs = _do_fetch_paginated(_SALES_INVOICES_ENTITY, period_start, period_end)
    cn_docs = _do_fetch_paginated(_SALES_CREDIT_NOTES_ENTITY, period_start, period_end)

    lines: list[dict] = []
    lines.extend(_extract_sales_lines(inv_docs, "sales_invoice"))
    lines.extend(_extract_sales_lines(cn_docs, "sales_credit_note"))
    return lines
