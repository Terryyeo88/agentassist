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
from decimal import Decimal
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
# Severity badge colours: red/amber/green matching traffic-light convention.
# Retained for backward-compat (_sev_cell); severity is no longer rendered in the
# findings table (report redesign, Change 4) but the palette/helper stay defined.
_SEV_HEX   = {"HIGH": "#C0392B", "MEDIUM": "#E67E22", "LOW": "#27AE60"}
# F5 four-number summary highlight (Change 2) — light blue-grey, distinct from
# the deterministic table stripe.
_SUMMARY_BG = colors.HexColor("#EAF2F8")

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


def _table(col_widths: list, header: list, rows: list, extra_style: list | None = None) -> Table:
    """Build a Table with a header row prepended and the standard base style.

    Args:
        col_widths: List of column widths in ReportLab units (e.g. cm values).
            Should sum to _UW so the table fills the usable page width.
        header:     List of Paragraph (or string) cells for the header row.
        rows:       List of data rows; each row is a list of cell values.
        extra_style: Optional additional TableStyle commands appended to the base
            style (e.g. per-row SPANs); None (the default) is byte-identical to
            before the parameter existed.

    Returns:
        Table: A ReportLab Table with repeatRows=1 so the header is reprinted
            at the top of each new page when the table spans a page break.
    """
    style = _base_table_style()
    for command in (extra_style or []):
        style.add(*command)
    return Table(
        [header] + rows,
        colWidths=col_widths,
        style=style,
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


# ── Report-redesign presentation helpers (Avinash feedback) ───────────────────
# All four helpers below are PURE and read-only. They shape how existing model
# data is DISPLAYED; none recomputes an F5 box value, changes enrich keying, or
# touches the show_ai_candidates gate. See CLAUDE.md Invariants 2-4.

def _category_code_label(appendix1_category: str | None, error_code: str) -> str:
    """Human-first finding label: IRAS Appendix-1 wording, raw code as a tag.

    Change 1 (codes -> labels). The finding's ``appendix1_category`` (already
    computed in report.enrich from IRAS ASK Appendix 1) is the primary label; the
    internal ``error_code`` is kept as a small parenthetical for auditor
    traceability — e.g. "Wrong classification of supplies made (E1)".

    Args:
        appendix1_category: IRAS ASK wording for the finding; "—" when absent.
        error_code:         Internal routing code (E1, E2, NO_GST_REG, …).

    Returns:
        str: "<wording> (<code>)".
    """
    wording = appendix1_category or "—"
    return f"{wording} ({error_code})"


# F5 four-number summary: (box key, display label). Order is the F5 reading a
# reviewer scans first — supplies, purchases, output tax, input tax.
_F5_SUMMARY_LABELS: list[tuple[str, str]] = [
    ("box_1_standard_rated_sales", "Standard-rated supplies (Box 1)"),
    ("box_5_taxable_purchases",    "Taxable purchases (Box 5)"),
    ("box_6_output_tax",           "Output tax due (Box 6)"),
    ("box_7_input_tax",            "Input tax claimed (Box 7)"),
]


def _f5_summary_pairs(boxes: dict) -> list[tuple[str, float]]:
    """Return the four headline F5 figures read VERBATIM from ``boxes``.

    Change 2 (four-number summary). No arithmetic, no rounding, no recompute —
    each value is ``boxes[key]`` exactly as the deterministic calculate step
    produced it (BOX-ISOLATION / Invariant 3+4). Read-only: never mutates boxes.

    Args:
        boxes: ``compile_output["calculate"]["boxes"]`` (or model.f5_boxes.boxes).

    Returns:
        list[tuple[str, float]]: Four (label, value) pairs in F5 reading order.
    """
    return [(label, boxes[key]) for key, label in _F5_SUMMARY_LABELS]


# ── Box-capability rendering (D-2026-07-26-box-capability, open item #48) ─────

# Marker for a box the SOURCE could not have populated (status "unavailable").
# A capability fact, not a figure: the sealed compile-output keeps the raw
# computed value; the paper GLOSSES it (the additive shape from
# D-2026-07-24-decision-render) — it never states a statutory figure the source
# could not support, and never claims a bound or a direction.
_UNAVAILABLE_MARKER = "Not available from this source"


def _box_value_flowables(a) -> list:
    """SGD-value cell content for one F5 box row, by capability status.

    "available" → the figure (or an em-dash when the boxes dict carried no key —
    an absent key must never be fabricated as 0.00, R7); "unavailable" → the
    marker, no figure; "derived_incomplete" → the figure PLUS a sub-line naming
    the unavailable input term(s), claiming no bound or direction (R4). Pure
    presentation over already-final values — no arithmetic, no recompute
    (BOX-ISOLATION).
    """
    if a.status == "unavailable":
        return [_p(_UNAVAILABLE_MARKER, _CELL_REC)]
    if a.box_value is None:
        return [_p(None)]  # _p renders None as an em-dash — never a fabricated 0.00
    if a.status == "derived_incomplete":
        named = "; ".join(
            _BOX_LABELS.get(key, key) for key in a.unavailable_inputs
        )
        return [
            _p(_sgd(a.box_value)),
            _p(
                f"Derived from an incomplete input: {named} is not available "
                "from this source.",
                _CELL_REC,
            ),
        ]
    return [_p(_sgd(a.box_value))]


def _display_amount(f) -> float:
    """Dollar impact used to order findings for DISPLAY (largest first).

    Change 4 (severity removed -> sort by amount). Prefers per-line ``line_total``;
    falls back to the manifest ``doc_total`` (e.g. NO_GST_REG has no per-line
    classify data); ``-inf`` when neither exists so unknown-amount rows sort last.
    Presentation only — the model-level severity sort in
    report.sections.build_findings_section is unchanged.
    """
    if f.line_total is not None:
        return f.line_total
    if f.doc_total is not None:
        return f.doc_total
    return float("-inf")


def _findings_display_order(findings: list) -> list:
    """Return findings sorted by dollar impact descending (render-only re-sort)."""
    return sorted(findings, key=_display_amount, reverse=True)


def _group_nogstreg_by_supplier(findings: list) -> list[tuple[str, list]]:
    """Group NO_GST_REG findings by supplier (card_name) for DISPLAY only.

    Change 3 (supplier grouping). Every per-document finding is preserved — this
    only buckets existing findings under one subheading per supplier; it never
    collapses or dedupes findings and never touches enrich keying or
    ``total_findings``. Suppliers are ordered by total exposure descending, and
    each supplier's documents by amount descending, so the largest sit first.

    Args:
        findings: NO_GST_REG EnrichedFindings (already filtered by the caller).

    Returns:
        list[tuple[str, list]]: (supplier, [findings]) preserving every row.
    """
    buckets: dict[str, list] = {}
    for f in findings:
        buckets.setdefault(f.card_name or "—", []).append(f)
    ordered: list[tuple[str, list]] = []
    for supplier, fs in buckets.items():
        ordered.append((supplier, _findings_display_order(fs)))
    # Largest-exposure supplier first (sum of display amounts).
    ordered.sort(key=lambda kv: sum(_display_amount(f) for f in kv[1]), reverse=True)
    return ordered

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

# ── Deterministic-check coverage helpers + text renderer (T2.12-2C) ──────────

# Friendly labels for the deterministic checks 2B's coverage seam reports on.
# Self-contained here so report/ takes NO new coupling to agent.registry (and
# stays feeders-pure); the raw check id is the fallback for any unmapped check.
_COVERAGE_CHECK_LABELS: dict[str, str] = {
    "DUP_CLAIM": "Duplicate input-tax claims (DUP_CLAIM)",
    "SEQ_GAP": "Invoice sequence gaps (SEQ_GAP)",
    "NO_GST_REG": "Supplier GST-registration check (NO_GST_REG)",
}


def _coverage_label(check: str) -> str:
    """Friendly label for a coverage check; raw id fallback keeps it honest."""
    return _COVERAGE_CHECK_LABELS.get(check, check or "(unknown check)")


def _coverage_line(row: dict) -> str:
    """One reviewer-facing coverage line, reusing tfix #63's three-state vocabulary.

    full        → positively marked "examined" (visible, not invisible) — no reason.
    degraded    → "examined" with the under-detection caveat surfaced.
    unavailable → "NOT examined" with the could-not-run caveat surfaced.

    The reason carries the data-coverage FACT only (no IRAS rationale); it is empty
    for full and non-empty for degraded/unavailable (2B's discipline).
    """
    label = _coverage_label(row.get("check", ""))
    level = row.get("level", "")
    reason = row.get("reason", "")
    if level == "full":
        return f"{label}: examined — full data coverage."
    if level == "degraded":
        return f"{label}: examined with reduced coverage (degraded) — {reason}"
    if level == "unavailable":
        return f"{label}: NOT examined — coverage unavailable — {reason}"
    # Defensive fallback for an unrecognised level — surface it rather than hide it.
    tail = f" — {reason}" if reason else ""
    return f"{label}: {level or '(unknown level)'}{tail}"


def render_check_coverage_section(section) -> str:
    """Render the deterministic-check coverage status to plain text (T2.12-2C).

    Mirrors ``render_declared_f5_section``: duck-typed (any object with a ``.rows``
    list of ``{check, level, reason}`` dicts), returns an EMPTY string when there are
    no rows so callers can test truthiness. This is the testable surface; the PDF
    flowable appender ``_check_coverage`` renders the same lines into the report.

    Args:
        section: CheckCoverageSection (or duck-typed equivalent) exposing ``.rows``.

    Returns:
        str: a heading + one line per check; empty string when there are no rows.
    """
    rows = getattr(section, "rows", None) or []
    if not rows:
        return ""
    lines: list[str] = [
        "Deterministic Check Coverage",
        "=" * 50,
    ]
    lines.extend(f"  {_coverage_line(row)}" for row in rows)
    return "\n".join(lines)


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


# ── Ledger-recon text renderer (public, T2.24 PR-3) ──────────────────────────

def render_ledger_recon_section(section) -> str:
    """Render the T2.24 GST control-ledger reconciliation to plain text.

    Empty-string-when-empty (mirrors render_declared_f5_section): a clean run (examined,
    no findings) and a never-run (not_examined) render NOTHING — no fabricated all-clear.
    Non-empty only when a divergence/drop candidate exists OR a sub-signal is
    ``unavailable`` (an honest could-not-run caveat). The finding descriptions already
    carry candidate framing; this renders them verbatim and asserts nothing. Duck-typed.
    """
    if section is None:
        return ""
    recon_status = getattr(section, "recon_status", "not_examined")
    recon_findings = getattr(section, "recon_findings", None) or []
    drop_status = getattr(section, "drop_status", "not_examined")
    drop_findings = getattr(section, "drop_findings", None) or []

    body: list[str] = []
    # Signal A — ledger-derived GST vs the declared return boxes.
    if recon_status == "unavailable":
        body.append(
            "  Ledger-vs-declared-return reconciliation not performed "
            f"({getattr(section, 'recon_reason', '')})."
        )
    else:
        for f in recon_findings:
            body.append(f"  [{f.get('side', '—')}] {f.get('description', '')}")
    # Signal B — GST postings dropped from the F5 report ("Transactions not included").
    if drop_status == "unavailable":
        body.append(
            "  Not-included GST-posting review not performed "
            f"({getattr(section, 'drop_reason', '')})."
        )
    else:
        for f in drop_findings:
            body.append(
                f"  [{f.get('account', '—')} {f.get('reference', '')}] "
                f"{f.get('description', '')}"
            )

    if not body:
        return ""
    return "\n".join(["GST Control-Ledger Reconciliation", "=" * 50, *body])


# ── Analytical review text renderer (public) ─────────────────────────────────

def render_analytical_review_section(section) -> str:
    """Render an AnalyticalReviewSection to a plain-text summary for validation.

    Duck-typed: accepts any object with .ratio, .findings, and .fluctuation_findings.
    Returns a multi-line string covering the TP/TS ratio and the QoQ fluctuation
    subsections.  Always returns a non-empty string when section.show is True.

    Args:
        section: AnalyticalReviewSection (or duck-typed equivalent).

    Returns:
        str: Plain-text summary of both analytical-review subsections.
    """
    lines: list[str] = [
        "Annual Analytical Review",
        "=" * 50,
        f"FY: {getattr(section, 'fy_start', '')} → {getattr(section, 'fy_end', '')}",
        f"TP/TS ratio: {getattr(section, 'ratio', None) or '—'}",
    ]
    tpts = getattr(section, "findings", None) or []
    if tpts:
        lines.append("TP/TS Ratio — Candidate for Review:")
        for f in tpts:
            lines.append(f"  {f.get('description', '')}")
    else:
        lines.append("TP/TS ratio: within threshold — no finding.")

    lines.append("")
    lines.append("QoQ Fluctuation Candidates — ASK Step 1.3a:")
    fluct = getattr(section, "fluctuation_findings", None) or []
    if fluct:
        for f in fluct:
            lines.append(f"  {f.description}")
    else:
        lines.append("  No material quarter-over-quarter fluctuations detected at the ±50% threshold.")

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
        f"SGD. Computed from {m.source_label} invoice and credit note lines "
        "by calculate_f5_return.",
        _SMLX,
    ))

    # Change 2 (Avinash): foreground the four headline figures a reviewer scans
    # first, read verbatim from the computed boxes (no arithmetic — BOX-ISOLATION).
    # D-2026-07-26-box-capability: rows are built from the attribution (which
    # carries each box's capability status) so a structurally-unknowable box shows
    # the marker instead of a fabricated figure; the all-available path renders the
    # same figures _f5_summary_pairs reads verbatim.
    att_by_name = {a.box_name: a for a in m.f5_boxes.attribution}
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph("Key figures", _H3))
    summary_rows = []
    for key, label in _F5_SUMMARY_LABELS:
        a = att_by_name.get(key)
        if a is not None and a.status == "unavailable":
            value_cell = _p(_UNAVAILABLE_MARKER, _CELL_REC)
        elif a is not None and a.box_value is None:
            value_cell = _p(None)  # absent key → em-dash, never a fabricated 0.00 (R7)
        else:
            value_cell = _p(_sgd(m.f5_boxes.boxes[key]))
        summary_rows.append([_p(label, _CELLB), value_cell])
    summary_style = _base_table_style()
    summary_style.add("BACKGROUND", (0, 0), (-1, -1), _SUMMARY_BG)
    summary_style.add("BOX", (0, 0), (-1, -1), 0.75, _HEADER_BG)
    summary_tbl = Table(summary_rows, colWidths=[10.0 * cm, 7.0 * cm], style=summary_style)
    story.append(summary_tbl)

    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("Full box breakdown", _H3))
    hdr = [_p(h, _CELLB) for h in ["Box", "SGD Value", "VatGroups in period"]]
    rows = []
    span_commands: list = []
    for row_idx, a in enumerate(m.f5_boxes.attribution, start=1):
        value_flowables = _box_value_flowables(a)
        if a.status in ("unavailable", "derived_incomplete"):
            # Marker / sub-line text spans the value + VatGroups columns so it
            # renders on one visual line (an unavailable box has no VatGroup
            # transactions to show anyway; a derived box shows none by design).
            rows.append([_p(_BOX_LABELS.get(a.box_name, a.box_name)), value_flowables, ""])
            span_commands.append(("SPAN", (1, row_idx), (2, row_idx)))
        else:
            rows.append([
                _p(_BOX_LABELS.get(a.box_name, a.box_name)),
                value_flowables,
                # Comma-joined VatGroup codes show the reviewer which codes fed each box
                _p(", ".join(a.vat_groups) if a.vat_groups else "—"),
            ])
    story.append(_table([7.5*cm, 3.5*cm, 6.0*cm], hdr, rows, extra_style=span_commands))


# Section 3 column geometry (report redesign, Change 1+4). Severity column
# removed; a wide "IRAS ASK category" column carries the human-readable label.
# Widths sum to 17.0 cm = _UW.
_FIND_COLS = [1.3*cm, 1.7*cm, 2.5*cm, 0.9*cm, 2.0*cm, 4.0*cm, 4.6*cm]
_FIND_HDR_LABELS = ["Doc #", "Date", "Counterparty", "VG", "Amount",
                    "IRAS ASK category (code)", "Description"]
# NO_GST_REG per-supplier sub-table: supplier is the subheading and the IRAS
# category is a one-line subsection note, so neither is repeated per row.
_NGR_COLS = [1.6*cm, 2.2*cm, 1.2*cm, 2.5*cm, 9.5*cm]
_NGR_HDR_LABELS = ["Doc #", "Date", "VG", "Amount", "Description"]


def _amount_str(f) -> str:
    """Amount cell text: line_total, else doc_total (tagged), else em-dash."""
    if f.line_total is not None:
        return _sgd(f.line_total)
    if f.doc_total is not None:
        return _sgd(f.doc_total) + " (doc total)"
    return "—"


def _find_row(f) -> list:
    """Main Section-3 table row (no severity; IRAS category as primary label)."""
    return [
        _p(str(f.doc_num) if f.doc_num is not None else "—"),
        _p(f.doc_date or "—"),
        _p(f.card_name or "—"),
        _p(f.vat_group or "—"),
        _p(_amount_str(f)),
        _p(_category_code_label(f.appendix1_category, f.error_code)),
        _desc_cell(f.description, f.recommendation),
    ]


def _findings(m: ReportModel, story: list) -> None:
    """Append Section 3 — Findings grouped by ASK template.

    Report redesign (Avinash feedback):
      * Change 1 — each finding's IRAS ASK Appendix-1 wording is the primary
        label; the raw error_code is a small "(CODE)" tag.
      * Change 3 — NO_GST_REG (unregistered-supplier) findings render grouped
        under one subheading per supplier; every per-document row is preserved.
      * Change 4 — no severity badge/column; rows are ordered by dollar impact
        (largest first). The model-level severity sort is unchanged; this is a
        render-only re-sort via _findings_display_order.

    Args:
        m:     The ReportModel containing grouped findings.
        story: Mutable story list; flowables are appended in place.
    """
    story.append(Paragraph("3.  Findings by IRAS ASK Template", _H2))
    story.append(Paragraph(
        f"Total: {m.findings.total_findings} finding(s). "
        "Sorted by dollar impact, largest first.",
        _SMLX,
    ))

    f_hdr = [_p(h, _CELLB) for h in _FIND_HDR_LABELS]
    ngr_hdr = [_p(h, _CELLB) for h in _NGR_HDR_LABELS]

    for grp in m.findings.groups:
        if not grp.findings:
            continue
        # Split unregistered-supplier findings out for per-supplier grouping.
        others = [f for f in grp.findings if f.error_code != "NO_GST_REG"]
        nogst = [f for f in grp.findings if f.error_code == "NO_GST_REG"]

        # Template heading kept with the first table so it is never orphaned.
        head_block = [Spacer(1, 0.35 * cm), Paragraph(grp.template_ref["label"], _H3)]
        if others:
            rows = [_find_row(f) for f in _findings_display_order(others)]
            head_block.append(_table(_FIND_COLS, f_hdr, rows))
        story.append(KeepTogether(head_block))

        if nogst:
            # One IRAS category applies to every NO_GST_REG row — state it once.
            note = _category_code_label(nogst[0].appendix1_category, "NO_GST_REG")
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(
                f"Purchases from non-GST-registered suppliers — {note}, grouped by supplier:",
                _SMALL,
            ))
            for supplier, fs in _group_nogstreg_by_supplier(nogst):
                sup_rows = [
                    [
                        _p(str(f.doc_num) if f.doc_num is not None else "—"),
                        _p(f.doc_date or "—"),
                        _p(f.vat_group or "—"),
                        _p(_amount_str(f)),
                        _desc_cell(f.description, f.recommendation),
                    ]
                    for f in _findings_display_order(fs)
                ]
                sup_block = [
                    Paragraph(f"{supplier} ({len(fs)} document(s))", _H3),
                    _table(_NGR_COLS, ngr_hdr, sup_rows),
                ]
                story.append(KeepTogether(sup_block))


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
    # Change 1 (Avinash): show the IRAS ASK wording as the primary label with the
    # raw code as a "(CODE)" tag, replacing the bare "Error codes" column.
    cols = [2.0*cm, 4.0*cm, _UW - 6.0*cm]
    hdr = [_p(h, _CELLB) for h in ["Doc #", "Counterparty", "IRAS ASK categories (code)"]]
    rows = [
        [
            _p(str(e.doc_num)),
            _p(e.findings[0].card_name if e.findings else "—"),
            # dict.fromkeys preserves insertion order and silently deduplicates
            # identical "wording (code)" labels across a document's findings.
            _p("; ".join(dict.fromkeys(
                _category_code_label(f.appendix1_category, f.error_code)
                for f in e.findings
            ))),
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


def _extra_candidates_subsections(m: ReportModel, story: list) -> None:
    """Render second/Nth reasoning streams (T2.27) within Section 5.

    Iterates model.extra_candidates (a {skill_id: AICandidatesSection} mapping)
    and renders each stream through the same gated layout as the reg2627
    AI-candidates subsection.  A stream is drawn ONLY when its section.show is
    True, so the show_ai_candidates freeze gate covers every reasoning stream
    identically.

    No-op — the story list is left unchanged — when model.extra_candidates is
    None/empty (every existing reg2627-only run), keeping those PDFs byte-identical.

    Args:
        m:     The ReportModel; extra_candidates may be None for legacy callers.
        story: Mutable story list; flowables are appended in place.
    """
    extras = getattr(m, "extra_candidates", None)
    if not extras:
        return

    # Deterministic order so the rendered PDF is stable across runs.
    for skill_id in sorted(extras):
        sec = extras[skill_id]
        if sec is None or not sec.show:
            continue

        story.append(Spacer(1, 0.4 * cm))
        story.append(HRFlowable(width=_UW, thickness=0.5, color=_AI_GRID))
        story.append(Paragraph(
            f"AI-surfaced candidates (unvalidated) — {skill_id}",
            _H3_AI,
        ))

        if sec.status == "errored":
            story.append(Paragraph("AI candidate pass did not complete.", _BODY))
            continue

        if sec.status == "ok" and sec.candidate_count == 0:
            story.append(Paragraph("No AI-surfaced candidates.", _BODY))
        else:
            ai_cols = [1.8*cm, 1.8*cm, 2.0*cm, 2.8*cm, 2.8*cm, 2.0*cm, 4.0*cm]
            ai_hdr = [_p(h, _CELLB) for h in
                      ["Doc #", "Line", "Date", "Counterparty", "Category",
                       "Confidence", "Reviewer prompt"]]
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
                for c in sec.candidates
            ]
            story.append(Table(
                [ai_hdr] + ai_rows,
                colWidths=ai_cols,
                style=_ai_table_style(),
                repeatRows=1,
            ))

        if sec.disclaimer:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(sec.disclaimer, _SMLX_AI))


def _esc_xml(text: str) -> str:
    """Minimal XML escape for Paragraph markup (candidate messages carry '&')."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _document_crossref(m: ReportModel, story: list) -> None:
    """Section — Source-Document Cross-Reference (T-E(2)/D-46). UNGATED.

    Deterministic comparisons over values extracted from supplied source documents;
    show_ai_candidates gates reasoning-layer (LLM) candidates only (the legibility-rows
    precedent for ungated rendering). Extraction provenance renders per candidate.
    NO severity word renders here (the negative paper pins ban them).
    """
    sec = getattr(m, "document_crossref", None)
    if sec is None or not getattr(sec, "show", False):
        return
    story.append(Paragraph("Source-Document Cross-Reference", _H2))
    story.append(Paragraph(_esc_xml(sec.disclaimer), _SMLX))
    for r in sec.rows:
        story.append(Paragraph(
            f"<b>{_esc_xml(r.doc_num)}</b> — {_esc_xml(r.check_label)} · {_esc_xml(r.provenance)}",
            _BODY,
        ))
        story.append(Paragraph(_esc_xml(r.message), _SMLX))
    story.append(Spacer(1, 6))


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
    # T2.27: second/Nth reasoning streams, gated identically to reg2627.
    _extra_candidates_subsections(m, story)


def _partial_exemption(m: ReportModel, story: list) -> None:
    """Append the deterministic partial-exemption / De Minimis section (Prompt I).

    No-op when model.partial_exemption is None (legacy caller) or show=False (the
    check did not fire) — the rest of the report stays byte-identical.

    UNGATED like the analytical review: keys ONLY on section.show (the check
    firing), never on show_ai_candidates — this is a deterministic finding
    surface, not an AI-candidate stream. The wording renders the computed
    position given the CODED figures; every finding is a reviewer candidate.

    Args:
        m:     The ReportModel; partial_exemption may be None for legacy callers.
        story: Mutable story list; flowables are appended in place.
    """
    pe = getattr(m, "partial_exemption", None)
    if pe is None or not pe.show:
        return

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Partial Exemption — De Minimis Position (ASK Step 6)", _H2
    ))
    for f in pe.findings:
        story.append(Paragraph(str(f.get("description", "")), _BODY))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(
            f"<b>Computed on coded figures:</b> Box 3 = {f.get('box_3')}; "
            f"monthly average = {f.get('monthly_average_exempt')} "
            f"(threshold {f.get('threshold_monthly_avg')}"
            f"{' — breached' if f.get('monthly_average_breached') else ''}); "
            f"exempt share = {f.get('exempt_ratio')} "
            f"(threshold {f.get('threshold_ratio')}"
            f"{' — breached' if f.get('ratio_breached') else ''}).",
            _SMALL,
        ))
        story.append(Paragraph(str(f.get("txre_note", "")), _SMALL))
        story.append(Paragraph(f"Basis: {f.get('basis', '')}", _SMALL))
        if f.get("caveat"):
            story.append(Paragraph(str(f["caveat"]), _SMALL))
        if f.get("caveat_incidental"):
            story.append(Paragraph(str(f["caveat_incidental"]), _SMALL))
        story.append(Paragraph(str(f.get("note", "")), _SMALL))


def _scheme_status(m: ReportModel, story: list) -> None:
    """Append the deterministic scheme-status contradiction section.

    No-op when model.scheme_status is None (legacy caller) or show=False (the
    check did not fire) — the rest of the report stays byte-identical.

    UNGATED like the partial-exemption section: keys ONLY on section.show,
    never on show_ai_candidates — this is a deterministic finding surface, not
    an AI-candidate stream. The wording carries BOTH hypotheses (stale
    configuration vs lines coded to a scheme not participated in) and asserts
    neither; every finding is a reviewer candidate.

    Args:
        m:     The ReportModel; scheme_status may be None for legacy callers.
        story: Mutable story list; flowables are appended in place.
    """
    ss = getattr(m, "scheme_status", None)
    if ss is None or not ss.show:
        return

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Scheme Status — Configuration vs Coded Lines", _H2
    ))
    for f in ss.findings:
        story.append(Paragraph(str(f.get("description", "")), _BODY))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(
            f"<b>Severity:</b> {f.get('severity', '—')} — "
            f"{f.get('doc_count', '—')} document(s) carrying the "
            f"{f.get('vat_group', '—')} VatGroup code; configuration flag "
            f"{f.get('config_flag', '—')}.",
            _SMALL,
        ))
        story.append(Paragraph(str(f.get("severity_note", "")), _SMALL))
        story.append(Paragraph(f"Basis: {f.get('basis', '')}", _SMALL))
        story.append(Paragraph(str(f.get("note", "")), _SMALL))


def _analytical_review(m: ReportModel, story: list) -> None:
    """Append the Annual Analytical Review section when the pass ran.

    No-op when model.analytical_review is None or show=False, keeping the rest
    of the report byte-identical to a run without --analytical-review.

    Renders: FY period context; per-quarter Box 1/2/3/5 table; FY totals and
    TP/TS ratio; any TP_TS_RATIO findings with the RC/OVR approximation caveat.

    Args:
        m:     The ReportModel; analytical_review may be None for legacy callers.
        story: Mutable story list; flowables are appended in place.
    """
    ar = getattr(m, "analytical_review", None)
    if ar is None or not ar.show:
        return

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Annual Analytical Review — ASK Step 1.3d (TP/TS Ratio)", _H2
    ))
    story.append(Paragraph(
        f"Financial year: {ar.fy_start} to {ar.fy_end}.  "
        "Taxable Purchases (Box 5) / Total Supplies (Box 4) ratio computed from "
        "four quarterly SAP reads.  IRAS threshold: ratio &gt; 1.2 is a "
        "candidate for reviewer explanation.",
        _SMLX,
    ))
    story.append(Spacer(1, 0.2 * cm))

    # Per-quarter box table — column widths sum to _UW (17.0 cm)
    q_cols = [3.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 3.5*cm]
    q_hdr = [_p(h, _CELLB) for h in
             ["Quarter", "Box 1", "Box 2", "Box 3", "Box 4 (sum)", "Box 5"]]
    q_rows = []
    for qb in ar.quarter_boxes:
        box4_q = qb["box_1"] + qb["box_2"] + qb["box_3"]
        q_rows.append([
            Paragraph(f"{qb['period_start']}<br/>{qb['period_end']}", _CELL),
            _p(_sgd(qb["box_1"])),
            _p(_sgd(qb["box_2"])),
            _p(_sgd(qb["box_3"])),
            _p(_sgd(box4_q)),
            _p(_sgd(qb["box_5"])),
        ])
    story.append(_table(q_cols, q_hdr, q_rows))

    # FY totals and ratio
    story.append(Spacer(1, 0.15 * cm))
    fy_b4 = Decimal(ar.fy_box_4)
    fy_b5 = Decimal(ar.fy_box_5)
    ratio_display = ar.ratio if ar.ratio is not None else "—"
    story.append(Paragraph(
        f"<b>FY Box 4 (Total Supplies):</b>  {_sgd(fy_b4)}"
        f"   <b>FY Box 5 (Taxable Purchases):</b>  {_sgd(fy_b5)}"
        f"   <b>TP/TS Ratio:</b>  {ratio_display}",
        _BODY,
    ))

    # TP/TS findings — empty list when ratio ≤ 1.2
    if ar.findings:
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph("TP/TS Ratio — Candidate for Review", _H3))
        for f in ar.findings:
            story.append(Paragraph(f.get("description", ""), _BODY))
            if f.get("caveat"):
                story.append(Spacer(1, 0.1 * cm))
                story.append(Paragraph(f.get("caveat"), _SMLX))
            if f.get("note"):
                story.append(Paragraph(f"Note: {f.get('note')}", _SMLX))
    else:
        story.append(Spacer(1, 0.1 * cm))
        story.append(Paragraph(
            "TP/TS ratio is within the IRAS threshold — no finding.", _SMALL
        ))

    # QoQ fluctuation findings — ASK §1.3a, T2.17
    fluct = getattr(ar, "fluctuation_findings", None) or []
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "QoQ Fluctuation Candidates — ASK Step 1.3a", _H3
    ))
    if fluct:
        story.append(Paragraph(
            "The following quarter-over-quarter movements in F5 boxes exceed the ±50% "
            "surfacing threshold (non-regulatory tuning parameter, not an IRAS rule). "
            "Each is a candidate for reviewer explanation — business cycle, seasonal "
            "pattern, or data issue.",
            _SMLX,
        ))
        story.append(Spacer(1, 0.1 * cm))
        for f in fluct:
            story.append(Paragraph(f.description, _BODY))
    else:
        story.append(Paragraph(
            "No material quarter-over-quarter fluctuations detected at the ±50% threshold.",
            _SMALL,
        ))


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

    The pass EXECUTION STATE (tfix) drives whether — and how — the section renders, so a
    clean run is positively marked examined and a thrown pass is marked could-not-run,
    never silently absent (which read identically before the fix):
      * "not_examined" with no findings → skipped (Section 6 carries the not-examined
        line — the historical legacy behaviour);
      * "unavailable" → a "could not run" note surfacing the execution reason;
      * "examined" with no findings → a positive "checks performed; no findings" note;
      * any findings → the per-check subsection tables below.

    Args:
        m:     The ReportModel containing listing_findings.
        story: Mutable story list; flowables are appended in place.
    """
    lf = m.listing_findings
    if lf is None:
        return
    status = getattr(lf, "status", "examined")
    has_findings = bool(lf.seq_gap_findings or lf.dup_claim_findings)
    if status == "not_examined" and not has_findings:
        return

    story.append(Paragraph("Invoice Listing Completeness Checks", _H2))
    story.append(Paragraph(
        "Invoice-listing completeness checks (IRAS ASK Annual Review Guide §10.1). "
        "Findings are candidates for reviewer attention; they do not affect F5 box "
        "totals or gate outcomes.",
        _SMLX,
    ))

    if status == "unavailable":
        story.append(Paragraph(
            f"These checks could not run for this review ({lf.reason}); "
            "invoice-listing completeness is NOT covered by this report.",
            _SMALL,
        ))
        return

    if not has_findings:
        story.append(Paragraph(
            "Checks performed — no sequence gaps or duplicate input-tax claims detected.",
            _SMALL,
        ))
        return

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


def _document_dup(m: ReportModel, story: list) -> None:
    """Render the same-day duplicate-purchase surfacer (DUP_SAME_DAY) when present.

    Mirrors _listing_findings' three-state rendering (examined / unavailable /
    not_examined), and carries the honest-status caveats VERBATIM in the section
    header so a reviewer sees the surfacer's limits on the page:
      * "not_examined" with no findings → skipped (legacy compile_output);
      * "unavailable" → a "could not run" note surfacing the execution reason;
      * "examined" with no findings → a positive "checks performed; none found" note;
      * any findings → the candidate table.

    The surfacer NEVER asserts the documents are duplicates; every row is a candidate
    for reviewer attention. Read-only over the section; touches no F5 box, no gate.

    Args:
        m:     The ReportModel carrying the optional document_dup section.
        story: Mutable story list; flowables are appended in place.
    """
    dd = getattr(m, "document_dup", None)
    if dd is None:
        return
    status = getattr(dd, "status", "examined")
    has_findings = bool(dd.findings)
    if status == "not_examined" and not has_findings:
        return

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Same-Day Duplicate-Purchase Review", _H2))
    story.append(Paragraph(
        "Surfaces purchase invoices sharing the same supplier, total, and date as "
        "candidates for reviewer attention — never an assertion that they are "
        "duplicates. It does not affect F5 box totals or gate outcomes.",
        _SMLX,
    ))
    # Honest-status caveats — VERBATIM on the page, one per line so PDF line-wrapping
    # never splits a caveat phrase mid-string (each must survive text extraction intact).
    #
    # G6 (D-2026-07-27-dup-window): the third caveat is CONDITIONAL. On a paper with
    # no active window section the string is BYTE-IDENTICAL to the locked pin
    # (tests/test_document_dup_section.py — passes UNAMENDED). On a paper where the
    # window check is enabled (any run state), "pending a worksheet-derived window"
    # would be a FALSE statement — a window check exists — so the caveat scopes this
    # section truthfully instead, deferring to the window section's own status.
    _window = getattr(m, "document_dup_window", None)
    _window_active = _window is not None and _window.status != "not_enabled"
    _scope_caveat = (
        "same-day pairs only in this section; multi-day pairs are the Windowed "
        "Duplicate-Purchase Review's scope — see that section's own status below"
        if _window_active
        else "same-day only pending a worksheet-derived window"
    )
    story.append(Paragraph("Honest status of this check:", _SMALL))
    for _caveat in (
        "built",
        "not accuracy-validated",
        _scope_caveat,
        "over-firing untestable pending a must-spare fixture",
    ):
        story.append(Paragraph(f"— {_caveat}", _SMALL))

    if status == "unavailable":
        story.append(Paragraph(
            f"This check could not run for this review ({dd.reason}); "
            "same-day duplicate-purchase completeness is NOT covered by this report.",
            _SMALL,
        ))
        return

    if not has_findings:
        story.append(Paragraph(
            "Check performed — no same-supplier, same-total, same-day purchase "
            "collisions detected.",
            _SMALL,
        ))
        return

    story.append(Paragraph(
        f"{len(dd.findings)} same-day collision candidate(s). Each groups two or more "
        "purchase invoices sharing supplier, total, and date.",
        _SMALL,
    ))
    dd_cols = [3.6*cm, 2.4*cm, 2.6*cm, 3.4*cm, 5.0*cm]
    dd_hdr = [_p(h, _CELLB) for h in
              ["Supplier", "Date", "Total (SGD)", "DocNums", "Description"]]
    dd_rows = [
        [
            _p(f.get("card_name", "—")),
            _p(str(f.get("doc_date", "—"))),
            _p(_sgd(f.get("doc_total"))),
            _p(", ".join(str(n) for n in f.get("doc_nums", []))),
            _p(f.get("description", "—")),
        ]
        for f in dd.findings
    ]
    story.append(_table(dd_cols, dd_hdr, dd_rows))


def _document_dup_window(m: ReportModel, story: list) -> None:
    """Render the windowed duplicate-purchase surfacer (DUP_WINDOW) when declared.

    D-2026-07-27-dup-window. Four states (G5, amended): the model section is None
    when the client config declares NO dup_window position — nothing renders and
    every undeclared paper (including SAP) stays byte-identical. A DECLARED
    position always renders the section, in one of:
      * "not_enabled"  → the check is declared but OFF — stated on the page,
                         distinguishably from not_examined;
      * "not_examined" → enabled, but this review's compiled output predates the
                         check — it was NOT performed here;
      * "unavailable"  → could not run; the execution reason is surfaced;
      * "examined"     → ran; zero findings is a positive statement, and findings
                         render as candidates for reviewer attention.

    G2: the ASK cite and the OURS label live in the SAME paragraph — the cite never
    travels without the label. The surfacer NEVER asserts documents are duplicates;
    read-only over the section; touches no F5 box, no gate.

    Args:
        m:     The ReportModel carrying the optional document_dup_window section.
        story: Mutable story list; flowables are appended in place.
    """
    dw = getattr(m, "document_dup_window", None)
    if dw is None:
        return  # no declared position → silent omission (the established rule)

    window_word = str(dw.window_days) if dw.window_days is not None else "N"

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Windowed Duplicate-Purchase Review", _H2))

    # H1 (Terry ruling): on "not_enabled", the heading and the not-enabled statement
    # ONLY — no basis paragraph, no honest-status caveats. Those lines describe a
    # check that did not run: a window "never applied to anything" needs no cite and
    # no caveat, and six lines of check-properties before "there was no check" builds
    # a model the last line has to demolish. G2 is not weakened — the cite travels
    # with the check's OUTPUT, and there is none. The enabled-but-didn't-run states
    # (unavailable / not_examined) keep the full framing: the check WAS enabled, so
    # describing its parameters is fair.
    if dw.status == "not_enabled":
        story.append(Paragraph(
            "This check is declared for this client but NOT ENABLED — no windowed "
            "duplicate-purchase review was performed for this period. This differs "
            "from a review performed with no findings.",
            _SMALL,
        ))
        return

    story.append(Paragraph(
        "Surfaces purchase invoices sharing the same supplier and the same total, "
        f"one to {window_word} days apart, as candidates for reviewer attention — "
        "never an assertion that they are duplicates. It does not affect F5 box "
        "totals or gate outcomes. Distinct from the same-day review above (day-zero "
        "pairs belong there) and from the vendor-reference check (DUP_CLAIM) — "
        "different predicates, different units, not one check.",
        _SMLX,
    ))
    # G2 — the cite and its label, one paragraph, inseparable.
    story.append(Paragraph(
        "Basis: IRAS ASK Annual Review Guide Step 3D.1.1(d) — check that input tax "
        "is not claimed on the same transaction more than once. The guide prescribes "
        f"the question, not this method: the {window_word}-day window and the "
        "exact-amount matching are AgentAssist operationalisations — a non-regulatory "
        "tuning parameter, not an IRAS rule.",
        _SMALL,
    ))
    # Honest-status caveats — VERBATIM, one per line (G7 vacuity + G8 pair-shape).
    story.append(Paragraph("Honest status of this check:", _SMALL))
    for _caveat in (
        "built",
        "not accuracy-validated",
        "window value is a demo parameter fitted to the committed fixture, not a "
        "validated threshold",
        "over-firing untestable pending a must-spare fixture; the legitimate "
        "recurring-charge (standing-order) case is UNTESTED, not absent",
        "findings are pair-shaped (two document numbers per row) and carry no single "
        "document identity; they cannot be keyed by the decision ledger, so "
        "review-panel actions do not apply — paper-only candidates",
    ):
        story.append(Paragraph(f"— {_caveat}", _SMALL))

    if dw.status == "not_examined":
        story.append(Paragraph(
            "This check is enabled for this client, but this review's compiled "
            "output predates it — the windowed review was NOT performed for this "
            "review.",
            _SMALL,
        ))
        return

    if dw.status == "unavailable":
        story.append(Paragraph(
            f"This check could not run for this review ({dw.reason}); windowed "
            "duplicate-purchase completeness is NOT covered by this report.",
            _SMALL,
        ))
        return

    if not dw.findings:
        story.append(Paragraph(
            "Check performed — no same-supplier, same-total purchase pairs within "
            f"the {window_word}-day window.",
            _SMALL,
        ))
        return

    story.append(Paragraph(
        f"{len(dw.findings)} windowed pair candidate(s). Each row is ONE pair of "
        "purchase invoices sharing supplier and total, dated within the window.",
        _SMALL,
    ))
    dw_cols = [3.0*cm, 2.8*cm, 2.2*cm, 1.4*cm, 3.0*cm, 4.6*cm]
    dw_hdr = [_p(h, _CELLB) for h in
              ["Supplier", "Dates", "Total (SGD)", "Days", "DocNums", "Description"]]
    dw_rows = [
        [
            _p(f.get("card_name", "—")),
            _p(", ".join(str(d) for d in f.get("doc_dates", []))),
            _p(_sgd(f.get("doc_total"))),
            _p(str(f.get("delta_days", "—"))),
            _p(", ".join(str(n) for n in f.get("doc_nums", []))),
            _p(f.get("description", "—")),
        ]
        for f in dw.findings
    ]
    story.append(_table(dw_cols, dw_hdr, dw_rows))


def _ledger_recon(m: ReportModel, story: list) -> None:
    """Render the T2.24 GST control-ledger reconciliation (Signal A + B) when present.

    Empty-when-empty: a clean run (examined, no findings) or a never-run reconciliation
    appends NOTHING — Section 6 carries the "not reconciled" line for the never-run case.
    Renders per-side divergence candidates (Signal A), the dropped-posting candidates
    (Signal B), and an honest "could not run" caveat for an unavailable sub-signal.
    Read-only projection over already-computed findings; touches no F5 box, no gate.

    Args:
        m:     The ReportModel carrying the optional ledger_recon section.
        story: Mutable story list; flowables are appended in place.
    """
    sec = getattr(m, "ledger_recon", None)
    if sec is None:
        return
    recon_status = getattr(sec, "recon_status", "not_examined")
    recon_findings = getattr(sec, "recon_findings", None) or []
    drop_status = getattr(sec, "drop_status", "not_examined")
    drop_findings = getattr(sec, "drop_findings", None) or []

    recon_shows = recon_status == "unavailable" or bool(recon_findings)
    drop_shows = drop_status == "unavailable" or bool(drop_findings)
    if not (recon_shows or drop_shows):
        return

    story.append(Paragraph("GST Control-Ledger Reconciliation", _H2))
    story.append(Paragraph(
        "Internal-consistency reconciliation of the GST control-account (820) ledger "
        "against the declared F5 return (IRAS ASK Annual Review Guide §10.1(e)). Findings "
        "are candidates for reviewer attention; they do not affect F5 box totals or gate "
        "outcomes. This is an internal-consistency check, not a truth check — a "
        "consistently-mis-coded transaction agrees on both sides and is invisible here.",
        _SMLX,
    ))

    # Signal A — ledger-derived GST vs the declared return boxes.
    if recon_status == "unavailable":
        story.append(Paragraph(
            "Ledger-vs-declared-return reconciliation could not run for this review "
            f"({sec.recon_reason}).",
            _SMALL,
        ))
    elif recon_findings:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Ledger vs Declared Return (Signal A)", _H3))
        for f in recon_findings:
            story.append(Paragraph(
                f"[{f.get('side', '—')}] {f.get('description', '')}", _SMALL))
            rec = f.get("recommendation")
            if rec:
                story.append(Paragraph(rec, _SMLX))

    # Signal B — GST postings dropped from the F5 report.
    if drop_status == "unavailable":
        story.append(Paragraph(
            "Not-included GST-posting review could not run for this review "
            f"({sec.drop_reason}).",
            _SMALL,
        ))
    elif drop_findings:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph("Postings Excluded from the F5 Return (Signal B)", _H3))
        for f in drop_findings:
            story.append(Paragraph(
                f"[{f.get('account', '—')} {f.get('reference', '')}] "
                f"{f.get('description', '')}",
                _SMALL))
            rec = f.get("recommendation")
            if rec:
                story.append(Paragraph(rec, _SMLX))


def _check_coverage(m: ReportModel, story: list) -> None:
    """Render the dedicated Deterministic Check Coverage section (T2.12-2C).

    Renders 2B's per-check data-coverage status so the reviewer can SEE what was and
    was not fully examined — a silently-partial review becomes impossible to sign
    unknowingly. A DEDICATED sibling surface (its own heading), distinct from the
    listing-completeness section, the show_ai_candidates probabilistic surface, and
    Section 6. No-op when the chain reader exposed no coverage seam (live SAP / frozen
    replay → no rows), so the report stays byte-identical on those paths.

    Args:
        m:     The ReportModel containing the optional check_coverage section.
        story: Mutable story list; flowables are appended in place.
    """
    cc = getattr(m, "check_coverage", None)
    if cc is None or not getattr(cc, "rows", None):
        return
    story.append(Paragraph("Deterministic Check Coverage", _H2))
    story.append(Paragraph(
        "Per-check data-coverage status for the deterministic checks. This makes the "
        "coverage of the review explicit — what was fully examined, what ran with "
        "reduced coverage, and what could not run — so a silently-partial review is "
        "never signed unknowingly. Caveats state the available DATA only and assert no "
        "compliance verdict; the tax basis remains the reviewer's to source.",
        _SMLX,
    ))
    for row in cc.rows:
        story.append(Paragraph(f"•  {_coverage_line(row)}", _SMALL))


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

    #43 signable-render guard: when ``m.show_ai_candidates`` is True this render
    includes UNVALIDATED AI-candidate content, so the sign-off is SUPPRESSED — an
    explicit do-not-sign notice replaces the ruled signature line entirely (no
    line to sign on). The guard keys on ``show_ai_candidates`` ONLY, never on
    ``validation_status``: the deterministic working paper is meant to be
    human-signed regardless of T2.11. In the signable branch the system still
    never signs — the ruled line stays empty until a human signs it.

    Args:
        m:     The ReportModel containing signature and disclaimer data.
        story: Mutable story list; flowables are appended in place.
    """
    story.append(PageBreak())
    story.append(Paragraph("Declaration and Sign-Off", _H2))

    if m.show_ai_candidates:
        # SUPPRESSED branch (#43): no declaration text, no ruled line, no date
        # field — nothing that invites a signature on an AI-preview render.
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(
            "<b>Signature suppressed.</b> This render includes UNVALIDATED "
            "AI-candidate preview content (show_ai_candidates enabled) and is "
            "NOT a signable working paper. Do not sign this document. Render "
            "the standard working paper (AI-candidate preview disabled) to "
            "obtain the signable version — the deterministic findings and F5 "
            "boxes in this document are identical in that version.",
            _BODY,
        ))
        story.append(Spacer(1, 1.2 * cm))
        story.append(HRFlowable(width=_UW, thickness=0.25, color=_GRID_LINE))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(m.signature.disclaimer, _SMLX))
        return

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

def _accumulated(m: ReportModel, story: list) -> None:
    """Accumulated review evidence (t-accumulated-sign) — rendered before sign-off.

    BOUNDING INVARIANT made visible: the paper's boxes/structure come from the PRIMARY
    slice alone (re-executed at signing); every non-primary slice below contributes
    FINDINGS ONLY, rendered AS STORED at attach time with per-slice provenance
    (source_kind, short sha, attach timestamp). Mixed vintage is shown via the
    timestamps, never hidden. Coverage renders per-source so one slice's "examined"
    never masks another's "unavailable". Supersession is listed visibly (Terry R2).
    No-op when m.accumulated is None (every per-slice/legacy render byte-identical).
    """
    sec = m.accumulated
    if sec is None or not getattr(sec, "show", False):
        return
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        f"Accumulated review evidence — session {sec.review_id}", _H1
    ))
    story.append(Paragraph(
        (
            f"Primary slice: {sec.primary_source_kind} (sha {sec.primary_sha256_short}), "
            f"re-executed at signing on {sec.sign_run_at}. The F5 boxes and report "
            "structure above derive from the primary slice ALONE — figures from other "
            "exports are never merged into them. Each slice below contributes findings "
            "only, rendered as stored at its attach timestamp (mixed vintages are "
            "visible by these timestamps)."
        ),
        _BODY,
    ))
    for note in sec.superseded_notes:
        story.append(Paragraph(f"Superseded: {note}", _BODY))
    for group in sec.groups:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            (
                f"Evidence slice: {group.source_kind} · sha {group.sha256_short} · "
                f"attached {group.uploaded_at[:10]} · {group.period_label}"
            ),
            _BODY,
        ))
        if not group.rows:
            story.append(Paragraph("No findings stored for this slice.", _BODY))
            continue
        rows = [
            [
                _p(r.check_id), _p(r.display_name), _p(r.doc_num), _p(r.vendor),
                _p(r.severity), _p(f"{r.description} [from {group.source_kind}]"),
            ]
            for r in group.rows
        ]
        story.append(_table(
            [0.09 * _UW, 0.21 * _UW, 0.10 * _UW, 0.14 * _UW, 0.08 * _UW, 0.38 * _UW],
            ["Check", "Display name", "Document", "Vendor", "Sev.", "Description · source"],
            rows,
        ))
    if sec.coverage_rows:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            "Coverage across slices (per-source attribution — one export's "
            "'examined' never masks another's 'unavailable'):", _BODY,
        ))
        story.append(_table(
            [0.20 * _UW, 0.18 * _UW, 0.12 * _UW, 0.50 * _UW],
            ["Check", "Source", "Level", "Reason"],
            [
                [_p(c), _p(sk), _p(lv), _p(rs or "—")]
                for (c, sk, lv, rs) in sec.coverage_rows
            ],
        ))


def _adjudications(m: ReportModel, story: list) -> None:
    """Reviewer adjudications (t-decision-render) — rendered before sign-off.

    Renders the decision view handed in AS DATA (api builds it; this module imports
    nothing from agent/ — tests/test_leaf_import_purity.py). R3: DISPOSITIONS only,
    never the UI verb (the free-text reason is never rendered). R4: the FULL ordered
    history per finding — a reviewer changing their mind is exactly what a working
    paper must show. R5b: additive — this section annotates; it never removes a
    finding from the paper, so the paper cannot contradict its sealed detect.issues.
    R2: superseded (pre-current-version) decisions surface as an aggregate count line
    only — per-finding attribution of a superseded entry is structurally impossible.
    No-op when m.adjudications is None/hidden (decision-free renders byte-identical).
    Wording deliberately avoids the unamendable negative text pins (R5c).
    """
    sec = m.adjudications
    if sec is None or not getattr(sec, "show", False):
        return
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Reviewer adjudications (recorded decisions)", _H1))
    story.append(Paragraph(
        (
            "The entries below are reviewer decisions read from AgentAssist's "
            "append-only decision ledger, reported AS STORED. They record what a "
            "human decided and assert nothing about the correctness of the "
            "underlying findings. Every finding remains shown on this paper — a "
            "set-aside decision demotes a finding, it never removes it."
        ),
        _BODY,
    ))
    for block in sec.clients:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            f"Decision store: {block.get('client_id') or '—'}", _BODY
        ))
        for f in block.get("findings") or []:
            marker = (
                " — SET ASIDE (demoted by prior adjudication; still shown above)"
                if f.get("demoted") else ""
            )
            doc_num = f.get("doc_num") or "—"
            story.append(Paragraph(
                f"{f.get('check_id')} · {f.get('vendor') or '—'} · document "
                f"{doc_num}{marker}",
                _BODY,
            ))
            rows = [
                [
                    _p(str(i + 1)),
                    _p(h.get("disposition") or "—"),
                    _p(h.get("reviewer") or "—"),
                    _p(h.get("timestamp") or "—"),
                    _p(h.get("period") or "—"),
                ]
                for i, h in enumerate(f.get("history") or [])
            ]
            story.append(_table(
                [0.05 * _UW, 0.22 * _UW, 0.28 * _UW, 0.30 * _UW, 0.15 * _UW],
                ["#", "Disposition", "Reviewer", "Recorded at", "Period"],
                rows,
            ))
        count = block.get("superseded_count") or 0
        if count > 0:
            story.append(Paragraph(
                (
                    f"{count} stored adjudication(s) for this client do not apply to "
                    "this review because they were recorded under a superseded "
                    "finding-identity version."
                ),
                _BODY,
            ))


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
    # #43 signable-render guard: a render carrying UNVALIDATED AI-candidate preview
    # content opens with a loud report-level banner (and its sign-off is suppressed
    # in _signature). Gated on show_ai_candidates ONLY — never validation_status;
    # the flag is False in every committed config, so the standard render is
    # byte-identical (banner absent).
    if model.show_ai_candidates:
        story.append(Paragraph(
            "UNVALIDATED — AI-CANDIDATE PREVIEW RENDER", _H1,
        ))
        story.append(Paragraph(
            "This document includes AI-candidate preview sections that are "
            "unvalidated and advisory only. It is NOT a signable working paper "
            "(the sign-off page is suppressed). The deterministic findings and "
            "F5 boxes it contains are unchanged from the standard working paper.",
            _BODY,
        ))
        story.append(Spacer(1, 0.6 * cm))
        story.append(HRFlowable(width=_UW, thickness=0.75, color=colors.black))
        story.append(Spacer(1, 0.6 * cm))
    _cover(model, story)
    _scope(model, story)
    _f5_boxes(model, story)
    _analytical_review(model, story)
    # Prompt I: deterministic partial-exemption / De Minimis position (ungated).
    _partial_exemption(model, story)
    # Scheme-status contradiction (config-vs-data, ungated).
    _scheme_status(model, story)
    _declared_f5(model, story)
    _findings(model, story)
    _listing_findings(model, story)
    _document_dup(model, story)
    # D-2026-07-27-dup-window: the windowed sibling renders beside the same-day
    # review (no-op when the config declares no dup_window position — every
    # undeclared paper, including SAP, stays byte-identical).
    _document_dup_window(model, story)
    _check_coverage(model, story)
    _ledger_recon(model, story)
    _cross_findings(model, story)
    _document_crossref(model, story)
    _judgment(model, story)
    _not_examined(model, story)
    # t-accumulated-sign: accumulated evidence renders LAST before sign-off (no-op
    # when model.accumulated is None — every per-slice render byte-identical).
    _accumulated(model, story)
    # t-decision-render: reviewer adjudications render between the evidence and the
    # sign-off block (no-op when model.adjudications is None/hidden — every
    # decision-free render byte-identical).
    _adjudications(model, story)
    _signature(model, story)

    NC = _make_numbered_canvas(model.cover.client_name)
    # canvasmaker= injects the numbered canvas subclass so every page receives
    # the two-pass footer stamp instead of the default bare Canvas.
    doc.build(story, canvasmaker=NC)
    return out_path
