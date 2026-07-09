"""tests/synth_xero_sales_export.py — synthetic Xero SALES-INVOICE export builder.

Writes a flat, one-row-per-invoice-line Xero sales-invoice export in BOTH a single-file CSV
and a single-sheet .xlsx, from a list of row dicts. Used two ways:

  1. As a SCRIPT (``python tests/synth_xero_sales_export.py``) it (re)generates the committed
     demo fixture under ``tests/fixtures/xero-sales-export/``.
  2. As an IMPORTABLE helper it lets a test build ad-hoc temp inputs (e.g. a file carrying a
     PARKED tax code) into ``tmp_path`` without touching the committed fixture.

HONEST STATUS (T2.11): this mirrors a Xero sales-invoice export LAYOUT with hand-authored
SYNTHETIC content — it is NOT a real client export, and the exact real column-header set /
TaxType vocabulary still need pinning against a genuine export. SGD only; no PII.

Pure stdlib (+ openpyxl, lazily, on the .xlsx path). No SAP, no anthropic.
"""
from __future__ import annotations

import csv
from pathlib import Path

# Canonical Xero sales-invoice export columns (real-FORMAT approximation). One row per invoice
# LINE; header-level fields (ContactName / InvoiceNumber / InvoiceDate / Currency / Total)
# repeat across a multi-line invoice's rows.
COLUMNS = [
    "ContactName", "InvoiceNumber", "InvoiceDate", "DueDate", "Description",
    "Quantity", "UnitAmount", "AccountCode", "TaxType", "TaxAmount", "LineAmount",
    "Currency", "Total",
]

# The default sheet name the .xlsx path writes / the reader locates by its marker columns.
SHEET_NAME = "Sales Invoices"


def _row(contact, invnum, date, taxtype, line_amount, tax_amount, total, *,
         description="Item", account="200", currency="SGD", due=""):
    """One flat export row (dict keyed by COLUMNS)."""
    return {
        "ContactName": contact,
        "InvoiceNumber": invnum,
        "InvoiceDate": date,
        "DueDate": due,
        "Description": description,
        "Quantity": "1",
        "UnitAmount": line_amount,
        "AccountCode": account,
        "TaxType": taxtype,
        "TaxAmount": tax_amount,
        "LineAmount": line_amount,
        "Currency": currency,
        "Total": total,
    }


# The committed demo fixture rows (SGD). Deliberately exercises the three shapes the sample
# real file may NOT: a MULTI-LINE invoice (INV-2001 repeats → grouped, ordered lines), a
# clean single-line ZR invoice (INV-2002), and an invoice carrying one OUT-OF-SCOPE ("No Tax")
# line beside an in-scope SR line (INV-2003) so out-of-scope exclusion is exercised inside a
# genuine invoice rather than in isolation.
DEMO_ROWS = [
    # INV-2001 — multi-line standard-rated (two SR lines under one InvoiceNumber → one doc).
    _row("Acme Pte Ltd", "INV-2001", "2026-04-05", "Standard-Rated Supplies",
         "10000", "900", "21800", description="Consulting services"),
    _row("Acme Pte Ltd", "INV-2001", "2026-04-05", "Standard-Rated Supplies",
         "10000", "900", "21800", description="Support retainer"),
    # INV-2002 — single zero-rated line.
    _row("Borealis Pte Ltd", "INV-2002", "2026-04-10", "Zero-Rated Supplies",
         "5000", "0", "5000", description="Export goods", account="201"),
    # INV-2003 — one in-scope SR line + one out-of-scope "No Tax" line (accepted, set aside).
    _row("Cresco Pte Ltd", "INV-2003", "2026-05-01", "Standard-Rated Supplies",
         "3000", "270", "3370", description="Advisory", account="200"),
    _row("Cresco Pte Ltd", "INV-2003", "2026-05-01", "No Tax",
         "100", "0", "3370", description="Out-of-scope disbursement", account="260"),
]


def write_csv(path: Path, rows: list[dict]) -> Path:
    """Write ``rows`` to a single flat CSV at ``path`` (header = COLUMNS)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return path


def write_xlsx(path: Path, rows: list[dict], sheet_name: str = SHEET_NAME) -> Path:
    """Write ``rows`` to a single-sheet .xlsx at ``path`` (header = COLUMNS)."""
    from openpyxl import Workbook  # lazy — the CSV path needs no third-party dep.

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(COLUMNS)
    for row in rows:
        ws.append([row.get(col, "") for col in COLUMNS])
    wb.save(path)
    return path


def build_demo_fixture(dir_path: Path) -> tuple[Path, Path]:
    """(Re)generate the committed demo fixture (both .xlsx and .csv). Returns (xlsx, csv)."""
    dir_path = Path(dir_path)
    xlsx = write_xlsx(dir_path / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx",
                      DEMO_ROWS)
    csv_path = write_csv(dir_path / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.csv",
                         DEMO_ROWS)
    return xlsx, csv_path


if __name__ == "__main__":
    _here = Path(__file__).resolve().parent
    _fixture_dir = _here / "fixtures" / "xero-sales-export"
    x, c = build_demo_fixture(_fixture_dir)
    print(f"wrote {x}")
    print(f"wrote {c}")
