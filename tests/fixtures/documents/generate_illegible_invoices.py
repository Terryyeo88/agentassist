#!/usr/bin/env python3
"""tests/fixtures/documents/generate_illegible_invoices.py — T2.14 hardening.

An APPEND-ONLY companion to the locked `generate_invoices.py` (which is NOT
edited). It draws BORN-DIGITAL Singapore-tax-invoice PDFs whose text layer is
extractable by `documents.ingest`, but which are deliberately ILLEGIBLE in the
mechanical sense the T2.14 gate keys on:

    draw_missing_gst_amount(...)   — omits the "GST @ NN%: <amount>" line, so
                                     `ingest()` yields gst_amount == None
                                     (a KEY field absent).
    draw_calendar_invalid_date(...) — renders "Invoice Date: 2024-13-45", which
                                     PASSES ingest's structural date regex but is
                                     not a real calendar date (the open-item-#28
                                     motivating case).
    draw_legible_control(...)      — a fully-legible invoice with a GST-amount
                                     discrepancy, to prove the generator does NOT
                                     spuriously trip the gate and that reconcile
                                     still runs over its output.

These are SYNTHETIC born-digital PDFs — the accepted proxy for the born-digital
path (Q1). The image-only-scan / multimodal path is deliberately OUT OF SCOPE
here (Q2): reportlab always emits a text layer, so these fixtures always route
born-digital, and the multimodal null-count branch stays on constructed inputs.

Determinism: `Canvas(invariant=1)` fixes reportlab's internal timestamps, so
re-running produces byte-identical PDFs. No network, no SAP, no anthropic import
— pure stdlib + reportlab, exactly like the locked generator.

The helpers write `INV-<doc_num>.pdf` into a caller-supplied directory (default a
fresh path the test hands in via tmp_path), matching
`documents.provider.FixtureDocumentProvider`'s `INV-<doc_num>.pdf` convention so
the test can feed them through `run_documents_pass` with zero committed binary.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas

# Layout constants mirror generate_invoices.py so pdfplumber extracts the same
# label/value line joins the ingest regexes depend on (label + value share a
# y-coordinate → pdfplumber returns them on one line).
PAGE_W, PAGE_H = A4
MARGIN = 2.0 * cm
INNER_W = PAGE_W - 2 * MARGIN

_GREY = colors.HexColor("#4A4A4A")
_RULE = colors.HexColor("#CCCCCC")
_BLUE_DARK = colors.HexColor("#1A3A5C")

GST_PERIOD_START = "2024-07-01"
GST_PERIOD_END = "2024-09-30"


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _render(
    pdf_path: Path,
    *,
    supplier_name: str = "TechSupply Solutions Pte Ltd",
    supplier_gst_reg: str | None = "M12345678X",
    invoice_num: str = "INV-4000",
    date: str = "2024-07-15",
    excl_gst: float = 5000.00,
    gst_rate_label: str = "7%",
    gst_amount: float = 350.00,
    total: float = 5350.00,
    omit_gst_line: bool = False,
) -> Path:
    """Draw one born-digital invoice page. When omit_gst_line=True the
    "GST @ NN%: <amount>" line is not drawn, so ingest's GST regex finds no
    match and returns gst_amount == None."""
    c = rl_canvas.Canvas(str(pdf_path), pagesize=A4, invariant=1)
    y = PAGE_H - MARGIN

    # Supplier identity (first non-empty line → ingest supplier_name).
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(_BLUE_DARK)
    c.drawString(MARGIN, y, supplier_name)
    y -= 0.55 * cm

    c.setFont("Helvetica", 9)
    c.setFillColor(_GREY)
    reg_text = f"GST Reg No: {supplier_gst_reg}" if supplier_gst_reg is not None else "GST Reg No: "
    c.drawString(MARGIN, y, reg_text)
    y -= 0.8 * cm

    c.setStrokeColor(_RULE)
    c.setLineWidth(0.5)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 0.6 * cm

    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(_BLUE_DARK)
    c.drawCentredString(PAGE_W / 2, y, "TAX INVOICE")
    y -= 1.0 * cm

    # Metadata block — label at meta_x, value at meta_x + 2.8cm, SAME y, so
    # pdfplumber joins "Invoice Date:" + the date on one extracted line.
    meta_x = MARGIN
    meta_y = y
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(_GREY)
    c.drawString(meta_x, meta_y, "Invoice No:")
    c.drawString(meta_x, meta_y - 0.5 * cm, "Invoice Date:")

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)
    c.drawString(meta_x + 2.8 * cm, meta_y, invoice_num)
    c.drawString(meta_x + 2.8 * cm, meta_y - 0.5 * cm, date)
    y = meta_y - 1.6 * cm

    # Single line item.
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.black)
    c.drawString(MARGIN, y, "1")
    c.drawString(MARGIN + 1.5 * cm, y, "Services rendered")
    c.drawRightString(PAGE_W - MARGIN - 0.2 * cm, y, _money(excl_gst))
    y -= 0.8 * cm

    # Totals block — label at label_x, value right-aligned at value_x, SAME y.
    label_x = PAGE_W - MARGIN - 7.0 * cm
    value_x = PAGE_W - MARGIN - 0.2 * cm

    def _total_row(label: str, value: str, bold: bool = False) -> None:
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        c.setFillColor(colors.black)
        c.drawString(label_x, y, label)
        c.drawRightString(value_x, y, value)
        y -= 0.5 * cm

    _total_row("Subtotal (excl. GST):", _money(excl_gst))
    if not omit_gst_line:
        _total_row(f"GST @ {gst_rate_label}:", _money(gst_amount))
    _total_row("TOTAL (incl. GST):", _money(total), bold=True)

    c.showPage()
    c.save()
    return pdf_path


def draw_missing_gst_amount(out_dir: Path | str, doc_num: int = 4001) -> Path:
    """Illegible: the GST-amount line is omitted → ingest gst_amount == None."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return _render(out / f"INV-{doc_num}.pdf", invoice_num=f"INV-{doc_num}", omit_gst_line=True)


def draw_calendar_invalid_date(out_dir: Path | str, doc_num: int = 4002) -> Path:
    """Illegible: a regex-passing but calendar-impossible date (open item #28)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return _render(out / f"INV-{doc_num}.pdf", invoice_num=f"INV-{doc_num}", date="2024-13-45")


def draw_legible_control(out_dir: Path | str, doc_num: int = 4003) -> Path:
    """Legible control with a GST-amount discrepancy vs the SAP record — proves
    the generator does NOT trip the gate and that reconcile still runs. gst_amount
    900.00 is present and valid; a paired line_item with tax_total 840.00 yields a
    gst_amount_mismatch reconcile candidate."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return _render(
        out / f"INV-{doc_num}.pdf",
        invoice_num=f"INV-{doc_num}",
        excl_gst=12000.00,
        gst_amount=900.00,
        total=12900.00,
    )
