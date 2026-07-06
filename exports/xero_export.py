"""exports/xero_export.py — outbound emitter: raw SAP B1 capture → Xero import CSVs.

Re-shapes the FULL raw SAP capture (the same document shape the live-SAP
``ChainReader.fetch_invoices`` returns — header + full ``DocumentLines``) into the
three Xero import templates:

    Invoices  (sales invoices)      → invoices.csv
    Bills     (purchase invoices)   → bills.csv
    Contacts  (deduped card names)  → contacts.csv

TRANSLATION-ONLY. Every output field is a re-shape of an existing captured field —
never a corrected or adjusted value, never a verdict. Reads records, writes files;
touches no F5 box and no AI-candidate surface. Imports no ``anthropic``; lives
outside ``orchestrator/``.

RULED behaviour (Terry):
  * TaxType  = line ``VatGroup`` → ``xero_crosswalk.to_annex_e`` (Annex E code). An
    unmapped SAP code flags-and-halts (``UnmappedTaxCodeError``) — never guessed.
  * AccountCode = BLANK (the client assigns a Xero chart-of-accounts code on import).
  * Quantity/UnitAmount: a zero-quantity line (SAP service line) emits Quantity=1 and
    UnitAmount = line net, so qty×unit reconciles to the line total; a non-zero line
    passes Quantity through with UnitAmount = ``UnitPrice``.
  * Dates: SAP ISO (``2024-08-05T00:00:00Z``) → Xero ``DD/MM/YYYY``.

The reader seam mirrors ``sap_b1_server.ChainReader`` (``fetch_invoices(entity)``),
here backed by the frozen raw JSON capture so the emitter runs fully offline.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from exports.xero_crosswalk import to_annex_e

# --- Xero import template column specs (header row 1, EXACT order) ----------
# Xero import requires the FULL template column set, in Xero's exact order, with
# unused columns present-but-blank. These are the complete ordered headers of the
# real Xero Invoices / Bills templates; the SAP-derived values (see ``_SOURCED``)
# land in their named positions and every other column is emitted "".
# AccountCode is present-but-blank by ruling (the client assigns a Xero CoA code).
INVOICE_COLUMNS = [
    "ContactName", "EmailAddress", "POAddressLine1", "POAddressLine2",
    "POAddressLine3", "POAddressLine4", "POCity", "PORegion", "POPostalCode",
    "POCountry", "InvoiceNumber", "Reference", "InvoiceDate", "DueDate", "Total",
    "InventoryItemCode", "Description", "Quantity", "UnitAmount", "Discount",
    "AccountCode", "TaxType", "TaxAmount", "TrackingName1", "TrackingOption1",
    "TrackingName2", "TrackingOption2", "Currency", "BrandingTheme",
]
BILL_COLUMNS = [
    "ContactName", "EmailAddress", "POAddressLine1", "POAddressLine2",
    "POAddressLine3", "POAddressLine4", "POCity", "PORegion", "POPostalCode",
    "POCountry", "InvoiceNumber", "InvoiceDate", "DueDate", "Total",
    "InventoryItemCode", "Description", "Quantity", "UnitAmount", "AccountCode",
    "TaxType", "TaxAmount", "TrackingName1", "TrackingOption1", "TrackingName2",
    "TrackingOption2", "Currency",
]
# The Xero Contacts import template is 73 columns; whether Xero accepts a
# single-ContactName import is an OPEN confirm for Terry — left at 1 column here,
# not guessed. See operational-backlog.md #16.
CONTACT_COLUMNS = ["ContactName"]

# Entity → raw capture filename (mirrors the ChainReader entity routing).
_ENTITY_FILE = {
    "Invoices": "invoices.raw.json",
    "PurchaseInvoices": "purchase-invoices.raw.json",
}

# Deterministic CSV line terminator (byte-stable across platforms).
_LINE_TERMINATOR = "\r\n"


# ---------------------------------------------------------------------------
# Reader seam over the frozen raw capture.
# ---------------------------------------------------------------------------

class RawCaptureReader:
    """Reads the FULL raw SAP capture, exposing the ChainReader read surface.

    ``fetch_invoices(entity)`` returns the raw document list (header + full
    ``DocumentLines``) for ``"Invoices"`` / ``"PurchaseInvoices"`` — the same shape
    the live ``ChainReader`` yields, so the emitter re-shapes real captured records
    (not the thin compliance projection).
    """

    def __init__(self, capture_dir):
        self._dir = Path(capture_dir)

    def fetch_invoices(self, entity: str) -> list:
        try:
            name = _ENTITY_FILE[entity]
        except KeyError:
            raise KeyError(f"unknown entity {entity!r}; expected one of {sorted(_ENTITY_FILE)}")
        with (self._dir / name).open("r", encoding="utf-8") as fh:
            return json.load(fh)


# ---------------------------------------------------------------------------
# Pure helpers.
# ---------------------------------------------------------------------------

def _num(value) -> str:
    """Deterministic numeric → string (trim trailing zeros; no scientific notation)."""
    s = f"{float(value or 0):.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def xero_date(iso: str) -> str:
    """SAP ISO datetime (``2024-08-05T00:00:00Z``) → Xero ``DD/MM/YYYY``."""
    date_part = (iso or "")[:10]  # YYYY-MM-DD
    year, month, day = date_part.split("-")
    return f"{day}/{month}/{year}"


def line_qty_unit(line: dict) -> dict:
    """Apply the ruled Quantity/UnitAmount rule to one SAP line.

    Zero-quantity (service line) → Quantity=1, UnitAmount = line net (``LineTotal``),
    so qty×unit reconciles to the line total. Otherwise Quantity passes through and
    UnitAmount = ``UnitPrice``.
    """
    qty = float(line.get("Quantity") or 0)
    if qty == 0:
        return {"Quantity": "1", "UnitAmount": _num(line.get("LineTotal"))}
    return {"Quantity": _num(qty), "UnitAmount": _num(line.get("UnitPrice"))}


# SAP-derived Xero columns (populated from the capture). Every OTHER template
# column is emitted as an empty string — present-but-blank, no data invented.
_SOURCED_COLUMNS = frozenset({
    "ContactName", "InvoiceNumber", "InvoiceDate", "DueDate",
    "Description", "Quantity", "UnitAmount", "TaxType",
})


# Companion fallback-provenance file (Option A). Records every Bill whose Xero
# InvoiceNumber fell back to the internal DocNum because the supplier reference
# (NumAtCard) was absent. Bookkeeping only — NOT a tax-semantics claim.
FALLBACK_COLUMNS = ["DocNum", "ContactName", "Reason"]
_FALLBACK_REASON = "NumAtCard absent — used internal DocNum"


def resolve_bill_invoice_number(doc: dict) -> tuple:
    """Bill InvoiceNumber = supplier ref (NumAtCard) if non-empty, else DocNum.

    Returns ``(number, is_fallback)`` — ``is_fallback`` is True when NumAtCard was
    absent/blank and the internal DocNum was substituted (a recorded fallback).
    """
    supplier_ref = (doc.get("NumAtCard") or "").strip()
    if supplier_ref:
        return supplier_ref, False
    return str(doc.get("DocNum", "")), True


def _doc_line_rows(doc: dict, columns: list, prefer_supplier_ref: bool = False) -> list:
    """One Xero row per SAP document line, projected onto the full template.

    SAP-derived values land under their named columns; every non-sourced template
    column defaults to "" (present-but-blank). AccountCode is deliberately blank by
    ruling (client assigns a Xero chart-of-accounts code on import).

    When ``prefer_supplier_ref`` (the BILL path only), InvoiceNumber prefers the
    supplier reference (NumAtCard) and falls back to DocNum; sales invoices leave it
    False and keep DocNum.
    """
    rows = []
    if prefer_supplier_ref:
        invoice_number = resolve_bill_invoice_number(doc)[0]
    else:
        invoice_number = str(doc.get("DocNum", ""))
    header_fields = {
        "ContactName": doc.get("CardName", ""),
        "InvoiceNumber": invoice_number,
        "InvoiceDate": xero_date(doc.get("DocDate", "")),
        "DueDate": xero_date(doc.get("DocDueDate", "")),
    }
    for line in doc.get("DocumentLines", []):
        qu = line_qty_unit(line)
        derived = dict(header_fields)
        derived["Description"] = line.get("ItemDescription", "") or ""
        derived["Quantity"] = qu["Quantity"]
        derived["UnitAmount"] = qu["UnitAmount"]
        derived["TaxType"] = to_annex_e(line.get("VatGroup", ""))
        # AccountCode stays "" (BLANK by ruling); all non-sourced columns "" too.
        rows.append({col: derived.get(col, "") for col in columns})
    return rows


# ---------------------------------------------------------------------------
# Row builders.
# ---------------------------------------------------------------------------

def build_invoice_rows(docs: list) -> list:
    """Sales invoices → Xero Invoices rows."""
    rows = []
    for doc in docs:
        rows.extend(_doc_line_rows(doc, INVOICE_COLUMNS))
    return rows


def build_bill_rows(docs: list) -> list:
    """Purchase invoices → Xero Bills rows (InvoiceNumber prefers NumAtCard else DocNum)."""
    rows = []
    for doc in docs:
        rows.extend(_doc_line_rows(doc, BILL_COLUMNS, prefer_supplier_ref=True))
    return rows


def collect_bill_fallbacks(docs: list) -> list:
    """One provenance record per Bill whose InvoiceNumber fell back to DocNum.

    A bill is recorded iff its supplier reference (NumAtCard) was absent/blank, so the
    internal DocNum was substituted. Order follows the document order (deterministic).
    """
    fallbacks = []
    for doc in docs:
        _number, is_fallback = resolve_bill_invoice_number(doc)
        if is_fallback:
            fallbacks.append({
                "DocNum": str(doc.get("DocNum", "")),
                "ContactName": doc.get("CardName", ""),
                "Reason": _FALLBACK_REASON,
            })
    return fallbacks


def build_contact_rows(*doc_lists: list) -> list:
    """Distinct ``CardName`` across the supplied document lists → Contacts rows.

    Dedup preserves first-seen order; a repeated CardName collapses to one row.
    """
    seen = set()
    rows = []
    for docs in doc_lists:
        for doc in docs:
            name = doc.get("CardName", "")
            if name and name not in seen:
                seen.add(name)
                rows.append({"ContactName": name})
    return rows


# ---------------------------------------------------------------------------
# CSV emission.
# ---------------------------------------------------------------------------

def _write_csv(path: Path, columns: list, rows: list) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator=_LINE_TERMINATOR)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def export_all(capture_dir, out_dir) -> dict:
    """Emit the three Xero import CSVs from the raw capture; return their paths.

    Deterministic and offline: reads the frozen raw JSON capture, writes byte-stable
    CSVs. Raises ``UnmappedTaxCodeError`` (flag-and-halt) if any line carries a SAP
    VatGroup with no Annex E crosswalk row.
    """
    reader = RawCaptureReader(capture_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sales = reader.fetch_invoices("Invoices")
    purchases = reader.fetch_invoices("PurchaseInvoices")

    invoice_rows = build_invoice_rows(sales)
    bill_rows = build_bill_rows(purchases)
    contact_rows = build_contact_rows(sales, purchases)
    # Companion provenance file: bills whose InvoiceNumber fell back to DocNum
    # (supplier NumAtCard absent). Header always written; zero rows if none.
    bill_fallbacks = collect_bill_fallbacks(purchases)

    return {
        "invoices": _write_csv(out / "invoices.csv", INVOICE_COLUMNS, invoice_rows),
        "bills": _write_csv(out / "bills.csv", BILL_COLUMNS, bill_rows),
        "contacts": _write_csv(out / "contacts.csv", CONTACT_COLUMNS, contact_rows),
        "bills_fallbacks": _write_csv(
            out / "bills.fallbacks.csv", FALLBACK_COLUMNS, bill_fallbacks
        ),
    }
