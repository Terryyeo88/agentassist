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

# --- Xero import template column specs (header row 1, exact order) ----------
# Required (*) columns per the Xero Invoices / Bills / Contacts import templates.
# AccountCode is present-but-blank (client fills it in Xero). Description is a
# required column on Invoices and an optional-but-populated column on Bills.
INVOICE_COLUMNS = [
    "ContactName", "InvoiceNumber", "InvoiceDate", "DueDate",
    "Description", "Quantity", "UnitAmount", "AccountCode", "TaxType",
]
BILL_COLUMNS = [
    "ContactName", "InvoiceNumber", "InvoiceDate", "DueDate",
    "Description", "Quantity", "UnitAmount", "AccountCode", "TaxType",
]
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


def _doc_line_rows(doc: dict, columns: list) -> list:
    """One Xero row per SAP document line (rows share the header fields)."""
    rows = []
    contact = doc.get("CardName", "")
    number = str(doc.get("DocNum", ""))
    inv_date = xero_date(doc.get("DocDate", ""))
    due_date = xero_date(doc.get("DocDueDate", ""))
    for line in doc.get("DocumentLines", []):
        qu = line_qty_unit(line)
        row = {
            "ContactName": contact,
            "InvoiceNumber": number,
            "InvoiceDate": inv_date,
            "DueDate": due_date,
            "Description": line.get("ItemDescription", "") or "",
            "Quantity": qu["Quantity"],
            "UnitAmount": qu["UnitAmount"],
            "AccountCode": "",  # BLANK by ruling — client assigns in Xero.
            "TaxType": to_annex_e(line.get("VatGroup", "")),
        }
        rows.append({col: row[col] for col in columns})
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
    """Purchase invoices → Xero Bills rows."""
    rows = []
    for doc in docs:
        rows.extend(_doc_line_rows(doc, BILL_COLUMNS))
    return rows


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

    return {
        "invoices": _write_csv(out / "invoices.csv", INVOICE_COLUMNS, invoice_rows),
        "bills": _write_csv(out / "bills.csv", BILL_COLUMNS, bill_rows),
        "contacts": _write_csv(out / "contacts.csv", CONTACT_COLUMNS, contact_rows),
    }
