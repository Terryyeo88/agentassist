"""tests/test_ingest_label_tolerance.py — T-E(2a): born-digital extraction label tolerance.

The T-E(2) measurement stopped at M3: zero document checks fire over the 2026Q2 corpus
because ingest's patterns are fitted to generate_invoices.py's own labels ("Invoice
Date:", "Subtotal (excl. GST):", "TOTAL (incl. GST):"), while the corpus PDFs print
"Date:", "Subtotal:", "Total:". The legibility gate then (correctly) refused every
document: key field invoice_date absent.

THE RULE: a wrong extracted value is worse than an absent one. T1 therefore asserts
VALUES against a hand-read answer key (authored from the M1 raw-text print, not from
any regex), and T5 pins that no broadened pattern can mistake a due/payment/statement
date for the invoice date. T2 pins the SAP control set byte-identical.

M2 also showed the CURRENT extractor already returns two wrong values on the corpus:
supplier_name = "TAX INVOICE" (first-line heuristic; the corpus puts the header first
and the supplier second) and BILL-3005 invoice_number = "INV-7742" (the bare INV-\\d+
pattern grabbing the vendor's Reference). The answer key makes both right.
"""
from pathlib import Path

import pytest

from documents.ingest import ingest
from documents.legibility import assess_legibility

_REPO = Path(__file__).resolve().parent.parent
_XERO = _REPO / "tests" / "fixtures" / "xero-demo-2026Q2" / "source_documents"
_SAP = _REPO / "tests" / "fixtures" / "documents"

_FIELDS = ("supplier_name", "supplier_gst_regno", "invoice_number", "invoice_date",
           "total_excl_gst", "gst_rate", "gst_amount", "total_incl_gst")

# T1 answer key — hand-read from the M1 raw-text print of each corpus PDF.
_XERO_KEY = {
    "BILL-3001": ("GoodVendor Pte Ltd", "200611111A", "BILL-3001", "2026-04-10", 2000.0, "9%", 180.0, 2180.0),
    "BILL-3002": ("OldRate Supplies Pte Ltd", "200722222B", "BILL-3002", "2026-04-22", 4000.0, "9%", 360.0, 4360.0),
    "BILL-3003": ("NoReg Trading", None, "BILL-3003", "2026-05-06", 1500.0, "9%", 135.0, 1635.0),
    "BILL-3004": ("DupSupplier Pte Ltd", "200733333C", "BILL-3004", "2026-05-12", 2500.0, "9%", 225.0, 2725.0),
    "BILL-3005": ("DupSupplier Pte Ltd", "200733333C", "BILL-3005", "2026-05-19", 2500.0, "9%", 225.0, 2725.0),
    "BILL-3006": ("Marina Fine Dining Pte Ltd", "200744444D", "BILL-3006", "2026-05-28", 800.0, "9%", 72.0, 872.0),
    "BILL-3007": ("AutoCare SG Pte Ltd", "200755555E", "BILL-3007", "2026-06-03", 1200.0, "9%", 108.0, 1308.0),
    "INV-2001": ("Cloudassist Services Pte Ltd", "201711175C", "INV-2001", "2026-04-08", 10000.0, "9%", 900.0, 10900.0),
    "INV-2002": ("Cloudassist Services Pte Ltd", "201711175C", "INV-2002", "2026-04-15", 5000.0, "9%", 0.0, 5000.0),
    "INV-2003": ("Cloudassist Services Pte Ltd", "201711175C", "INV-2003", "2026-05-02", 3000.0, "9%", 270.0, 3270.0),
}

# T2 control key — the M3 print of the CURRENT extractor over the 8 SAP fixtures.
# These values must not move by one byte.
_SAP_KEY = {
    "INV-3001": ("TechSupply Solutions Pte Ltd", "M12345678X", "INV-3001", "2024-07-15", 5000.0, "7%", 350.0, 5350.0),
    "INV-3002": ("Office Essentials Pte Ltd", "M87654321X", "INV-3002", "2024-08-20", 2800.0, "7%", 196.0, 2996.0),
    "INV-3003": ("Heavy Equipment Rentals Pte Ltd", "M11223344X", "INV-3003", "2024-07-30", 12000.0, "7%", 900.0, 12900.0),
    "INV-3004": ("Premium Catering Services Pte Ltd", "M99887766X", "INV-3004", "2024-08-05", 3200.0, "6%", 192.0, 3392.0),
    "INV-3005": ("Fresh Food Distributors Pte Ltd", None, "INV-3005", "2024-09-10", 1500.0, "7%", 105.0, 1605.0),
    "INV-3006": ("TechSupply Solutions Pte Ltd", "M12345678X", "INV-3006", "2024-10-05", 7800.0, "7%", 546.0, 8346.0),
    "INV-3007": ("MarketSG Advertising Pte Ltd", "M44556677X", "INV-3007", "2024-08-22", 4200.0, "7%", 294.0, 4530.0),
    "INV-3008": ("CleanSpace Facilities Pte Ltd", None, "INV-3008", "2024-09-15", 6000.0, "7%", 360.0, 6360.0),
}


def _tuple(e):
    return tuple(getattr(e, f) for f in _FIELDS)


@pytest.mark.parametrize("stem", sorted(_XERO_KEY))
def test_t1_xero_corpus_extracts_the_answer_key(stem):
    e = ingest(_XERO / f"{stem}.pdf")
    assert _tuple(e) == _XERO_KEY[stem], f"{stem}: {_tuple(e)} != key"


@pytest.mark.parametrize("stem", sorted(_SAP_KEY))
def test_t2_sap_control_set_does_not_move(stem):
    e = ingest(_SAP / f"{stem}.pdf")
    assert _tuple(e) == _SAP_KEY[stem], f"{stem}: control moved: {_tuple(e)}"


def _pdf(tmp_path, name, lines):
    """Minimal born-digital PDF via reportlab (a dependency the suite already carries)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    p = tmp_path / name
    c = canvas.Canvas(str(p), pagesize=A4)
    y = 800
    for ln in lines:
        c.drawString(50, y, ln)
        y -= 20
    c.save()
    return p


def test_t3_invoice_date_label_beats_bare_date(tmp_path):
    p = _pdf(tmp_path, "both.pdf", [
        "Some Supplier Pte Ltd",
        "GST Reg No: 200600000Z",
        "Invoice No: X-1",
        "Invoice Date: 2026-01-15",
        "Date: 2026-02-20",
        "Subtotal: 100.00",
        "GST @ 9%: 9.00",
        "Total: 109.00",
    ])
    e = ingest(p)
    assert e.invoice_date == "2026-01-15", (
        "the specific label must win; the general pattern is a fallback, never a competitor"
    )


def test_t4_no_date_stays_absent_and_refused(tmp_path):
    p = _pdf(tmp_path, "nodate.pdf", [
        "Some Supplier Pte Ltd",
        "GST Reg No: 200600000Z",
        "Invoice No: X-2",
        "Subtotal: 100.00",
        "GST @ 9%: 9.00",
        "Total: 109.00",
    ])
    e = ingest(p)
    assert e.invoice_date is None
    assert assess_legibility(e).needs_manual_review, (
        "broadening must not make absence disappear — honest refusal is the protected thing"
    )


@pytest.mark.parametrize("label", ["Due Date:", "Payment Date:", "Statement Date:", "Due:"])
def test_t5_other_dates_are_never_the_invoice_date(tmp_path, label):
    p = _pdf(tmp_path, "other.pdf", [
        "Some Supplier Pte Ltd",
        "GST Reg No: 200600000Z",
        "Invoice No: X-3",
        f"{label} 2026-03-31",
        "Subtotal: 100.00",
        "GST @ 9%: 9.00",
        "Total: 109.00",
    ])
    e = ingest(p)
    assert e.invoice_date is None, f"{label!r} must never be extracted as the invoice date"


def test_t6_fields_present_is_computed(tmp_path):
    e = ingest(_XERO / "BILL-3003.pdf")           # regno genuinely absent on the face
    assert e.fields_present["supplier_gst_regno"] is False
    assert e.fields_present["invoice_date"] is True
    assert e.fields_present["gst_amount"] is True
    for f in _FIELDS:
        assert e.fields_present[f] == (getattr(e, f) is not None)
