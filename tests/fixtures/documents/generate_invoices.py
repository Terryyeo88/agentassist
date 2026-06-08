#!/usr/bin/env python3
"""
Deterministic Singapore TAX INVOICE PDF generator — T2.8 document-ingestion
test substrate.

Generates 8 PDFs + fixtures_manifest.json in the same directory as this script.

IRAS para 7.1.4 particulars present in every PDF
(Tenth Edition, GST Act s.41 requirements):
  (a) The words "TAX INVOICE"
  (b) Invoice number (unique sequential identifier)
  (c) Date of issue
  (d) Supplier name, address, and GST registration number
  (e) Customer name and address
  (f) Description of the goods or services
  (g) Amount payable excluding GST
  (h) GST rate applied
  (i) GST amount charged (shown separately)
  (j) Total amount payable including GST

Internal line-item shape produced by reasoning/sap_lines.py (every record
in fixtures_manifest.json["cases"][*]["line_item_record"] matches this shape
exactly):
    doc_num          int     — SAP DocNum (join key)
    doc_type         str     — "purchase_invoice"
    doc_date         str     — YYYY-MM-DD (from SAP DocDate; matches PDF date for
                               clean cases; PDF date differs for date_outside_period)
    card_name        str     — supplier/vendor name (SAP CardName on AP invoice)
    line_index       int     — 0-based line index within the document
    vat_group        str     — "SI" (only SI lines are extracted by sap_lines.py)
    line_description str     — item description (SAP ItemDescription field)
    line_total       float   — amount excluding GST (SAP LineTotal)
    tax_total        float   — GST amount as recorded in SAP (SAP TaxTotal)

Injected issues (controlled discrepancies between the PDF and the SAP record):
    none                     — clean case; PDF and record agree on all particulars
    gst_amount_mismatch      — PDF GST figure differs from record tax_total
    supplier_gst_reg_absent  — PDF omits the supplier GST registration number
    date_outside_period      — PDF invoice date falls outside Q3 2024 period
    total_inconsistency      — PDF total incl. GST != PDF excl. + PDF GST amount
    combined                 — two issues present simultaneously

Determinism guarantee:
    Canvas(invariant=1) fixes reportlab's internal timestamps to a constant
    value, so re-running this script produces byte-identical PDFs.
    The case data and all rendered strings are hardcoded; no random selection
    is performed at generation time.  The seed constant SEED=20260608 is
    reserved for future parametric extension.

Usage:
    python tests/fixtures/documents/generate_invoices.py

No network, no SAP instance, no anthropic import required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED = 20260608          # reserved; all case data is currently hardcoded
GST_PERIOD_START = "2024-07-01"
GST_PERIOD_END   = "2024-09-30"
DOCS_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Case definitions
#
# Each case has two sections:
#   "record"  — the internal line-item shape as returned by sap_lines.py
#   "pdf"     — the values actually rendered on the PDF face
#               (identical to record for clean cases; deliberately different
#                for injected-issue cases)
# ---------------------------------------------------------------------------

CASES: list[dict[str, Any]] = [
    # ── Case 1 ── Clean: all particulars correct ───────────────────────────
    {
        "record": {
            "doc_num": 3001,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-07-15",
            "card_name": "TechSupply Solutions Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Professional IT Consulting Services - July 2024",
            "line_total": 5000.00,
            "tax_total": 350.00,
        },
        "pdf": {
            "invoice_num": "INV-3001",
            "date": "2024-07-15",
            "supplier_name": "TechSupply Solutions Pte Ltd",
            "supplier_address": "100 Beach Road #20-01, Singapore 189702",
            "supplier_gst_reg": "M12345678X",
            "customer_name": "Acme Corporation Pte Ltd",
            "customer_address": "50 Raffles Place #30-01, Singapore 048623",
            "description": "Professional IT Consulting Services - July 2024",
            "excl_gst": 5000.00,
            "gst_rate_label": "7%",
            "gst_amount": 350.00,
            "total": 5350.00,
        },
        "injected_issue": "none",
        "injected_issue_detail": "Clean case. PDF and SAP record agree on all IRAS para 7.1.4 particulars.",
    },

    # ── Case 2 ── Clean: second clean case, different supplier ─────────────
    {
        "record": {
            "doc_num": 3002,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-08-20",
            "card_name": "Office Essentials Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Office Supplies - Stationery and Consumables Q3",
            "line_total": 2800.00,
            "tax_total": 196.00,
        },
        "pdf": {
            "invoice_num": "INV-3002",
            "date": "2024-08-20",
            "supplier_name": "Office Essentials Pte Ltd",
            "supplier_address": "30 Tanjong Pagar Road, Singapore 088461",
            "supplier_gst_reg": "M87654321X",
            "customer_name": "BuildCo Engineering Pte Ltd",
            "customer_address": "200 Pandan Loop, Singapore 128388",
            "description": "Office Supplies - Stationery and Consumables Q3",
            "excl_gst": 2800.00,
            "gst_rate_label": "7%",
            "gst_amount": 196.00,
            "total": 2996.00,
        },
        "injected_issue": "none",
        "injected_issue_detail": "Clean case. PDF and SAP record agree on all IRAS para 7.1.4 particulars.",
    },

    # ── Case 3 ── GST amount mismatch: PDF overstates GST ──────────────────
    # SAP record has tax_total=840.00 (correct 7%); PDF shows 900.00
    {
        "record": {
            "doc_num": 3003,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-07-30",
            "card_name": "Heavy Equipment Rentals Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Excavator Equipment Rental - Monthly Hire July",
            "line_total": 12000.00,
            "tax_total": 840.00,
        },
        "pdf": {
            "invoice_num": "INV-3003",
            "date": "2024-07-30",
            "supplier_name": "Heavy Equipment Rentals Pte Ltd",
            "supplier_address": "45 Tuas Avenue 11, Singapore 638785",
            "supplier_gst_reg": "M11223344X",
            "customer_name": "ConstructMaster Pte Ltd",
            "customer_address": "10 Changi South Lane, Singapore 486162",
            "description": "Excavator Equipment Rental - Monthly Hire July",
            "excl_gst": 12000.00,
            "gst_rate_label": "7%",
            "gst_amount": 900.00,      # ← INJECTED: overstated; record has 840.00
            "total": 12900.00,
        },
        "injected_issue": "gst_amount_mismatch",
        "injected_issue_detail": (
            "PDF shows GST 900.00 but SAP record tax_total=840.00 "
            "(PDF overstates by 60.00; correct 7% of 12000 is 840.00)."
        ),
    },

    # ── Case 4 ── GST amount mismatch: PDF understates GST (wrong rate) ────
    # SAP record has tax_total=224.00 (correct 7%); PDF shows 192.00 (applies 6%)
    {
        "record": {
            "doc_num": 3004,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-08-05",
            "card_name": "Premium Catering Services Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Corporate Catering Services - August Board Meeting",
            "line_total": 3200.00,
            "tax_total": 224.00,
        },
        "pdf": {
            "invoice_num": "INV-3004",
            "date": "2024-08-05",
            "supplier_name": "Premium Catering Services Pte Ltd",
            "supplier_address": "22 Jurong Port Road, Singapore 619092",
            "supplier_gst_reg": "M99887766X",
            "customer_name": "Events Management Asia Ltd",
            "customer_address": "80 Middle Road #10-01, Singapore 188966",
            "description": "Corporate Catering Services - August Board Meeting",
            "excl_gst": 3200.00,
            "gst_rate_label": "6%",    # ← INJECTED: wrong rate label on PDF
            "gst_amount": 192.00,      # ← INJECTED: 6% of 3200; record has 224.00
            "total": 3392.00,
        },
        "injected_issue": "gst_amount_mismatch",
        "injected_issue_detail": (
            "PDF shows GST rate 6% and GST amount 192.00 but SAP record "
            "tax_total=224.00 (correct 7% of 3200). "
            "PDF understates GST by 32.00."
        ),
    },

    # ── Case 5 ── Supplier GST registration number absent from PDF ──────────
    {
        "record": {
            "doc_num": 3005,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-09-10",
            "card_name": "Fresh Food Distributors Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Fresh Produce Supply - September Delivery Batch 3",
            "line_total": 1500.00,
            "tax_total": 105.00,
        },
        "pdf": {
            "invoice_num": "INV-3005",
            "date": "2024-09-10",
            "supplier_name": "Fresh Food Distributors Pte Ltd",
            "supplier_address": "5 Senoko Way, Singapore 758057",
            "supplier_gst_reg": None,  # ← INJECTED: GST reg omitted from PDF
            "customer_name": "FoodChain Operations Pte Ltd",
            "customer_address": "25 Mandai Estate, Singapore 729933",
            "description": "Fresh Produce Supply - September Delivery Batch 3",
            "excl_gst": 1500.00,
            "gst_rate_label": "7%",
            "gst_amount": 105.00,
            "total": 1605.00,
        },
        "injected_issue": "supplier_gst_reg_absent",
        "injected_issue_detail": (
            "Supplier GST registration number not shown on the invoice face. "
            "IRAS para 7.1.4(d) requires the supplier's GST reg number. "
            "Input tax claim may be disallowable without this particular."
        ),
    },

    # ── Case 6 ── Invoice date outside the audit period ────────────────────
    # doc_date in the SAP record would be set by the user to match the PDF.
    # The SAP record itself carries the out-of-period date; the ISSUE is that
    # this document was included in a Q3 2024 period run.
    {
        "record": {
            "doc_num": 3006,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-10-05",   # outside Q3 2024 (period ends 2024-09-30)
            "card_name": "TechSupply Solutions Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Network Infrastructure Maintenance - October Support",
            "line_total": 7800.00,
            "tax_total": 546.00,
        },
        "pdf": {
            "invoice_num": "INV-3006",
            "date": "2024-10-05",       # ← INJECTED: outside Q3 2024 period
            "supplier_name": "TechSupply Solutions Pte Ltd",
            "supplier_address": "100 Beach Road #20-01, Singapore 189702",
            "supplier_gst_reg": "M12345678X",
            "customer_name": "LogiCo Singapore Pte Ltd",
            "customer_address": "3 Changi Business Park Vista, Singapore 486051",
            "description": "Network Infrastructure Maintenance - October Support",
            "excl_gst": 7800.00,
            "gst_rate_label": "7%",
            "gst_amount": 546.00,
            "total": 8346.00,
        },
        "injected_issue": "date_outside_period",
        "injected_issue_detail": (
            "PDF invoice date 2024-10-05 is outside the audit period "
            f"{GST_PERIOD_START} to {GST_PERIOD_END}. "
            "Document should not appear in the Q3 2024 F5 return."
        ),
    },

    # ── Case 7 ── Total inconsistency: PDF total != excl + GST on same PDF ─
    # The arithmetic on the PDF face itself is wrong (total overstated)
    {
        "record": {
            "doc_num": 3007,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-08-22",
            "card_name": "MarketSG Advertising Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Digital Marketing Campaign Services - Q3 2024",
            "line_total": 4200.00,
            "tax_total": 294.00,
        },
        "pdf": {
            "invoice_num": "INV-3007",
            "date": "2024-08-22",
            "supplier_name": "MarketSG Advertising Pte Ltd",
            "supplier_address": "14 Science Park Drive, Singapore 118228",
            "supplier_gst_reg": "M44556677X",
            "customer_name": "RetailPro Solutions Ltd",
            "customer_address": "60 Alexandra Terrace #08-18, Singapore 118502",
            "description": "Digital Marketing Campaign Services - Q3 2024",
            "excl_gst": 4200.00,
            "gst_rate_label": "7%",
            "gst_amount": 294.00,
            "total": 4530.00,           # ← INJECTED: should be 4494.00 (4200+294)
        },
        "injected_issue": "total_inconsistency",
        "injected_issue_detail": (
            "PDF total 4530.00 does not equal "
            "PDF excl_gst 4200.00 + PDF gst_amount 294.00 = 4494.00. "
            "Arithmetic error on the invoice face (overstated by 36.00)."
        ),
    },

    # ── Case 8 ── Combined: GST amount mismatch + supplier GST reg absent ──
    {
        "record": {
            "doc_num": 3008,
            "doc_type": "purchase_invoice",
            "doc_date": "2024-09-15",
            "card_name": "CleanSpace Facilities Pte Ltd",
            "line_index": 0,
            "vat_group": "SI",
            "line_description": "Building Cleaning and Maintenance Services - September",
            "line_total": 6000.00,
            "tax_total": 420.00,
        },
        "pdf": {
            "invoice_num": "INV-3008",
            "date": "2024-09-15",
            "supplier_name": "CleanSpace Facilities Pte Ltd",
            "supplier_address": "77 Science Park Drive, Singapore 118256",
            "supplier_gst_reg": None,  # ← INJECTED: GST reg omitted
            "customer_name": "PropMgmt Singapore Pte Ltd",
            "customer_address": "1 Marina Boulevard, Singapore 018989",
            "description": "Building Cleaning and Maintenance Services - September",
            "excl_gst": 6000.00,
            "gst_rate_label": "7%",
            "gst_amount": 360.00,      # ← INJECTED: 6% of 6000; record has 420.00
            "total": 6360.00,
        },
        "injected_issue": "combined",
        "injected_issue_detail": (
            "Two issues: (1) PDF shows GST 360.00 but record tax_total=420.00 "
            "(PDF applies 6% instead of 7%; understated by 60.00). "
            "(2) Supplier GST registration number absent from PDF face."
        ),
    },
]


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

# Layout constants (A4 = 595.28 x 841.89 pt; 1 cm = 28.35 pt)
PAGE_W, PAGE_H = A4
MARGIN = 2.0 * cm
INNER_W = PAGE_W - 2 * MARGIN

_GREY      = colors.HexColor("#4A4A4A")
_LIGHT     = colors.HexColor("#F5F5F5")
_RULE      = colors.HexColor("#CCCCCC")
_BLUE_DARK = colors.HexColor("#1A3A5C")


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _render_invoice(c: rl_canvas.Canvas, case: dict[str, Any]) -> None:
    """Render one Singapore tax invoice page onto canvas c."""
    pdf = case["pdf"]
    y = PAGE_H - MARGIN

    # ── Header block: supplier identity ──────────────────────────────────
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(_BLUE_DARK)
    c.drawString(MARGIN, y, pdf["supplier_name"])
    y -= 0.55 * cm

    c.setFont("Helvetica", 9)
    c.setFillColor(_GREY)
    c.drawString(MARGIN, y, pdf["supplier_address"])
    y -= 0.45 * cm

    if pdf["supplier_gst_reg"] is not None:
        c.drawString(MARGIN, y, f"GST Reg No: {pdf['supplier_gst_reg']}")
    else:
        # Intentionally blank — supplier_gst_reg_absent injected issue
        c.drawString(MARGIN, y, "GST Reg No: ")
    y -= 0.8 * cm

    # ── Horizontal rule ───────────────────────────────────────────────────
    c.setStrokeColor(_RULE)
    c.setLineWidth(0.5)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 0.6 * cm

    # ── TAX INVOICE title ─────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(_BLUE_DARK)
    c.drawCentredString(PAGE_W / 2, y, "TAX INVOICE")
    y -= 1.0 * cm

    # ── Invoice metadata (left) + Bill To (right) ─────────────────────────
    meta_x = MARGIN
    bill_x = PAGE_W / 2 + 0.5 * cm
    meta_y = y

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(_GREY)
    c.drawString(meta_x, meta_y, "Invoice No:")
    c.drawString(meta_x, meta_y - 0.5 * cm, "Invoice Date:")
    c.drawString(meta_x, meta_y - 1.0 * cm, "Currency:")
    c.drawString(meta_x, meta_y - 1.5 * cm, "GST Period:")

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)
    c.drawString(meta_x + 2.8 * cm, meta_y, pdf["invoice_num"])
    c.drawString(meta_x + 2.8 * cm, meta_y - 0.5 * cm, pdf["date"])
    c.drawString(meta_x + 2.8 * cm, meta_y - 1.0 * cm, "SGD")
    c.drawString(
        meta_x + 2.8 * cm,
        meta_y - 1.5 * cm,
        f"{GST_PERIOD_START} to {GST_PERIOD_END}",
    )

    # Bill To block
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(_GREY)
    c.drawString(bill_x, meta_y, "Bill To:")
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.black)
    c.drawString(bill_x, meta_y - 0.5 * cm, pdf["customer_name"])
    c.setFont("Helvetica", 9)
    c.setFillColor(_GREY)
    c.drawString(bill_x, meta_y - 1.0 * cm, pdf["customer_address"])

    y = meta_y - 2.2 * cm

    # ── Line items table header ────────────────────────────────────────────
    c.setFillColor(_LIGHT)
    c.setStrokeColor(_RULE)
    c.rect(MARGIN, y - 0.5 * cm, INNER_W, 0.55 * cm, fill=1, stroke=1)

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(_BLUE_DARK)
    cols = [MARGIN + 0.2 * cm, MARGIN + 1.5 * cm, PAGE_W - MARGIN - 3.5 * cm]
    c.drawString(cols[0], y - 0.35 * cm, "S/No")
    c.drawString(cols[1], y - 0.35 * cm, "Description")
    c.drawString(cols[2], y - 0.35 * cm, "Amount (SGD)")
    y -= 0.5 * cm

    # ── Single line item row ───────────────────────────────────────────────
    c.setStrokeColor(_RULE)
    c.setLineWidth(0.3)
    c.line(MARGIN, y - 0.45 * cm, PAGE_W - MARGIN, y - 0.45 * cm)

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)
    c.drawString(cols[0], y - 0.32 * cm, "1")
    c.drawString(cols[1], y - 0.32 * cm, pdf["description"])
    c.drawRightString(
        PAGE_W - MARGIN - 0.2 * cm, y - 0.32 * cm, _money(pdf["excl_gst"])
    )
    y -= 0.45 * cm

    # ── Totals block ───────────────────────────────────────────────────────
    y -= 0.4 * cm
    label_x = PAGE_W - MARGIN - 7.0 * cm
    value_x = PAGE_W - MARGIN - 0.2 * cm

    def _total_row(label: str, value: str, bold: bool = False) -> None:
        nonlocal y
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, 9)
        c.setFillColor(colors.black)
        c.drawString(label_x, y, label)
        c.drawRightString(value_x, y, value)
        y -= 0.5 * cm

    _total_row("Subtotal (excl. GST):", _money(pdf["excl_gst"]))
    _total_row(f"GST @ {pdf['gst_rate_label']}:", _money(pdf["gst_amount"]))

    # Rule above TOTAL
    c.setStrokeColor(_RULE)
    c.setLineWidth(0.5)
    c.line(label_x, y + 0.35 * cm, value_x, y + 0.35 * cm)

    _total_row("TOTAL (incl. GST):", _money(pdf["total"]), bold=True)

    y -= 0.4 * cm

    # ── Footer ─────────────────────────────────────────────────────────────
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(_GREY)
    c.drawString(
        MARGIN,
        y,
        "All amounts in Singapore Dollars (SGD). "
        "This is a computer-generated tax invoice.",
    )
    y -= 0.4 * cm
    c.drawString(
        MARGIN,
        y,
        f"GST is charged pursuant to the Goods and Services Tax Act (Cap. 117A). "
        f"GST Period: {GST_PERIOD_START} to {GST_PERIOD_END}.",
    )


# ---------------------------------------------------------------------------
# Generator entry point
# ---------------------------------------------------------------------------

def generate(output_dir: Path | None = None) -> Path:
    """Generate all PDFs and write fixtures_manifest.json.

    Args:
        output_dir: Target directory.  Defaults to the directory containing
                    this script (tests/fixtures/documents/).

    Returns:
        Path to the written fixtures_manifest.json.
    """
    out = output_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)

    manifest_cases = []

    for case in CASES:
        rec = case["record"]
        pdf_data = case["pdf"]
        doc_num = rec["doc_num"]
        pdf_filename = f"INV-{doc_num}.pdf"
        pdf_path = out / pdf_filename

        # invariant=1 fixes internal timestamps → byte-identical across runs
        c = rl_canvas.Canvas(str(pdf_path), pagesize=A4, invariant=1)
        _render_invoice(c, case)
        c.showPage()
        c.save()

        manifest_cases.append({
            "doc_num": doc_num,
            "pdf_filename": pdf_filename,
            "injected_issue": case["injected_issue"],
            "injected_issue_detail": case["injected_issue_detail"],
            "line_item_record": rec,
            "pdf_values": {
                k: v for k, v in pdf_data.items()
                if k not in ("supplier_name", "supplier_address",
                             "customer_name", "customer_address")
            },
        })
        print(f"  wrote {pdf_filename}  ({case['injected_issue']})")

    manifest = {
        "_meta": {
            "description": (
                "Controlled fixtures. Labels are author-known injected issues "
                "for build/demo only — NOT specialist-validated ground truth (T2.13)."
            ),
            "generator": "tests/fixtures/documents/generate_invoices.py",
            "seed": SEED,
            "gst_period": {"start": GST_PERIOD_START, "end": GST_PERIOD_END},
            "line_item_shape": (
                "doc_num, doc_type, doc_date, card_name, line_index, "
                "vat_group, line_description, line_total, tax_total"
            ),
            "join_key": "doc_num",
            "injected_issue_types": [
                "none",
                "gst_amount_mismatch",
                "supplier_gst_reg_absent",
                "date_outside_period",
                "total_inconsistency",
                "combined",
            ],
        },
        "cases": manifest_cases,
    }

    manifest_path = out / "fixtures_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  wrote fixtures_manifest.json  ({len(CASES)} cases)")
    return manifest_path


if __name__ == "__main__":
    print(f"Generating T2.8 document-ingestion fixtures → {DOCS_DIR}")
    generate()
    print("Done.")
    sys.exit(0)
