"""exports/xero_crosswalk.py — SAP B1 VatGroup → IRAS Annex E GST Category Code.

SOURCE OF AUTHORITY (in-repo IRAS traceability):
    knowledge-base/etaxguide_gst_invoicenow_requirement.pdf
    — IRAS e-Tax Guide "Adopting GST InvoiceNow Requirement for GST-Registered
      Businesses" (Second Edition), Annex E "GST Category Codes", pp.79-83.

This is a Terry-authored, IRAS-traced crosswalk. It is TRANSLATION-ONLY: it maps a
raw SAP B1 VatGroup to its Annex E code so an outbound Xero import file carries the
Annex E TaxType. It NEVER asserts a verdict and NEVER corrects a value.

The tool emits the Annex E code only; the client maps Annex E → their own Xero
tax-rate names on their side (this module does not invent Xero rate-names).

FLAG-AND-HALT: an unmapped SAP code raises ``UnmappedTaxCodeError`` — it is never
guessed and never silently defaulted. A blank/unknown code stops that line loudly so
a mis-code can never reach the client file.
"""
from __future__ import annotations

# Committed Annex E artifact the crosswalk is traced to (repo-relative path).
ANNEX_E_SOURCE = "knowledge-base/etaxguide_gst_invoicenow_requirement.pdf"

# Terry-authored SAP B1 VatGroup → Annex E GST Category Code (Annex E pp.79-83).
# 13 direct carryovers, 2 renames (SO→SR, SI→TX), plus the exempt-input rename
# TX-E33→TX-ESS. Any code NOT in this table flags-and-halts.
SAP_TO_ANNEX_E = {
    "SO": "SR",
    "ZR": "ZR",
    "OS": "OS",
    "DS": "DS",
    "ES33": "ES33",
    "ESN33": "ESN33",
    "SI": "TX",
    "ZP": "ZP",
    "EP": "EP",
    "OP": "OP",
    "IM": "IM",
    "IGDS": "IGDS",
    "ME": "ME",
    "NR": "NR",
    "BL": "BL",
    "TX-E33": "TX-ESS",
    "TX-N33": "TX-N33",
    "TX-RE": "TX-RE",
}


class UnmappedTaxCodeError(ValueError):
    """A SAP VatGroup with no Annex E crosswalk row — halt, never guess."""


def to_annex_e(vat_group: str) -> str:
    """Map one SAP B1 VatGroup to its Annex E GST Category Code.

    Raises ``UnmappedTaxCodeError`` (never guesses, never defaults) when the code is
    blank or absent from ``SAP_TO_ANNEX_E`` — the outbound line must stop rather than
    carry an unauthorised tax code into the client's Xero import.
    """
    code = (vat_group or "").strip()
    try:
        return SAP_TO_ANNEX_E[code]
    except KeyError:
        raise UnmappedTaxCodeError(
            f"SAP VatGroup {vat_group!r} has no Annex E crosswalk row "
            f"(source: {ANNEX_E_SOURCE}, Annex E pp.79-83). Flag-and-halt: the "
            "crosswalk refuses to guess or default an unmapped code."
        )
