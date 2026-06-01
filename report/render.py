"""
report/render.py — reportlab Platypus PDF renderer.

Consumes ReportModel only; never touches CompileOutput, never calls datetime.now().
generated_at is taken from model.cover.generated_at.
A4 page, Helvetica fixed fonts throughout.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from report.report import ReportModel

# ── Page geometry ─────────────────────────────────────────────────────────────

_W, _H = A4
_MARGIN = 2.0 * cm
_UW = _W - 2 * _MARGIN   # usable width ≈ 17.0 cm
_FOOTER_Y = 0.9 * cm     # footer baseline from bottom edge

# ── Styles ────────────────────────────────────────────────────────────────────

_base = getSampleStyleSheet()


def _style(name: str, parent: str = "Normal", **kw) -> ParagraphStyle:
    return ParagraphStyle(name, parent=_base[parent], **kw)


_H1      = _style("AA_H1",   "Heading1", fontSize=15, fontName="Helvetica-Bold",   spaceAfter=6)
_H2      = _style("AA_H2",   "Heading2", fontSize=11, fontName="Helvetica-Bold",   spaceAfter=4, spaceBefore=12)
_H3      = _style("AA_H3",   "Heading3", fontSize=9,  fontName="Helvetica-Bold",   spaceAfter=3, spaceBefore=8)
_BODY    = _style("AA_Body",             fontSize=9,  fontName="Helvetica",         spaceAfter=3)
_SMALL   = _style("AA_Sm",              fontSize=8,  fontName="Helvetica",         spaceAfter=2)
_SMLX    = _style("AA_SmX",             fontSize=7,  fontName="Helvetica-Oblique", spaceAfter=2)
_META    = _style("AA_Meta",             fontSize=9,  fontName="Helvetica",         spaceAfter=3)
_CELL    = _style("AA_Cell",             fontSize=8,  fontName="Helvetica",         leading=10)
_CELLB   = _style("AA_CellB",           fontSize=8,  fontName="Helvetica-Bold",    leading=10)
# Code column: no intra-word splitting so "NO_GST_REG" always sits on one line
_CELL_CODE = _style("AA_CellCode",      fontSize=8,  fontName="Helvetica",         leading=10,
                     splitLongWords=0)
# Recommendation sub-line inside description cell
_CELL_REC  = _style("AA_CellRec",       fontSize=7,  fontName="Helvetica-Oblique", leading=9,
                     textColor=colors.HexColor("#5D6D7E"))

# ── Colour palette ────────────────────────────────────────────────────────────

_HEADER_BG = colors.HexColor("#2C3E50")
_STRIPE    = colors.HexColor("#F0F3F4")
_GRID_LINE = colors.HexColor("#BDC3C7")
_FOOTER_FG = colors.HexColor("#7F8C8D")
_SEV_HEX   = {"HIGH": "#C0392B", "MEDIUM": "#E67E22", "LOW": "#27AE60"}

# ── Box labels (display order matches the F5 form) ────────────────────────────

_BOX_LABELS: dict[str, str] = {
    "box_1_standard_rated_sales": "Box 1 — Standard-rated supplies",
    "box_2_zero_rated_sales":     "Box 2 — Zero-rated supplies",
    "box_3_exempt_sales":         "Box 3 — Exempt supplies",
    "box_4_total_sales":          "Box 4 — Total value of taxable supplies",
    "box_5_taxable_purchases":    "Box 5 — Taxable purchases",
    "box_6_output_tax":           "Box 6 — Output tax due",
    "box_7_input_tax":            "Box 7 — Input tax and refunds claimed",
    "box_8_net_gst":              "Box 8 — Net GST to be paid / (refunded)",
}

# ── Timestamp formatter (display-only; never calls datetime.now()) ────────────

def _fmt_timestamp(iso: str) -> str:
    """Parse a stored ISO 8601 string into a reader-friendly UTC display string."""
    try:
        dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return iso  # fallback: render verbatim if parse fails

# ── Table helpers ─────────────────────────────────────────────────────────────

def _base_table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  _HEADER_BG),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTNAME",       (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 0), (-1, -1), 8),
        ("LEADING",        (0, 0), (-1, -1), 10),
        ("GRID",           (0, 0), (-1, -1), 0.25, _GRID_LINE),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",     (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 3),
        ("LEFTPADDING",    (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _STRIPE]),
    ])


def _table(col_widths: list, header: list, rows: list) -> Table:
    return Table(
        [header] + rows,
        colWidths=col_widths,
        style=_base_table_style(),
        repeatRows=1,
    )

# ── Cell formatters ───────────────────────────────────────────────────────────

def _p(text, style: ParagraphStyle = _CELL) -> Paragraph:
    return Paragraph(str(text) if text is not None else "—", style)


def _sgd(value) -> str:
    return f"{value:,.2f}" if value is not None else "—"


def _sev_cell(sev: str) -> Paragraph:
    hex_c = _SEV_HEX.get(sev, "#000000")
    return Paragraph(f'<font color="{hex_c}"><b>{sev}</b></font>', _CELL)


def _desc_cell(description: str | None, recommendation: str | None) -> list[Paragraph]:
    """Return one or two stacked Paragraphs for the description column.

    Recommendation is rendered on its own line in italic grey so it is
    visually distinct from the finding description. No separator glyphs used.
    """
    result = [_p(description or "—")]
    if recommendation:
        result.append(Paragraph(f"Recommendation: {recommendation}", _CELL_REC))
    return result

# ── Numbered canvas (Page X of Y footer) ─────────────────────────────────────

def _make_numbered_canvas(client_name: str):
    """Return a Canvas subclass that draws a footer with page X of Y on every page."""

    class _NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict] = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            states = self._saved_page_states[:]   # capture before __dict__ mutations
            total = len(states)
            for page_num, state in enumerate(states, 1):
                self.__dict__.update(state)
                self._draw_footer(page_num, total)
                Canvas.showPage(self)
            Canvas.save(self)

        def _draw_footer(self, page_num: int, total: int) -> None:
            self.saveState()
            self.setFont("Helvetica", 7)
            self.setFillColor(_FOOTER_FG)
            y = _FOOTER_Y
            self.drawString(_MARGIN, y, "Working paper — not an IRAS submission")
            right = (
                f"AgentAssist GST Compliance Review — {client_name} "
                f"— Page {page_num} of {total}"
            )
            self.drawRightString(_W - _MARGIN, y, right)
            self.restoreState()

    return _NumberedCanvas

# ── Section renderers ─────────────────────────────────────────────────────────

def _cover(m: ReportModel, story: list) -> None:
    story.append(Spacer(1, 1.2 * cm))
    story.append(Paragraph("AgentAssist GST Compliance Review", _H1))
    story.append(Paragraph("IRAS ASK Annual Review — Transaction-Level Analysis", _BODY))
    story.append(HRFlowable(width=_UW, thickness=2, color=_HEADER_BG))
    story.append(Spacer(1, 0.4 * cm))
    for label, value in [
        ("Client",           m.cover.client_name),
        ("GST Registration", m.cover.gst_registration_number or "—"),
        ("Review Period",    f"{m.cover.period_start}  to  {m.cover.period_end}"),
        ("Reviewed by",      f"{m.cover.reviewer_name},  {m.cover.firm_name}"),
        ("Generated",        _fmt_timestamp(m.cover.generated_at)),
    ]:
        story.append(Paragraph(f"<b>{label}:</b>  {value}", _META))
    story.append(PageBreak())


def _scope(m: ReportModel, story: list) -> None:
    story.append(Paragraph("1.  Scope — Items Examined", _H2))

    hdr = [_p("Document type", _CELLB), _p("Count", _CELLB)]
    rows = [
        [_p(dt.replace("_", " ").title()), _p(str(cnt))]
        for dt, cnt in sorted(m.scope.items_examined.items())
    ]
    story.append(_table([_UW * 0.68, _UW * 0.32], hdr, rows))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Foreign Currency Invoices Excluded from Box Totals", _H3))
    if m.scope.fx_excluded:
        fx_w = [2.4*cm, 2.2*cm, 4.5*cm, 2.1*cm, 2.8*cm, 3.0*cm]
        fx_h = [_p(h, _CELLB) for h in ["Doc #", "Date", "Counterparty", "Currency", "Amount", "Type"]]
        fx_r = [
            [
                _p(str(f["doc_num"])), _p(f.get("doc_date", "")),
                _p(f.get("card_name", "")), _p(f.get("currency", "")),
                _p(_sgd(f.get("doc_total"))), _p(f.get("type", "")),
            ]
            for f in m.scope.fx_excluded
        ]
        story.append(_table(fx_w, fx_h, fx_r))
    else:
        story.append(Paragraph("None in period.", _SMALL))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Credit Notes Applied", _H3))
    if m.scope.credit_notes_applied:
        cn_w = [2.2*cm, 2.2*cm, 3.5*cm, 3.0*cm, 1.8*cm, 2.2*cm, 2.1*cm]
        cn_h = [_p(h, _CELLB) for h in
                ["Doc #", "Date", "Counterparty", "Type", "VG", "Line Total", "Tax Total"]]
        cn_r = [
            [
                _p(str(c["doc_num"])), _p(c.get("doc_date", "")),
                _p(c.get("card_name", "")), _p(c.get("type", "")),
                _p(c.get("vat_group", "")),
                _p(_sgd(c.get("line_total_applied"))),
                _p(_sgd(c.get("tax_total_applied"))),
            ]
            for c in m.scope.credit_notes_applied
        ]
        story.append(_table(cn_w, cn_h, cn_r))
    else:
        story.append(Paragraph("None in period.", _SMALL))


def _f5_boxes(m: ReportModel, story: list) -> None:
    story.append(Paragraph("2.  GST F5 Return — Box Figures", _H2))
    story.append(Paragraph(
        "SGD. Computed from SAP B1 invoice and credit note lines by calculate_f5_return.",
        _SMLX,
    ))
    story.append(Spacer(1, 0.2 * cm))
    hdr = [_p(h, _CELLB) for h in ["Box", "SGD Value", "VatGroups in period"]]
    rows = [
        [
            _p(_BOX_LABELS.get(a.box_name, a.box_name)),
            _p(_sgd(a.box_value)),
            _p(", ".join(a.vat_groups) if a.vat_groups else "—"),
        ]
        for a in m.f5_boxes.attribution
    ]
    story.append(_table([7.5*cm, 3.5*cm, 6.0*cm], hdr, rows))


def _findings(m: ReportModel, story: list) -> None:
    story.append(Paragraph("3.  Findings by IRAS ASK Template", _H2))
    story.append(Paragraph(
        f"Total: {m.findings.total_findings} finding(s). "
        "Sorted HIGH &gt; MEDIUM &gt; LOW, then by document number within each severity.",
        _SMLX,
    ))

    # Column widths: Code column is 2.0 cm — wide enough for NO_GST_REG at 8 pt Helvetica.
    f_cols = [1.5*cm, 1.4*cm, 2.0*cm, 3.0*cm, 1.2*cm, 1.8*cm, 2.0*cm, 4.1*cm]
    f_hdr  = [_p(h, _CELLB) for h in
              ["Severity", "Doc #", "Date", "Counterparty", "VG", "Amount", "Code", "Description"]]

    for grp in m.findings.groups:
        if not grp.findings:
            continue
        f_rows = []
        for f in grp.findings:
            # Amount: use doc_total (labelled in header as "Amount") when line_total
            # is unavailable (e.g. NO_GST_REG has no per-line classify data).
            if f.line_total is not None:
                amount = _sgd(f.line_total)
            elif f.doc_total is not None:
                amount = _sgd(f.doc_total) + " (doc total)"
            else:
                amount = "—"
            f_rows.append([
                _sev_cell(f.severity),
                _p(str(f.doc_num) if f.doc_num is not None else "—"),
                _p(f.doc_date or "—"),
                _p(f.card_name or "—"),
                _p(f.vat_group or "—"),
                _p(amount),
                # _CELL_CODE: splitLongWords=0 keeps "NO_GST_REG" on a single line
                Paragraph(f.error_code, _CELL_CODE),
                _desc_cell(f.description, f.recommendation),
            ])

        # KeepTogether: template heading stays with the start of its table
        group_block = [
            Spacer(1, 0.35 * cm),
            Paragraph(grp.template_ref["label"], _H3),
            _table(f_cols, f_hdr, f_rows),
        ]
        story.append(KeepTogether(group_block))


def _cross_findings(m: ReportModel, story: list) -> None:
    story.append(Paragraph("4.  Cross-Finding Analysis", _H2))
    if not m.cross_findings.multi_error_docs:
        story.append(Paragraph(
            "No documents carry more than one distinct error code in this period.", _BODY
        ))
        return
    story.append(Paragraph(
        "The following documents carry more than one distinct error code. "
        "Prioritise these for review.",
        _BODY,
    ))
    story.append(Spacer(1, 0.2 * cm))
    cols = [2.0*cm, 4.0*cm, 5.0*cm, _UW - 11.0*cm]
    hdr = [_p(h, _CELLB) for h in ["Doc #", "Error codes", "Counterparty", "Appendix 1 categories"]]
    rows = [
        [
            _p(str(e.doc_num)),
            _p(", ".join(e.error_codes)),
            _p(e.findings[0].card_name if e.findings else "—"),
            _p("; ".join(dict.fromkeys(f.appendix1_category for f in e.findings))),
        ]
        for e in m.cross_findings.multi_error_docs
    ]
    story.append(_table(cols, hdr, rows))


def _judgment(m: ReportModel, story: list) -> None:
    story.append(Paragraph("5.  Judgment — Items for Reviewer Decision", _H2))
    story.append(Paragraph(
        "AgentAssist surfaces the following candidates. "
        "Professional judgment by the reviewer of record is required for each group.",
        _BODY,
    ))
    for jg in m.judgment.groups:
        story.append(Spacer(1, 0.25 * cm))
        # Use the explicit display_title set in sections.py — no slug-to-title conversion
        story.append(Paragraph(jg.display_title, _H3))
        story.append(Paragraph(jg.judgment_question, _BODY))
        story.append(Paragraph(
            "<b>Document numbers requiring review:</b>  "
            + ", ".join(str(d) for d in jg.doc_nums),
            _SMALL,
        ))


def _not_examined(m: ReportModel, story: list) -> None:
    story.append(Paragraph("6.  Items Not Examined", _H2))
    story.append(Paragraph(
        "The following checks are outside the scope of this automated review. "
        "The reviewer of record should determine whether any require additional action.",
        _BODY,
    ))
    for item in m.not_examined.items:
        story.append(Paragraph(f"•  {item}", _SMALL))


def _signature(m: ReportModel, story: list) -> None:
    story.append(PageBreak())
    story.append(Paragraph("Declaration and Sign-Off", _H2))
    story.append(Paragraph(
        "I have reviewed the findings in this report, exercised professional judgment "
        "on the items listed in Section 5, and confirm the accuracy of the "
        "filing decision.",
        _BODY,
    ))
    story.append(Spacer(1, 0.4 * cm))
    for label, value in [
        ("Reviewer",     m.signature.reviewer_name),
        ("Firm",         m.signature.firm_name),
        ("GST Reg. No.", m.signature.gst_registration_number or "—"),
    ]:
        story.append(Paragraph(f"<b>{label}:</b>  {value}", _META))

    story.append(Spacer(1, 1.5 * cm))
    # Ruled signature line — mirrors the IRAS Declaration Form on Completing Annual Review
    story.append(HRFlowable(width=_UW * 0.55, thickness=0.75, color=colors.black))
    story.append(Paragraph(
        "Signature" + " " * 16 + "Date: _______________",
        _SMALL,
    ))
    story.append(Spacer(1, 1.2 * cm))
    story.append(HRFlowable(width=_UW, thickness=0.25, color=_GRID_LINE))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(m.signature.disclaimer, _SMLX))


# ── Public entry point ────────────────────────────────────────────────────────

def render_pdf(model: ReportModel, out_path: str | Path) -> Path:
    """
    Render a ReportModel to PDF and return the output Path.

    out_path's parent directory is created if it does not exist.
    generated_at is taken from model.cover.generated_at; no datetime.now() is called
    anywhere in this module.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN + 0.4 * cm,   # extra clearance for footer
        title=(
            f"AgentAssist GST Review — "
            f"{model.cover.period_start} to {model.cover.period_end}"
        ),
        author=f"{model.cover.reviewer_name}, {model.cover.firm_name}",
    )

    story: list = []
    _cover(model, story)
    _scope(model, story)
    _f5_boxes(model, story)
    _findings(model, story)
    _cross_findings(model, story)
    _judgment(model, story)
    _not_examined(model, story)
    _signature(model, story)

    NC = _make_numbered_canvas(model.cover.client_name)
    doc.build(story, canvasmaker=NC)
    return out_path
