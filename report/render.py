"""
report/render.py — ReportLab Platypus PDF renderer for the GST compliance report.

Accepts a fully-built ReportModel and writes a single A4 PDF.  All content is
derived from the model; this module never reads files, calls SAP, or calls
datetime.now() — generated_at is taken from model.cover.generated_at so the
rendered timestamp matches when the chain ran, not when the PDF was built.

Rendering pipeline:
    1. render_pdf() creates a SimpleDocTemplate and an empty story list.
    2. Eight section renderers (_cover, _scope, _f5_boxes, _findings,
       _cross_findings, _judgment, _not_examined, _signature) each append
       ReportLab Flowable objects (Paragraph, Table, Spacer, etc.) to the story.
    3. doc.build(story, canvasmaker=_NumberedCanvas) runs the Platypus layout
       engine, which calls _NumberedCanvas instead of the default Canvas.
    4. _NumberedCanvas intercepts showPage() calls to buffer page state, then
       replays all pages in save() — the only point where the total page count
       is known — to stamp the "Page X of Y" footer on every page.

Design constraints:
    * Helvetica fixed fonts throughout (no font embedding required; universally
      available in PDF readers).
    * All style names are prefixed "AA_" to avoid collision with ReportLab's
      built-in stylesheet names (Normal, Heading1, etc.).
    * Column widths in each table are tuned to sum to _UW (≈ 17.0 cm) so tables
      fill the usable width exactly without overflow.

Dependencies:
    reportlab     — Platypus layout engine and PDF generation
    report.report — ReportModel dataclass (the only input to render_pdf)

Exports:
    render_pdf — build a PDF from a ReportModel and return the output Path
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

# A4 tuple unpacked once; _W and _H are referenced throughout for right-align math.
_W, _H = A4
_MARGIN = 2.0 * cm
_UW = _W - 2 * _MARGIN   # usable width ≈ 17.0 cm
_FOOTER_Y = 0.9 * cm     # footer baseline from bottom edge

# ── Styles ────────────────────────────────────────────────────────────────────

_base = getSampleStyleSheet()


def _style(name: str, parent: str = "Normal", **kw) -> ParagraphStyle:
    """Create a named ParagraphStyle inheriting from a base stylesheet entry.

    All styles defined here use the "AA_" prefix to avoid collision with
    ReportLab's built-in names (Normal, Heading1, etc.) in the shared
    getSampleStyleSheet() registry.

    Args:
        name:   Unique style name; must begin with "AA_" by convention.
        parent: Name of the parent style in the base stylesheet (default 'Normal').
        **kw:   ParagraphStyle keyword overrides (fontSize, fontName, spaceAfter, etc.).

    Returns:
        ParagraphStyle: A new style object ready for use in Paragraph() calls.
    """
    return ParagraphStyle(name, parent=_base[parent], **kw)


_H1      = _style("AA_H1",   "Heading1", fontSize=15, fontName="Helvetica-Bold",   spaceAfter=6)
_H2      = _style("AA_H2",   "Heading2", fontSize=11, fontName="Helvetica-Bold",   spaceAfter=4, spaceBefore=12)
_H3      = _style("AA_H3",   "Heading3", fontSize=9,  fontName="Helvetica-Bold",   spaceAfter=3, spaceBefore=8)
_BODY    = _style("AA_Body",             fontSize=9,  fontName="Helvetica",         spaceAfter=3)
_SMALL   = _style("AA_Sm",              fontSize=8,  fontName="Helvetica",         spaceAfter=2)
_SMLX    = _style("AA_SmX",             fontSize=7,  fontName="Helvetica-Oblique", spaceAfter=2)
_CELL    = _style("AA_Cell",             fontSize=8,  fontName="Helvetica",         leading=10)
_CELLB   = _style("AA_CellB",           fontSize=8,  fontName="Helvetica-Bold",    leading=10)
# Code column: no intra-word splitting so "NO_GST_REG" always sits on one line
_CELL_CODE = _style("AA_CellCode",      fontSize=8,  fontName="Helvetica",         leading=10,
                     splitLongWords=0)
# Recommendation sub-line inside description cell
_CELL_REC  = _style("AA_CellRec",       fontSize=7,  fontName="Helvetica-Oblique", leading=9,
                     textColor=colors.HexColor("#5D6D7E"))

# ── Colour palette ────────────────────────────────────────────────────────────

_HEADER_BG = colors.HexColor("#2C3E50")   # dark blue-grey — table header background
_STRIPE    = colors.HexColor("#F0F3F4")   # very light grey — alternating row fill
_GRID_LINE = colors.HexColor("#BDC3C7")   # light grey — table cell borders
_FOOTER_FG = colors.HexColor("#7F8C8D")   # medium grey — footer text
# Severity badge colours: red/amber/green matching traffic-light convention
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
    """Parse a stored ISO 8601 string into a reader-friendly UTC display string.

    Args:
        iso: An ISO 8601 datetime string, e.g. '2024-03-31T10:45:00+08:00'.

    Returns:
        str: Formatted as '31 Mar 2024, 02:45 UTC'.  Returns the original string
            verbatim if parsing fails, so a malformed timestamp degrades gracefully
            rather than raising inside the renderer.
    """
    try:
        dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        return dt.strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return iso  # fallback: render verbatim if parse fails

# ── Table helpers ─────────────────────────────────────────────────────────────

def _base_table_style() -> TableStyle:
    """Return the standard zebra-stripe TableStyle used by all data tables.

    Applies a dark header row, alternating white/light-grey row backgrounds
    starting at row 1, a light grid, top-aligned cells, and uniform padding.
    ROWBACKGROUNDS cycles through the provided list — two colours produce
    alternating stripes automatically.

    Returns:
        TableStyle: A new instance (not a singleton) so callers that need to
            extend it can append commands without affecting other tables.
    """
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
    """Build a Table with a header row prepended and the standard base style.

    Args:
        col_widths: List of column widths in ReportLab units (e.g. cm values).
            Should sum to _UW so the table fills the usable page width.
        header:     List of Paragraph (or string) cells for the header row.
        rows:       List of data rows; each row is a list of cell values.

    Returns:
        Table: A ReportLab Table with repeatRows=1 so the header is reprinted
            at the top of each new page when the table spans a page break.
    """
    return Table(
        [header] + rows,
        colWidths=col_widths,
        style=_base_table_style(),
        # repeatRows=1 reprints the header row at the top of each continuation page
        repeatRows=1,
    )

# ── Cell formatters ───────────────────────────────────────────────────────────

def _p(text, style: ParagraphStyle = _CELL) -> Paragraph:
    """Wrap text in a Paragraph, substituting an em-dash for None values.

    The explicit None check (rather than `text or "—"`) is intentional: numeric
    zero should render as "0", not "—", but falsy-zero would collapse with a
    bare `or` short-circuit.

    Args:
        text:  Any value; converted via str() unless None.
        style: ParagraphStyle to apply (defaults to _CELL).

    Returns:
        Paragraph: Ready to embed in a Table cell or story list.
    """
    return Paragraph(str(text) if text is not None else "—", style)


def _sgd(value) -> str:
    """Format a numeric value as a comma-separated SGD string with 2 decimal places.

    Args:
        value: Numeric value, or None.

    Returns:
        str: e.g. '12,345.67', or '—' if value is None.
    """
    return f"{value:,.2f}" if value is not None else "—"


def _sev_cell(sev: str) -> Paragraph:
    """Render a severity badge as a bold, coloured Paragraph using ReportLab XML markup.

    Args:
        sev: Severity string — 'HIGH', 'MEDIUM', or 'LOW'.

    Returns:
        Paragraph: Text coloured per _SEV_HEX; falls back to black for unknown values.
    """
    hex_c = _SEV_HEX.get(sev, "#000000")
    return Paragraph(f'<font color="{hex_c}"><b>{sev}</b></font>', _CELL)


def _desc_cell(description: str | None, recommendation: str | None) -> list[Paragraph]:
    """Return one or two stacked Paragraphs for the description column.

    Recommendation is rendered on its own line in italic grey so it is
    visually distinct from the finding description. No separator glyphs used.

    Args:
        description:    Main finding description text, or None (renders as '—').
        recommendation: Optional corrective action text.  Omitted entirely when None
                        so the cell height is not wasted on a blank line.

    Returns:
        list[Paragraph]: One element (description only) or two (description + recommendation).
            ReportLab accepts a list of Flowables as a single cell value and stacks them.
    """
    result = [_p(description or "—")]
    if recommendation:
        result.append(Paragraph(f"Recommendation: {recommendation}", _CELL_REC))
    return result

# ── Numbered canvas (Page X of Y footer) ─────────────────────────────────────

def _make_numbered_canvas(client_name: str):
    """Return a Canvas subclass that draws a footer with page X of Y on every page.

    ReportLab's normal rendering model flushes each page immediately via showPage(),
    so the total page count is not known until all pages have been processed.
    This factory uses the standard two-pass workaround:
      Pass 1 — showPage() is overridden to buffer each page's canvas state
               (as a dict snapshot of self.__dict__) instead of flushing it.
      Pass 2 — save() replays all buffered states, now knowing the total count,
               stamping the footer before flushing each page via Canvas.showPage().

    Args:
        client_name: Client name string embedded in the right-side footer text.

    Returns:
        type: A Canvas subclass (_NumberedCanvas).  Pass as canvasmaker= to
            SimpleDocTemplate.build().
    """

    class _NumberedCanvas(Canvas):
        """Canvas subclass that buffers pages to support 'Page X of Y' footers."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict] = []

        def showPage(self):
            """Buffer the current page state instead of flushing, then start a new page.

            Called by the Platypus layout engine at each page boundary.  Overriding
            it prevents immediate flushing so that save() can replay all pages once
            the total count is known.
            """
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            """Replay all buffered pages with footers, then flush the PDF to disk.

            Two-pass process: all page states were buffered in showPage(); now that
            the total is known, each state is restored and the footer is drawn before
            the page is flushed via Canvas.showPage() (the real implementation, not
            the overridden one).
            """
            # Shallow copy taken before the restore loop mutates self.__dict__
            states = self._saved_page_states[:]
            total = len(states)
            for page_num, state in enumerate(states, 1):
                self.__dict__.update(state)
                self._draw_footer(page_num, total)
                # Call Canvas.showPage directly (not super()) to bypass the
                # override above and actually flush this page to the PDF stream.
                Canvas.showPage(self)
            Canvas.save(self)

        def _draw_footer(self, page_num: int, total: int) -> None:
            """Draw the two-part footer bar at the bottom of the current page.

            Left side: working-paper caveat.
            Right side: client name, report title, and page numbering.

            Args:
                page_num: 1-based current page number.
                total:    Total number of pages in the document.
            """
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

# ── Declared-vs-computed F5 text renderer (public) ───────────────────────────

def render_declared_f5_section(section) -> str:
    """Render declared_f5_findings to a plain-text summary for validation and logging.

    Accepts any object with a .findings attribute (duck-typed so tests can pass a
    DeclaredF5Section directly without an explicit import dependency here).

    Returns an empty string when section.findings is empty, so callers can test
    for truthiness before printing.

    Args:
        section: DeclaredF5Section (or duck-typed equivalent); must expose
                 .findings as a list of finding dicts.

    Returns:
        str: Multi-line text table of all findings; empty string if no findings.
    """
    findings = getattr(section, "findings", None) or []
    if not findings:
        return ""

    lines: list[str] = [
        "Declared-vs-Computed F5 Comparison",
        "=" * 50,
    ]
    for f in findings:
        check = f.get("check", "?")
        ftype = f.get("finding_type", "?")
        box = f.get("box", "?")
        delta = f.get("delta")
        delta_str = f"{delta:+.6g}" if isinstance(delta, (int, float)) else str(delta)
        lines.append(f"  [{check}] {ftype}  box={box}  delta={delta_str}")
        desc = f.get("description") or f.get("note") or f.get("hypothesis", "")
        if desc:
            lines.append(f"       {desc}")
    return "\n".join(lines)


# ── Section renderers ─────────────────────────────────────────────────────────

def _cover(m: ReportModel, story: list) -> None:
    """Append the cover page flowables to the story.

    Renders: report title, subtitle, a horizontal rule, and a metadata block
    (client, GST reg number, period, reviewer, generated timestamp), followed
    by a PageBreak.

    Args:
        m:     The ReportModel containing cover data.
        story: Mutable story list; flowables are appended in place.
    """
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
        story.append(Paragraph(f"<b>{label}:</b>  {value}", _BODY))
    story.append(PageBreak())


def _scope(m: ReportModel, story: list) -> None:
    """Append Section 1 — Scope (items examined, FX exclusions, credit notes).

    Three sub-sections:
      * Items examined table: document-type counts, sorted alphabetically for
        stable display regardless of dict insertion order.
      * Foreign currency invoices excluded from box totals.
      * Credit notes applied (with signed line/tax totals).

    Args:
        m:     The ReportModel containing scope data.
        story: Mutable story list; flowables are appended in place.
    """
    story.append(Paragraph("1.  Scope — Items Examined", _H2))

    hdr = [_p("Document type", _CELLB), _p("Count", _CELLB)]
    # Alphabetical sort gives stable display order regardless of dict insertion order
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
    """Append Section 2 — GST F5 Return box figures.

    One row per F5 box showing the computed SGD value and the VatGroup codes
    that contributed to it.  Box labels are looked up from _BOX_LABELS so the
    display text matches the IRAS F5 form labels exactly.

    Args:
        m:     The ReportModel containing F5 box attribution data.
        story: Mutable story list; flowables are appended in place.
    """
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
            # Comma-joined VatGroup codes show the reviewer which codes fed each box
            _p(", ".join(a.vat_groups) if a.vat_groups else "—"),
        ]
        for a in m.f5_boxes.attribution
    ]
    story.append(_table([7.5*cm, 3.5*cm, 6.0*cm], hdr, rows))


def _findings(m: ReportModel, story: list) -> None:
    """Append Section 3 — Findings grouped by ASK template.

    Each template group is wrapped in KeepTogether so its heading is never
    orphaned at the bottom of a page without at least the start of its table.

    Amount column fallback order (most to least precise):
      1. line_total  — sum of classify line totals (most precise; covers E1–E4)
      2. doc_total   — full document total from the manifest (approximate;
                       used for NO_GST_REG where no per-line classify data exists)
      3. "—"         — neither is available

    Args:
        m:     The ReportModel containing grouped findings.
        story: Mutable story list; flowables are appended in place.
    """
    story.append(Paragraph("3.  Findings by IRAS ASK Template", _H2))
    story.append(Paragraph(
        f"Total: {m.findings.total_findings} finding(s). "
        "Sorted HIGH &gt; MEDIUM &gt; LOW, then by document number within each severity.",
        _SMLX,
    ))

    # Column widths: Code column is 2.0 cm — wide enough for NO_GST_REG at 8 pt Helvetica.
    # Widths sum to 17.0 cm = _UW.
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
    """Append Section 4 — Cross-finding analysis (documents with multiple error codes).

    Lists only documents that carry two or more distinct error codes — these
    are the highest-priority items for manual review because they indicate
    compound problems.

    Args:
        m:     The ReportModel containing cross-finding data.
        story: Mutable story list; flowables are appended in place.
    """
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
            # dict.fromkeys preserves insertion order and silently deduplicates;
            # multiple findings can share the same Appendix 1 category string.
            _p("; ".join(dict.fromkeys(f.appendix1_category for f in e.findings))),
        ]
        for e in m.cross_findings.multi_error_docs
    ]
    story.append(_table(cols, hdr, rows))


# AI subsection styles — visually distinct (blue palette) from the deterministic
# grey/dark-blue palette above, signalling these are unvalidated candidates.
_AI_SUBHEADING_BG = colors.HexColor("#EAF4FB")   # light blue — visually distinct from deterministic
_AI_DISCLAIMER_FG = colors.HexColor("#1A5276")   # dark blue for disclaimer text

_H3_AI = _style(
    "AA_H3_AI", "Heading3",
    fontSize=9, fontName="Helvetica-Bold",
    spaceAfter=3, spaceBefore=8,
    textColor=_AI_DISCLAIMER_FG,
)
_CELL_AI = _style("AA_CellAI", fontSize=8, fontName="Helvetica", leading=10,
                   textColor=colors.HexColor("#1B2631"))
_SMLX_AI = _style("AA_SmXAI", fontSize=7, fontName="Helvetica-Oblique", spaceAfter=2,
                   textColor=_AI_DISCLAIMER_FG)

_AI_GRID  = colors.HexColor("#AED6F1")   # light blue border for AI tables
_AI_STRIPE = colors.HexColor("#EBF5FB")  # light blue alternating stripe for AI tables


def _ai_table_style() -> TableStyle:
    """Return a TableStyle for AI-candidate tables.

    Extends the standard base structure (_base_table_style layout constants) with
    the AI blue colour palette — light-blue header background, dark-blue header text,
    blue grid lines, and blue row stripes — so both AI subsections share one definition.
    """
    ts = _base_table_style()
    ts.add("BACKGROUND",    (0, 0), (-1, 0),  _AI_SUBHEADING_BG)
    ts.add("TEXTCOLOR",     (0, 0), (-1, 0),  _AI_DISCLAIMER_FG)
    ts.add("GRID",          (0, 0), (-1, -1), 0.25, _AI_GRID)
    ts.add("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, _AI_STRIPE])
    return ts


def _ai_candidates_subsection(m: ReportModel, story: list) -> None:
    """Render the optional AI-surfaced candidates subsection within Section 5.

    Rendered only when model.ai_candidates.show is True.
    Candidates are NEVER counted in deterministic finding totals.

    Args:
        m:     The ReportModel; ai_candidates may be None if the AI pass was
               not configured for this run.
        story: Mutable story list; flowables are appended in place.
    """
    ai = m.ai_candidates
    if ai is None or not ai.show:
        return

    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width=_UW, thickness=0.5,
                             color=_AI_GRID))
    story.append(Paragraph(
        "AI-surfaced candidates (unvalidated) — Reg 26/27 disallowed input tax",
        _H3_AI,
    ))

    if ai.status == "errored":
        story.append(Paragraph("AI candidate pass did not complete.", _BODY))
        return

    if ai.status == "ok" and ai.candidate_count == 0:
        story.append(Paragraph("No AI-surfaced candidates.", _BODY))
    else:
        # Render candidates table — visually distinct from deterministic findings.
        ai_cols = [1.8*cm, 1.8*cm, 2.0*cm, 2.8*cm, 2.8*cm, 2.0*cm, 4.0*cm]
        ai_hdr = [_p(h, _CELLB) for h in
                  ["Doc #", "Line", "Date", "Counterparty", "Category", "Confidence",
                   "Reviewer prompt"]]
        ai_rows = [
            [
                _p(str(c.doc_num), _CELL_AI),
                _p(str(c.line_index), _CELL_AI),
                _p(c.doc_date, _CELL_AI),
                _p(c.card_name, _CELL_AI),
                _p(c.suspected_category.replace("_", " "), _CELL_AI),
                _p(c.confidence, _CELL_AI),
                _p(c.phrasing, _CELL_AI),
            ]
            for c in ai.candidates
        ]
        tbl = Table(
            [ai_hdr] + ai_rows,
            colWidths=ai_cols,
            style=_ai_table_style(),
            repeatRows=1,
        )
        story.append(tbl)

    # Disclaimer — always shown when the subsection is visible.
    if ai.disclaimer:
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(ai.disclaimer, _SMLX_AI))


def _unified_candidates_subsection(m: ReportModel, story: list) -> None:
    """Render the unified AI-Surfaced Candidates subsection within Section 5.

    Uses model.unified_candidates when present (Prompt 4+).  Falls back to the
    legacy _ai_candidates_subsection for ReportModel instances constructed before
    unified_candidates was added (e.g. manually built in tests).

    Gated by unified_candidates.show — when False the function returns immediately,
    leaving the rest of the report byte-identical to a pre-Prompt-4 run.

    Args:
        m:     The ReportModel; unified_candidates may be None for legacy callers.
        story: Mutable story list; flowables are appended in place.
    """
    uc = m.unified_candidates
    if uc is None:
        _ai_candidates_subsection(m, story)
        return
    if not uc.show:
        return

    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width=_UW, thickness=0.5,
                             color=_AI_GRID))
    story.append(Paragraph(
        "AI-Surfaced Candidates for Review (unvalidated)",
        _H3_AI,
    ))

    # ── Status notes for passes that did not run ──────────────────────────────
    if uc.reasoning_status == "not_examined":
        story.append(Paragraph(
            "Reasoning analysis (Reg 26/27 description-based): not examined.",
            _SMLX_AI,
        ))
    elif uc.reasoning_status not in ("ok",):
        story.append(Paragraph(
            f"Reasoning analysis (Reg 26/27 description-based): "
            f"did not complete ({uc.reasoning_status}).",
            _SMLX_AI,
        ))

    if uc.documents_status == "not_examined":
        story.append(Paragraph(
            "Source document cross-reference: not examined.",
            _SMLX_AI,
        ))

    # ── Candidates table or "none surfaced" notice ────────────────────────────
    if not uc.candidates:
        if uc.reasoning_status == "ok" or uc.documents_status == "ok":
            story.append(Paragraph("No candidates surfaced.", _BODY))
    else:
        # Columns: Doc # | Basis | Finding | Determinability | Reviewer prompt
        uc_cols = [1.8*cm, 3.5*cm, 2.5*cm, 2.5*cm, 6.7*cm]
        uc_hdr = [_p(h, _CELLB) for h in
                  ["Doc #", "Basis", "Finding", "Determinability",
                   "Reviewer prompt"]]
        uc_rows = [
            [
                _p(str(r.doc_num), _CELL_AI),
                _p(r.basis, _CELL_AI),
                _p(r.finding.replace("_", " "), _CELL_AI),
                _p(r.determinability, _CELL_AI),
                _p(r.message, _CELL_AI),
            ]
            for r in uc.candidates
        ]
        tbl = Table(
            [uc_hdr] + uc_rows,
            colWidths=uc_cols,
            style=_ai_table_style(),
            repeatRows=1,
        )
        story.append(tbl)

    if uc.disclaimer:
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(uc.disclaimer, _SMLX_AI))


def _judgment(m: ReportModel, story: list) -> None:
    """Append Section 5 — Judgment items requiring reviewer decision.

    Renders one sub-section per judgment group, each with a display title,
    judgment question, and the list of document numbers to review.  The
    unified candidates subsection is appended at the end when show=True.

    Args:
        m:     The ReportModel containing judgment groups and unified_candidates.
        story: Mutable story list; flowables are appended in place.
    """
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
    _unified_candidates_subsection(m, story)


def _declared_f5(m: ReportModel, story: list) -> None:
    """Append the Declared-vs-Computed F5 section when findings are present.

    No-op when model.declared_f5 is None or has no findings, so the rest of
    the report is byte-identical to a run without --declared-f5.

    Check A findings (internal consistency violations) and Check B findings
    (declared-vs-computed divergence) are rendered in separate sub-tables so
    the reviewer can distinguish rule violations from materiality divergences.

    Args:
        m:     The ReportModel; declared_f5 may be None for legacy callers.
        story: Mutable story list; flowables are appended in place.
    """
    df5 = getattr(m, "declared_f5", None)
    if df5 is None or not df5.findings:
        return

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Declared-vs-Computed F5 Comparison", _H2))
    story.append(Paragraph(
        "Divergences detected between the client's filed F5 figures and the "
        "SAP-computed values.  These are observations for reviewer attention — "
        "the audit chain seals normally regardless of findings.",
        _SMLX,
    ))
    story.append(Spacer(1, 0.2 * cm))

    check_a = [f for f in df5.findings if f.get("check") == "A"]
    check_b = [f for f in df5.findings if f.get("check") == "B"]

    if check_a:
        story.append(Paragraph("Check A — Declared Internal Consistency", _H3))
        story.append(Paragraph(
            "The client's own filed figures violate an F5 accounting identity.",
            _SMLX,
        ))
        a_cols = [4.0*cm, 2.0*cm, 10.0*cm, 1.0*cm]
        a_hdr = [_p(h, _CELLB) for h in ["Rule", "Box", "Description", "Delta"]]
        a_rows = [
            [
                _p(f.get("rule", ""), _CELL),
                _p(f.get("box", ""), _CELL),
                _p(f.get("description", ""), _CELL),
                _p(
                    f"{f['delta']:+.2f}" if isinstance(f.get("delta"), (int, float)) else "?",
                    _CELL,
                ),
            ]
            for f in check_a
        ]
        story.append(_table(a_cols, a_hdr, a_rows))
        story.append(Spacer(1, 0.2 * cm))

    if check_b:
        story.append(Paragraph("Check B — Declared-vs-Computed Divergence", _H3))
        story.append(Paragraph(
            "Tolerance: SGD 1.00 per independent box "
            "(IRAS ASK Annual Review Guide s10.1(d)(iii) fn33).  "
            "Derived boxes (Box 4, Box 8) shown as consequence notes only.",
            _SMLX,
        ))
        b_cols = [3.0*cm, 2.5*cm, 2.5*cm, 2.0*cm, 3.0*cm, 4.0*cm]
        b_hdr = [_p(h, _CELLB) for h in
                 ["Box", "Declared", "Computed", "Delta", "Direction", "Observation"]]
        b_rows = [
            [
                _p(f.get("box", ""), _CELL),
                _p(
                    _sgd(f["declared"]) if isinstance(f.get("declared"), (int, float)) else "—",
                    _CELL,
                ),
                _p(
                    _sgd(f["computed"]) if isinstance(f.get("computed"), (int, float)) else "—",
                    _CELL,
                ),
                _p(
                    f"{f['delta']:+.2f}" if isinstance(f.get("delta"), (int, float)) else "?",
                    _CELL,
                ),
                _p(f.get("direction", ""), _CELL),
                # Primary findings have hypothesis; derived findings have note.
                _p(f.get("hypothesis") or f.get("note", ""), _CELL),
            ]
            for f in check_b
        ]
        story.append(_table(b_cols, b_hdr, b_rows))


def _listing_findings(m: ReportModel, story: list) -> None:
    """Render T2.10 listing-level check findings (SEQ_GAP + DUP_CLAIM) when present.

    Skipped entirely when model.listing_findings is None (legacy callers) or when
    both finding lists are empty.  Renders a separate subsection for each check
    type that has at least one finding.

    Args:
        m:     The ReportModel containing listing_findings.
        story: Mutable story list; flowables are appended in place.
    """
    lf = m.listing_findings
    if lf is None:
        return
    if not lf.seq_gap_findings and not lf.dup_claim_findings:
        return

    story.append(Paragraph("Invoice Listing Completeness Checks", _H2))
    story.append(Paragraph(
        "Invoice-listing completeness checks (IRAS ASK Annual Review Guide §10.1). "
        "Findings are candidates for reviewer attention; they do not affect F5 box "
        "totals or gate outcomes.",
        _SMLX,
    ))

    if lf.seq_gap_findings:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Sequence Gap Detection (SEQ_GAP)", _H3))
        story.append(Paragraph(
            f"{len(lf.seq_gap_findings)} gap candidate(s). "
            "Each DocNum is absent from all company records and falls within the "
            "reviewed-period active range — §10.1(c)(i).",
            _SMALL,
        ))
        sg_cols = [1.4*cm, 2.2*cm, 2.8*cm, 10.6*cm]
        sg_hdr = [_p(h, _CELLB) for h in ["Series", "Gap DocNum", "Active Range", "Description"]]
        sg_rows = [
            [
                _p(str(f.get("series", "—"))),
                _p(str(f.get("gap_doc_num", "—"))),
                _p(f"{f.get('series_min', '—')}–{f.get('series_max', '—')}"),
                _p(f.get("description", "—")),
            ]
            for f in lf.seq_gap_findings
        ]
        story.append(_table(sg_cols, sg_hdr, sg_rows))

    if lf.dup_claim_findings:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Duplicate Input-Tax Claims (DUP_CLAIM)", _H3))
        story.append(Paragraph(
            f"{len(lf.dup_claim_findings)} duplicate candidate(s). "
            "Each purchase invoice shares the same vendor, vendor reference, and total "
            "as another — §10.1(d)(i).",
            _SMALL,
        ))
        dc_cols = [1.8*cm, 2.0*cm, 2.2*cm, 3.0*cm, 2.5*cm, 5.5*cm]
        dc_hdr = [_p(h, _CELLB) for h in
                  ["DocNum", "Duplicate Of", "Vendor", "Vendor Ref", "Total (SGD)", "Description"]]
        dc_rows = [
            [
                _p(str(f.get("doc_num", "—"))),
                _p(str(f.get("duplicate_of", "—"))),
                _p(f.get("card_code", "—")),
                _p(f.get("num_at_card", "—")),
                _p(_sgd(f.get("doc_total"))),
                _p(f.get("description", "—")),
            ]
            for f in lf.dup_claim_findings
        ]
        story.append(_table(dc_cols, dc_hdr, dc_rows))


def _not_examined(m: ReportModel, story: list) -> None:
    """Append Section 6 — Items not examined (coverage boundary).

    Each item is a bulleted paragraph drawn from model.not_examined.items,
    which in turn comes from constants.NOT_EXAMINED_ITEMS via the report builder.

    Args:
        m:     The ReportModel containing the not-examined item list.
        story: Mutable story list; flowables are appended in place.
    """
    story.append(Paragraph("6.  Items Not Examined", _H2))
    story.append(Paragraph(
        "The following checks are outside the scope of this automated review. "
        "The reviewer of record should determine whether any require additional action.",
        _BODY,
    ))
    for item in m.not_examined.items:
        story.append(Paragraph(f"•  {item}", _SMALL))


def _signature(m: ReportModel, story: list) -> None:
    """Append the declaration and sign-off page.

    Starts on a new page.  Renders reviewer metadata, a ruled signature line
    (width matches the IRAS Declaration Form convention), a date field, and
    the disclaimer text.

    Args:
        m:     The ReportModel containing signature and disclaimer data.
        story: Mutable story list; flowables are appended in place.
    """
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
        story.append(Paragraph(f"<b>{label}:</b>  {value}", _BODY))

    story.append(Spacer(1, 1.5 * cm))
    # Ruled signature line — mirrors the IRAS Declaration Form on Completing Annual Review
    # Width at 55% of usable width matches the physical form's signature line proportion.
    story.append(HRFlowable(width=_UW * 0.55, thickness=0.75, color=colors.black))
    story.append(Paragraph(
        "Signature" + " " * 16 + "Date: _______________",
        _SMALL,
    ))
    story.append(Spacer(1, 1.2 * cm))
    story.append(HRFlowable(width=_UW, thickness=0.25, color=_GRID_LINE))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(m.signature.disclaimer, _SMLX))


# ── Public entry point ────────────────────────────────────────────────────────

def render_pdf(model: ReportModel, out_path: str | Path) -> Path:
    """Render a ReportModel to a PDF file and return the output Path.

    Assembles eight section renderers into a Platypus story list, then builds
    the PDF using SimpleDocTemplate with _NumberedCanvas for page-X-of-Y footers.
    No datetime.now() is called anywhere in this module — the generated_at
    timestamp comes from model.cover.generated_at.

    Args:
        model:    A fully populated ReportModel.  All section data must be set;
                  no defaults are applied here.
        out_path: Destination file path (str or Path).  The parent directory is
                  created if it does not exist.

    Returns:
        Path: The absolute path to the written PDF file.

    Raises:
        OSError: If the output directory cannot be created or the file cannot
            be written (e.g. insufficient permissions).
        Exception: ReportLab may raise if any Flowable cannot be laid out
            (e.g. a single cell value wider than its column).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        # Extra 0.4 cm below the standard margin so content never overlaps the footer text
        bottomMargin=_MARGIN + 0.4 * cm,
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
    _declared_f5(model, story)
    _findings(model, story)
    _listing_findings(model, story)
    _cross_findings(model, story)
    _judgment(model, story)
    _not_examined(model, story)
    _signature(model, story)

    NC = _make_numbered_canvas(model.cover.client_name)
    # canvasmaker= injects the numbered canvas subclass so every page receives
    # the two-pass footer stamp instead of the default bare Canvas.
    doc.build(story, canvasmaker=NC)
    return out_path
