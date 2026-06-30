"""feeders/xero_f5_reader.py — XeroF5ChainReader: a ChainReader over a REAL Xero IRAS-F5 export.

Parses the genuine Xero "Transactions by box number" workbook (the F5-period transaction
export) and emits the SAME shaped record lists/dicts the deterministic checking core consumes
from the live-SAP feeder — the identical structural ``ChainReader`` contract ``ExtractChainReader``
satisfies (T2.23), neither importing nor widening the Protocol:

    count(entity, period_start, period_end)            -> Optional[int]
    fetch_invoices(entity, period_start, period_end)   -> list[dict]
    fetch_credit_notes(entity_type, ps, pe)            -> list[dict]
    get_business_partner(card_code)                    -> dict
    fetch_listing(period)                              -> dict   (4 buckets)

It exists ALONGSIDE ``ExtractChainReader`` (the synthetic ``documents``/``business_partners``/
``listing`` shape) — it does NOT edit or branch that reader, so the synthetic path stays
byte-identical.

THREE REAL-FORMAT RULES this reader adds (each pinned in tests/test_xero_f5_reader.py — the
three-times rule):

  1. TITLE-BLOCK SKIP / ROW-5 HEADER. The real export carries a 4-row title block
     (sheet name / entity / period / blank); the column header is on row 5. The header row is
     located structurally (the row carrying the "Tax rate" + "Date" columns), so the four
     title rows are skipped without a hard-coded offset.

  2. TAX-RATE SUFFIX STRIP. Xero appends " (NN%)" to the tax-rate display name; the authored
     name itself may already carry a parenthetical and a leading space (e.g.
     " ZR-Broken (9%) [test] (9%)"). ``parse_tax_rate`` trims whitespace and strips ONLY the
     LAST " (NN%)" suffix (anchored to end), returning (name, rate-as-fraction).

  3. VALUE-BOX-ONLY STRUCTURAL SELECTION (the dedupe). The export groups transactions under
     labelled box sections. VALUE boxes ("Box 1 - ... supplies", "Box 5 - ... purchases")
     carry each transaction ONCE; TAX/restatement boxes ("Box 6 - Output tax due", "Box 7 -
     Less: Input tax ...", "Box 19 - ... Deferred import GST") RE-LIST the same transactions.
     The reader extracts ONLY from value boxes and SKIPS the restatement boxes — pairing is by
     box-section membership, NOT a content hash. So two genuinely-distinct look-alike rows
     (the DupSupplier quotation + tax invoice) are BOTH kept; a content-hash dedupe would
     wrongly collapse them (undercount). No hash dedupe is performed.

HONEST STATUS (T2.11): this is real-FORMAT validation over SYNTHETIC data. The committed
fixture mirrors a genuine Xero IRAS-F5 export LAYOUT but carries hand-authored synthetic
transactions — it is NOT a real client file and asserts NO GST/accuracy verdict, only that the
reader reproduces the canonical shaped surfaces.

The ``tax_rate_to_vat_group`` mapping is PROPOSED / UNVALIDATED (DEBT-1: IRAS Annex E citations
deferred). It is a CANDIDATE normalisation, never a verdict; an unmapped tax-rate name fails
loud rather than silently mis-coding.

ABSENT SURFACES (honest degrade, never fabricated). A Xero F5 export carries NO supplier master
and NO document-number listing, so:
  * ``get_business_partner`` raises KeyError (no BP master),
  * ``fetch_listing`` returns the four canonical buckets EMPTY,
  * ``coverage_status`` degrades the BP/listing-dependent checks (NO_GST_REG → unavailable,
    DUP_CLAIM/SEQ_GAP → degraded) through the SAME ``derive_coverage_statuses`` seam the
    synthetic reader uses. The Xero references are non-numeric and there is no card code, so
    DocNum carries the reference string and CardCode is empty.

Pure stdlib; openpyxl is imported lazily only inside the loader. No SAP, no anthropic.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Optional

from feeders import extract_schema as schema
from feeders.coverage_status import derive_coverage_statuses
from feeders.extract_reader import ExtractCoverage

# The sheet the real Xero IRAS-F5 export carries the period transactions on.
TRANSACTIONS_SHEET = "Transactions by box number"

# Real-export header column labels (row 5). Located structurally via _HEADER_MARKERS.
_COL_DATE = "Date"
_COL_REFERENCE = "Reference"
_COL_CONTACT = "Contact"
_COL_TAX_RATE = "Tax rate"
_COL_SOURCE_CURRENCY = "Source currency"
_COL_GROSS = "Gross"
_COL_NET = "Net"
_COL_TAX = "Tax"
# Two markers whose joint presence identifies the header row (so the 4-row title block is
# skipped structurally, not by a hard-coded offset).
_HEADER_MARKERS = (_COL_DATE, _COL_TAX_RATE)

# Box-section classification. VALUE boxes carry "total value of"; restatement (tax) boxes
# ("Output tax due", "Less: Input tax ...", "Deferred import GST") do NOT and are SKIPPED
# (they re-list value-box rows). Keying on the value marker avoids misreading Box 5's own
# "... input tax is disallowed" parenthetical as a tax box.
_VALUE_BOX_MARKER = "total value of"
# Entity routing from the value-box header text.
_PURCHASE_KEYWORDS = ("purchase", "import")
_SALES_KEYWORDS = ("suppl",)

# PROPOSED / UNVALIDATED name-stem → VatGroup mapping (DEBT-1; IRAS citations deferred).
# Candidate normalisation only — never surfaced as a verdict. An unmapped name fails loud.
_PROPOSED_VAT_GROUP_MAP = {
    "Standard-Rated Supplies": "SR",
    "Standard-Rated Purchases": "TX",
    "SR-NoGST": "SR",
    "ZR-Broken": "ZR",
    "SI-Stale": "TX",
}

# Trailing " (NN%)" suffix Xero appends to the tax-rate display name (anchored to END, so a
# double suffix strips only the LAST token).
_RATE_SUFFIX_RE = re.compile(r"\s*\((\d+(?:\.\d+)?)\s*%\)\s*$")


# ---------------------------------------------------------------------------
# Pure parse helpers (Rule 2).
# ---------------------------------------------------------------------------


def parse_tax_rate(display: str) -> tuple[str, Optional[float]]:
    """Strip the LAST trailing " (NN%)" suffix Xero appends; return (name, rate-as-fraction).

    Trims leading/trailing whitespace, then removes ONLY the final " (NN%)" token (the regex is
    anchored to the end), so a name that itself carries an earlier "(0%)" keeps it. The rate is
    returned as a fraction (e.g. 9% -> 0.09); a display with no suffix yields (name, None).
    """
    s = (display or "").strip()
    m = _RATE_SUFFIX_RE.search(s)
    if m is None:
        return s, None
    name = s[: m.start()].rstrip()
    rate = float(m.group(1)) / 100.0
    return name, rate


def _name_stem(display: str) -> str:
    """The mapping stem: the parsed name minus any trailing parenthetical/bracket decoration."""
    name, _rate = parse_tax_rate(display)
    # Cut at the first " (" or " [" so "SR-NoGST (0%) [test]" -> "SR-NoGST" while
    # "Standard-Rated Supplies" (no decoration) stays whole.
    for sep in (" (", " ["):
        idx = name.find(sep)
        if idx != -1:
            name = name[:idx]
    return name.strip()


def tax_rate_to_vat_group(display: str) -> str:
    """PROPOSED/UNVALIDATED (DEBT-1) name-stem -> VatGroup code. Candidate, not a verdict.

    Fails loud (ValueError) on an unmapped tax-rate name rather than silently mis-coding — the
    mapping is unauthored and IRAS citations are deferred, so an unknown name is surfaced, never
    guessed.
    """
    stem = _name_stem(display)
    try:
        return _PROPOSED_VAT_GROUP_MAP[stem]
    except KeyError:
        raise ValueError(
            f"unmapped Xero tax-rate name {display!r} (stem {stem!r}); the PROPOSED VatGroup "
            "mapping is unvalidated (DEBT-1) and refuses to guess an unknown code"
        )


# ---------------------------------------------------------------------------
# ChainReader over the real export.
# ---------------------------------------------------------------------------

# Bucket key (doc_type, doc_kind) per the canonical ENTITY_ROUTING — Xero F5 carries only
# net invoices (credit notes fold into the box totals), so only the invoice buckets fill.
_SALES_INVOICE = ("sales", "invoice")
_PURCHASE_INVOICE = ("purchase", "invoice")

# Which canonical (surface, field) coverage keys this reader populates. The documents-surface
# line + header fields it emits ARE covered; CardCode (no Xero card code), the BP master
# (FederalTaxID) and the whole listing surface are ABSENT — the honest-degrade signal.
_COVERED_FIELDS = frozenset(
    {
        (schema.DOCUMENTS_SHEET, "DocNum"),
        (schema.DOCUMENTS_SHEET, "DocDate"),
        (schema.DOCUMENTS_SHEET, "CardName"),
        (schema.DOCUMENTS_SHEET, "DocCurrency"),
        (schema.DOCUMENTS_SHEET, "VatGroup"),
        (schema.DOCUMENTS_SHEET, "LineTotal"),
        (schema.DOCUMENTS_SHEET, "TaxTotal"),
        (schema.DOCUMENTS_SHEET, "DocTotal"),
    }
)


class XeroF5ChainReader:
    """A ``ChainReader`` backed by a REAL Xero IRAS-F5 "Transactions by box number" export.

    Args:
        source: path to the Xero F5 ``.xlsx`` workbook.

    Each read returns FRESH objects (deepcopy on hand-off), matching ``ExtractChainReader``'s
    per-call freshness.
    """

    def __init__(self, source):
        self._source = Path(source)
        self._docs_by_bucket: dict[tuple, list[dict]] = {
            _SALES_INVOICE: [],
            _PURCHASE_INVOICE: [],
        }
        self._build_documents(_load_transactions(self._source))

    # -- construction --------------------------------------------------------

    def _build_documents(self, transactions: list[dict]) -> None:
        """Turn value-box transaction rows into one-line canonical documents."""
        for txn in transactions:
            display = txn["tax_rate"]
            doc = {
                # Xero references are non-numeric — DocNum carries the reference string; a
                # numeric DocNum/Series surface is absent (SEQ_GAP degrades accordingly).
                "DocNum": txn["reference"],
                "DocDate": txn["date"],
                "CardCode": "",  # no card code in a Xero export
                "CardName": txn["contact"],
                "DocCurrency": txn["currency"],
                "DocTotal": txn["gross"],
                "DocumentLines": [
                    {
                        "VatGroup": tax_rate_to_vat_group(display),
                        "LineTotal": txn["net"],
                        "TaxTotal": txn["tax"],
                    }
                ],
            }
            self._docs_by_bucket[txn["bucket"]].append(doc)

    # -- ChainReader surfaces (structural) -----------------------------------

    def count(self, entity: str, period_start: str, period_end: str) -> Optional[int]:
        """S0 — value-box document count for the entity (the export has every row)."""
        route = schema.ENTITY_ROUTING.get(entity)
        if route is None or route not in self._docs_by_bucket:
            return None
        return len(self._docs_by_bucket[route])

    def fetch_invoices(self, entity: str, period_start: str, period_end: str) -> list:
        """S1 — value-box documents for ``entity`` (Invoices / PurchaseInvoices)."""
        route = schema.ENTITY_ROUTING[entity]
        return copy.deepcopy(self._docs_by_bucket.get(route, []))

    def fetch_credit_notes(self, entity_type: str, period_start: str, period_end: str) -> list:
        """S2 — EMPTY: a Xero F5 export folds credit notes into the box totals (none surfaced)."""
        _ = schema.CREDIT_NOTE_TYPE_ROUTING[entity_type]  # validate the entity_type
        return []

    def get_business_partner(self, card_code: str) -> dict:
        """S3 — a Xero F5 export carries NO supplier master; never fabricate one."""
        raise KeyError(
            f"CardCode {card_code!r}: a Xero F5 export carries no business-partner master "
            "(supply a supplier-master sheet at onboarding)"
        )

    def fetch_listing(self, period: dict) -> dict:
        """S5 — the four canonical listing buckets, all EMPTY (no listing surface in a Xero export)."""
        return {name: [] for name in schema.LISTING_BUCKETS}

    # -- coverage seam (beside the Protocol; NOT part of ChainReader) ---------

    def coverage(self) -> ExtractCoverage:
        """Declare which canonical fields the Xero export carried (header AND value).

        Documents-surface line+header fields are covered; CardCode, the BP master and the whole
        listing surface are absent — the honest-degrade signal the status mapping consumes.
        """
        fields = {key: (key in _COVERED_FIELDS) for key in schema.COVERAGE_FIELDS}
        populated = dict(fields)
        return ExtractCoverage(fields=fields, populated=populated)

    def coverage_status(self) -> list:
        """Map this export's coverage onto per-check status (T2.12 slice 2B + ext-1 + ext-3).

        A Xero F5 export has no company-wide listing surface and no source-document (PDF)
        provider, so both flags are False — NO_GST_REG is unavailable, DUP_CLAIM/SEQ_GAP
        degrade, and the four document-pre-pass checks are unavailable. Emission only; asserts
        no verdict.
        """
        return derive_coverage_statuses(
            self.coverage(),
            company_wide_population_present=False,
            document_pdfs_present=False,
        )


# ---------------------------------------------------------------------------
# Loading — parse the real "Transactions by box number" sheet into value-box
# transaction dicts (Rules 1 & 3). openpyxl is imported lazily here only.
# ---------------------------------------------------------------------------


def _classify_box(header_text: str) -> Optional[str]:
    """Map a box-section header to a bucket key, or None if it is a restatement (tax) box.

    Discrimination is by the "total value of" marker the VALUE boxes carry ("Box 1 - Total
    value of standard-rated supplies", "Box 5 - Total value of taxable purchases ..."). The
    restatement (tax) boxes — "Box 6 - Output tax due", "Box 7 - Less: Input tax ...", "Box 19
    - Add: Deferred import GST payable" — do NOT carry it; they RE-LIST value-box rows and are
    skipped (Rule 3 — no content-hash dedupe). Keying on "total value of" (rather than on the
    restatement keywords directly) avoids misreading Box 5's own descriptive parenthetical
    ("exclude expenses where input tax is disallowed") as a tax box. A value box then routes to
    sales or purchase by its header keywords.
    """
    text = header_text.lower()
    if _VALUE_BOX_MARKER not in text:
        return None  # restatement / tax box (output tax, input tax, deferred import GST)
    if any(kw in text for kw in _PURCHASE_KEYWORDS):
        return _PURCHASE_INVOICE
    if any(kw in text for kw in _SALES_KEYWORDS):
        return _SALES_INVOICE
    return None


def _load_transactions(source: Path) -> list[dict]:
    if source.suffix.lower() != ".xlsx":
        raise ValueError(
            f"unsupported Xero export source {source!r}: expected a .xlsx workbook"
        )
    # Lazy import: keep the module dependency-light until a workbook is actually opened.
    from openpyxl import load_workbook

    wb = load_workbook(source, read_only=True, data_only=True)
    try:
        if TRANSACTIONS_SHEET not in wb.sheetnames:
            raise FileNotFoundError(
                f"Xero export workbook missing sheet {TRANSACTIONS_SHEET!r}"
            )
        ws = wb[TRANSACTIONS_SHEET]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    col = _locate_header(rows)
    transactions: list[dict] = []
    current_bucket: Optional[tuple] = None
    in_restatement = False

    # Rows AFTER the located header row (Rule 1 — the 4-row title block is everything before it).
    for raw in rows[col["_header_row_index"] + 1 :]:
        cells = [schema.ser(c) for c in raw]
        first = _cell(cells, col[_COL_DATE])
        tax_rate = _cell(cells, col[_COL_TAX_RATE])

        if not any(c.strip() for c in cells):
            continue  # blank spacer row
        if first == "Total":
            continue  # box subtotal row
        if tax_rate.strip() == "":
            # A box-section header (single label in the Date column, no tax rate).
            bucket = _classify_box(first)
            in_restatement = bucket is None and _is_box_header(first)
            current_bucket = bucket
            continue

        # A transaction row — belongs to the current box section.
        if in_restatement or current_bucket is None:
            continue  # tax-box re-list (skip) or stray row outside any value box
        transactions.append(
            {
                "reference": _cell(cells, col[_COL_REFERENCE]),
                "date": first,
                "contact": _cell(cells, col[_COL_CONTACT]),
                "tax_rate": _cell(cells, col[_COL_TAX_RATE]),
                "currency": _cell(cells, col[_COL_SOURCE_CURRENCY]),
                "gross": schema.to_float(_cell(cells, col[_COL_GROSS]) or None),
                "net": schema.to_float(_cell(cells, col[_COL_NET]) or None),
                "tax": schema.to_float(_cell(cells, col[_COL_TAX]) or None),
                "bucket": current_bucket,
            }
        )
    return transactions


def _is_box_header(text: str) -> bool:
    """A box/section header line (col-A label with no tax rate)."""
    t = text.strip().lower()
    return t.startswith("box ") or t.startswith("transactions ")


def _locate_header(rows: list[list]) -> dict:
    """Find the header row structurally (carries the marker columns) → name→index map.

    Returns the column-index map plus ``_header_row_index`` so the caller skips the title block.
    """
    for idx, raw in enumerate(rows):
        labels = [schema.ser(c).strip() for c in raw]
        if all(marker in labels for marker in _HEADER_MARKERS):
            col = {label: pos for pos, label in enumerate(labels) if label}
            col["_header_row_index"] = idx
            return col
    raise ValueError(
        f"Xero export header row not found (no row carrying {_HEADER_MARKERS!r})"
    )


def _cell(cells: list[str], index: Optional[int]) -> str:
    """Safe positional cell access (rows may be short); missing → ''."""
    if index is None or index >= len(cells):
        return ""
    return cells[index]


# ---------------------------------------------------------------------------
# Public helpers for the upload seam (T-xero-engine-wire / PR-B): format
# detection + review-period extraction from the export's title block.
# ---------------------------------------------------------------------------

# Title-block line: "For the period Apr 1, 2026 to Jun 30, 2026".
_PERIOD_RE = re.compile(r"for the period\s+(.+?)\s+to\s+(.+?)\s*$", re.IGNORECASE)
# A single human-format date inside that line: "Apr 1, 2026".
_DATE_RE = re.compile(r"([A-Za-z]{3,})\s+(\d{1,2}),?\s+(\d{4})")
# Month-abbreviation → number (locale-independent; strptime %b is locale-sensitive).
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def is_xero_f5_workbook(source) -> bool:
    """True iff the workbook carries the Xero IRAS-F5 "Transactions by box number" sheet.

    The format-routing key for POST /review/upload: a Xero F5 export goes down the engine
    path, any other .xlsx (the synthetic documents/business_partners/listing shape) stays on
    the coverage-only ExtractChainReader path. Any open/parse failure → False (not a Xero
    workbook), so an untrusted/garbage upload falls through to the existing 422 handling.
    """
    path = Path(source)
    if path.suffix.lower() != ".xlsx":
        return False
    try:
        from openpyxl import load_workbook  # lazy

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return TRANSACTIONS_SHEET in wb.sheetnames
        finally:
            wb.close()
    except Exception:  # noqa: BLE001 — an unreadable upload is simply "not a Xero workbook"
        return False


def _iso_date(human: str) -> str:
    """Parse one 'Apr 1, 2026' → '2026-04-01' (locale-independent)."""
    m = _DATE_RE.search(human)
    if m is None:
        raise ValueError(f"unparseable Xero date {human!r}")
    mon = _MONTHS.get(m.group(1)[:3].lower())
    if mon is None:
        raise ValueError(f"unknown month in Xero date {human!r}")
    return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"


def parse_review_period(source) -> dict:
    """Extract {'start','end'} ISO dates from the export's 'For the period … to …' title line.

    Scans the "Transactions by box number" sheet's title block. Raises ValueError if the line
    is absent or unparseable (the caller surfaces this as a 422 client-input error, never a 500).
    """
    from openpyxl import load_workbook  # lazy

    wb = load_workbook(Path(source), read_only=True, data_only=True)
    try:
        ws = wb[TRANSACTIONS_SHEET]
        for raw in ws.iter_rows(min_row=1, max_row=8, values_only=True):
            for cell in raw:
                text = schema.ser(cell).strip()
                m = _PERIOD_RE.match(text)
                if m:
                    return {"start": _iso_date(m.group(1)), "end": _iso_date(m.group(2))}
    finally:
        wb.close()
    raise ValueError(
        f"Xero export missing a 'For the period … to …' line on sheet {TRANSACTIONS_SHEET!r}"
    )
