"""tests/synth_extract_export.py — SYNTHETIC GST-export generator for the T2.12a round-trip.

Test scaffolding (NOT a product format). Reads the frozen SBODEMOSG ground-truth surfaces
and writes them out in this slice's *guess* at a client SAP B1 GST-listing export — a
combined line-level transaction register (sales/purchase × invoice/credit-note), a
BusinessPartner master, and a document-number listing. ``feeders.ExtractChainReader`` then
reads that export back; the round-trip test asserts the reconstructed surfaces equal the
canonical projection of the frozen ground truth, field-for-field.

The exporter and the reader share ONE schema (``feeders.extract_schema``) so the column
shape has a single source of truth. CSV is written with LF line terminators so committed
fixtures are byte-stable across Windows capture and Linux CI.

Loaded via importlib in the test (tests/ is not a package — same pattern as replay_shim).
Pure stdlib (+ openpyxl for the .xlsx path). No network.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from feeders import extract_schema as schema

# Frozen-surface filename → (doc_type, doc_kind) for the document register.
_DOC_SURFACES = [
    ("invoices.raw.json", "sales", "invoice"),
    ("purchase-invoices.raw.json", "purchase", "invoice"),
    ("credit-notes.raw.json", "sales", "credit_note"),
    ("purchase-credit-notes.raw.json", "purchase", "credit_note"),
]

# listing-headers.json bucket → (scope, doc_type) for the listing register.
_LISTING_SURFACES = [
    ("period_sales_headers", "period", "sales"),
    ("period_purch_headers", "period", "purchase"),
    ("all_sales_headers", "all", "sales"),
    ("all_purch_headers", "all", "purchase"),
]


def _load(extract_dir: Path, name: str):
    return json.loads((extract_dir / name).read_text(encoding="utf-8"))


def build_document_rows(extract_dir: Path) -> list[dict]:
    """One row per document line, in frozen surface + document + line order."""
    rows: list[dict] = []
    for filename, doc_type, doc_kind in _DOC_SURFACES:
        for doc in _load(extract_dir, filename):
            base = {
                schema.DOC_TYPE_COL: doc_type,
                schema.DOC_KIND_COL: doc_kind,
                "DocNum": schema.ser(doc.get("DocNum")),
                "DocDate": schema.ser(doc.get("DocDate")),
                "CardCode": schema.ser(doc.get("CardCode")),
                "CardName": schema.ser(doc.get("CardName")),
                "DocCurrency": schema.ser(doc.get("DocCurrency")),
                # Doc-level total, sourced from the frozen ground truth (not fabricated).
                "DocTotal": schema.ser(doc.get("DocTotal")),
            }
            for idx, line in enumerate(doc.get("DocumentLines", [])):
                row = dict(base)
                row[schema.LINE_INDEX_COL] = schema.ser(idx)
                row["VatGroup"] = schema.ser(line.get("VatGroup"))
                row["LineTotal"] = schema.ser(line.get("LineTotal"))
                row["TaxTotal"] = schema.ser(line.get("TaxTotal"))
                rows.append(row)
    return rows


def build_business_partner_rows(extract_dir: Path) -> list[dict]:
    raw = _load(extract_dir, "business-partners.raw.json")
    rows = []
    for record in raw.values():
        rows.append({
            "CardCode": schema.ser(record.get("CardCode")),
            "CardName": schema.ser(record.get("CardName")),
            "FederalTaxID": schema.ser(record.get("FederalTaxID")),
        })
    return rows


def build_listing_rows(extract_dir: Path) -> list[dict]:
    listing = _load(extract_dir, "listing-headers.json")
    rows = []
    for bucket, scope, doc_type in _LISTING_SURFACES:
        for rec in listing.get(bucket, []):
            rows.append({
                schema.SCOPE_COL: scope,
                schema.DOC_TYPE_COL: doc_type,
                "DocNum": schema.ser(rec.get("DocNum")),
                "Series": schema.ser(rec.get("Series")),
                "Cancelled": schema.ser(rec.get("Cancelled")),
                "CardCode": schema.ser(rec.get("CardCode")),
                "NumAtCard": schema.ser(rec.get("NumAtCard")),
                "DocTotal": schema.ser(rec.get("DocTotal")),
            })
    return rows


_SHEETS = [
    (schema.DOCUMENTS_SHEET, schema.DOCUMENT_COLUMNS, build_document_rows),
    (schema.BUSINESS_PARTNERS_SHEET, schema.BUSINESS_PARTNER_COLUMNS, build_business_partner_rows),
    (schema.LISTING_SHEET, schema.LISTING_COLUMNS, build_listing_rows),
]


def export_csv(extract_dir: Path, out_dir: Path) -> Path:
    """Write the synthetic export as a directory of LF-terminated CSV files."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, columns, builder in _SHEETS:
        path = out_dir / f"{name}.csv"
        # newline="" + explicit LF lineterminator → byte-stable LF output on Windows.
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for row in builder(extract_dir):
                writer.writerow(row)
    return out_dir


def export_xlsx(extract_dir: Path, out_path: Path) -> Path:
    """Write the synthetic export as a single .xlsx workbook (one sheet per surface)."""
    from openpyxl import Workbook

    out_path = Path(out_path)
    wb = Workbook()
    wb.remove(wb.active)
    for name, columns, builder in _SHEETS:
        ws = wb.create_sheet(title=name)
        ws.append(columns)
        for row in builder(extract_dir):
            ws.append([row.get(col, "") for col in columns])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
