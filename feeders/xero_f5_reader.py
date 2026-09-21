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
from feeders.xero_contacts import (
    AMBIGUOUS,
    MISSING,
    NAMELESS,
    UNIQUE,
    ContactsJoin,
    load_contacts,
)

# The sheet the real Xero IRAS-F5 export carries the period transactions on.
TRANSACTIONS_SHEET = "Transactions by box number"

# Real-export header column labels (row 5). Located structurally via _HEADER_MARKERS.
_COL_DATE = "Date"
_COL_ACCOUNT = "Account"
_COL_REFERENCE = "Reference"
_COL_CONTACT = "Contact"
_COL_DESCRIPTION = "Description"
_COL_TAX_RATE = "Tax rate"
_COL_SOURCE_CURRENCY = "Source currency"
_COL_GROSS = "Gross"
_COL_NET = "Net"
_COL_TAX = "Tax"
# Two markers whose joint presence identifies the header row (so the 4-row title block is
# skipped structurally, not by a hard-coded offset). _COL_ACCOUNT / _COL_DESCRIPTION are read
# only by the T2.24 parse_not_included path (the value-box loader ignores them).
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
def _safe_tax(value) -> float:
    """Coerce a line's TaxTotal to a float; anything uncoercible reads as 0.00.

    Mirrors ``sap_b1_server._safe_float``'s posture at the one place this reader needs it
    (counting INPUT-TAX lines for the contacts-join denominator) so the denominator can
    never differ from the set of documents the check actually walks.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
    #: T-E(2)/D-40 — (matched, total) document join, set by the api layer when the
    #: review session carries uploaded source documents; None = no document surface.
    document_join: "tuple[int, int] | None" = None

    """A ``ChainReader`` backed by a REAL Xero IRAS-F5 "Transactions by box number" export.

    Args:
        source: path to the Xero F5 ``.xlsx`` workbook.

    Each read returns FRESH objects (deepcopy on hand-off), matching ``ExtractChainReader``'s
    per-call freshness.
    """

    def __init__(self, source, contacts=None):
        """``contacts`` — an OPTIONAL Xero Contacts export (the supplier master).

        D-2026-09-20-slice-c-contacts-no-gst-reg. Absent (the default), this reader is
        BYTE-IDENTICAL to before in every surface it exposes: no CardCode, no BP master,
        NO_GST_REG still unavailable. Supplied, the purchase documents gain a CardCode for
        every supplier that resolves to exactly one contact, and the BP surface answers
        from that contact's TaxNumber.
        """
        self._source = Path(source)
        self._contacts = load_contacts(contacts) if contacts is not None else None
        #: Per-state counts over the INPUT-TAX purchase lines (R3's denominator).
        self._join_counts: dict[str, int] = {}
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
            # Slice C: the contacts join is PURCHASE-SIDE ONLY — NO_GST_REG reads purchase
            # invoices and purchase credit notes, so a sales document keeps CardCode "" and
            # nothing on the sales side of the chain sees any change.
            if self._contacts is not None and txn["bucket"] == _PURCHASE_INVOICE:
                self._join_contact(doc)
            self._docs_by_bucket[txn["bucket"]].append(doc)

    def _join_contact(self, doc: dict) -> None:
        """Resolve ONE purchase document's counterparty against the Contacts export.

        A UNIQUE match sets ``CardCode`` to the CONTACT's own spelling of the name (so two
        spellings of one supplier dedupe to one finding), which is also the key the BP
        surface resolves back through the SAME index — one source of truth. MISSING / AMBIGUOUS / NAMELESS leave ``CardCode`` empty, which is
        exactly how ``detect_gst_errors`` SKIPS a document — not examined, never a finding
        (R2). Every state is counted, but only over INPUT-TAX lines: a purchase carrying no
        input tax was never in scope for this check, so it belongs in no denominator.
        """
        state, _tax_number = self._contacts.match(doc.get("CardName"))
        if state == UNIQUE:
            card_code = self._contacts.canonical_name(doc.get("CardName"))
            if card_code:
                doc["CardCode"] = card_code
        has_input_tax = any(
            _safe_tax(line.get("TaxTotal")) > 0.01 for line in doc.get("DocumentLines", [])
        )
        if has_input_tax:
            self._join_counts[state] = self._join_counts.get(state, 0) + 1

    @property
    def contacts_join(self) -> "ContactsJoin | None":
        """The join summary, or None when no Contacts export was supplied.

        None is the signal that the check could not run at all; a ContactsJoin is the
        signal that it ran, over ``examined`` of ``total`` input-tax purchase lines.
        """
        if self._contacts is None:
            return None
        # Keyed by the IMPORTED constants, never by bare literals: the counts are what
        # the coverage degrade reports, so a rename in xero_contacts.py must break loudly
        # here rather than silently zero them and report a full examination.
        return ContactsJoin(
            examined=self._join_counts.get(UNIQUE, 0),
            missing=self._join_counts.get(MISSING, 0),
            ambiguous=self._join_counts.get(AMBIGUOUS, 0),
            nameless=self._join_counts.get(NAMELESS, 0),
        )

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
        """S3 — the supplier master, IF a Contacts export was supplied.

        Slice C: a Xero F5 export alone carries no supplier master, and this still refuses
        to fabricate one. With a Contacts export the answer comes from that export and
        nowhere else: ``FederalTaxID`` is the contact's ``TaxNumber`` VERBATIM (canonical
        field name, Xero value — no translation, no validation, R1). A CardCode that did
        not resolve to exactly one contact was never written onto a document, so reaching
        here with one is a genuine KeyError. The lookup goes through the SAME index the
        join used, so the answer cannot drift from the CardCode the documents carry, and a
        contact with no transaction in the period is still a legitimate supplier-master
        record rather than a KeyError.
        """
        if self._contacts is not None:
            state, tax_number = self._contacts.match(card_code)
            if state == UNIQUE:
                canonical = self._contacts.canonical_name(card_code)
                return {
                    "CardCode": canonical,
                    "CardName": canonical,
                    "FederalTaxID": tax_number or "",
                }
        raise KeyError(
            f"CardCode {card_code!r}: a Xero F5 export carries no business-partner master "
            "(supply a supplier-master sheet at onboarding)"
        )

    def fetch_listing(self, period: dict) -> dict:
        """S5 — the four canonical listing buckets, all EMPTY (no listing surface in a Xero export)."""
        return {name: [] for name in schema.LISTING_BUCKETS}

    # -- coverage seam (beside the Protocol; NOT part of ChainReader) ---------

    def _observed_populated_keys(self) -> frozenset:
        """The (surface, field) keys that carried >=1 non-empty value — OBSERVED.

        D-2026-07-27-xero-coverage-derived: population is observed from the data,
        never asserted by fiat — a present-but-empty column is NOT populated. The
        cell predicate mirrors ``ExtractCoverage``'s exactly
        (``extract_reader._compute_populated_columns``): a value counts as populated
        when it is not None and stringifies to a non-blank string.
        """
        seen: set = set()
        for docs in self._docs_by_bucket.values():
            for doc in docs:
                for field in ("DocNum", "DocDate", "CardName", "DocCurrency", "DocTotal"):
                    value = doc.get(field)
                    if value is not None and str(value).strip() != "":
                        seen.add((schema.DOCUMENTS_SHEET, field))
                for line in doc.get("DocumentLines", []):
                    for field in ("VatGroup", "LineTotal", "TaxTotal"):
                        value = line.get(field)
                        if value is not None and str(value).strip() != "":
                            seen.add((schema.DOCUMENTS_SHEET, field))
        # Slice C: the supplied Contacts export IS the business-partner surface, and the
        # SAME observed-population predicate applies to it — a TaxNumber column that is
        # present but 0%-populated is NOT populated, so the check reads unavailable rather
        # than flagging every supplier off an empty column.
        if self._contacts is not None and self._contacts.has_tax_number_population():
            seen.add((schema.BUSINESS_PARTNERS_SHEET, "FederalTaxID"))
        return frozenset(seen)

    def coverage(self) -> ExtractCoverage:
        """Declare which canonical fields the Xero export carried (header AND value).

        Documents-surface line+header fields are covered; CardCode, the BP master and the whole
        listing surface are absent — the honest-degrade signal the status mapping consumes.

        D-2026-07-27-xero-coverage-derived: ``fields`` (header/format presence) stays
        CONSTANT-driven — presence is a FORMAT fact for this reader. ``populated`` is
        now OBSERVED from the loaded documents (previously ``dict(fields)`` — asserted
        by fiat), so a present-but-all-empty column reads NOT populated and
        ``is_covered`` degrades honestly, exactly as the extract reader has always
        behaved.

        D-2026-09-20-slice-c-contacts-no-gst-reg SUPERSEDES the sentence that stood here
        ("FederalTaxID stays outside the covered set: NO_GST_REG remains unavailable on
        this reader and this change makes nothing newly runnable"). That was true while
        this reader had no supplier-master surface at all. It now has one WHEN AND ONLY
        WHEN a Contacts export was supplied: ``_covered_field_keys()`` adds
        (business_partners, FederalTaxID) for THIS INSTANCE, and the population predicate
        above still governs — a 0%-populated TaxNumber column is not covered. With no
        Contacts export the covered set is the module constant, unchanged, and NO_GST_REG
        is still unavailable on this reader.
        """
        fields = {key: (key in self._covered_field_keys()) for key in schema.COVERAGE_FIELDS}
        observed = self._observed_populated_keys()
        populated = {key: (fields[key] and key in observed) for key in schema.COVERAGE_FIELDS}
        return ExtractCoverage(fields=fields, populated=populated)

    def _covered_field_keys(self) -> frozenset:
        """Which (surface, field) keys THIS READER INSTANCE carried a column for.

        Ruling 3 (Slice C): the business-partner surface is declared PER INSTANCE, and
        ONLY when a Contacts export was supplied. The module-level ``_COVERED_FIELDS``
        constant is deliberately NOT widened — widening it would make every reader,
        including one constructed over an F5 export alone, claim a supplier master it does
        not have, and D2 (no contacts → byte-identical) would be false.
        """
        if self._contacts is None:
            return _COVERED_FIELDS
        return _COVERED_FIELDS | {(schema.BUSINESS_PARTNERS_SHEET, "FederalTaxID")}

    def populatable_sides(self) -> frozenset:
        """Which F5 SIDES this FORMAT can populate — a capability fact, never a content fact.

        The "Transactions by box number" export structurally carries BOTH value-box
        sections (Box 1-4 supplies AND Box 5 purchases/imports), so both sides are
        declarable even when a period happens to contain no purchase rows — capability,
        not emptiness, drives the render marker (open item #48): a genuinely-zero box on
        this format renders its 0.00 figure, never an unavailable marker.
        """
        return frozenset({"sales", "purchase"})

    def coverage_status(self) -> list:
        """Map this export's coverage onto per-check status (T2.12 slice 2B + ext-1 + ext-3).

        A Xero F5 export has no company-wide listing surface and no source-document (PDF)
        provider, so both flags are False — NO_GST_REG is unavailable, DUP_CLAIM/SEQ_GAP
        degrade, and the four document-pre-pass checks are unavailable. Emission only; asserts
        no verdict.
        """
        # T-E(2)/D-40: the api layer sets document_join = (matched, total), COMPUTED
        # from the actual reference join against the review's uploaded documents. The
        # SAME reader instance feeds both the response's coverage rows and the signed
        # paper's (engine review reads it), so screen and paper cannot diverge. None
        # (the default) is byte-identical to the pre-T-E(2) False.
        return derive_coverage_statuses(
            self.coverage(),
            company_wide_population_present=False,
            document_pdfs_present=(
                self.document_join if self.document_join is not None else False
            ),
            # Slice C / ruling 3: the join summary travels as DATA (the document_join
            # precedent, D-40). None — no Contacts export — is byte-identical to before.
            contacts_join=self.contacts_join,
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


# ---------------------------------------------------------------------------
# T2.24 PR-2 — ADDITIVE readers over the F5 workbook (declared boxes + the
# "Transactions not included" drop surface). These do NOT touch _load_transactions
# or XeroF5ChainReader — the value-box path stays byte-identical. openpyxl lazy.
# ---------------------------------------------------------------------------

# The 'Return' sheet lays out one box per row: col A = "Box N", col C = value.
RETURN_SHEET = "Return"
# Declared boxes T2.24 reconciles the 820 ledger against — keyed to the gst_ledger
# ["declared_boxes"] seam contract (output_tax = Box 6, input_tax = Box 7).
_DECLARED_BOX_LABELS = {"Box 6": "output_tax", "Box 7": "input_tax"}
_RETURN_VALUE_COL = 2  # col C

# The section header (col A) for postings Xero EXCLUDES from every F5 box.
NOT_INCLUDED_HEADER = "Transactions not included"


def parse_declared_return(source) -> dict:
    """Read the DECLARED F5 Box 6 (output tax) / Box 7 (input tax) VALUES off the 'Return' sheet.

    Returns ``{"output_tax": <Box 6>, "input_tax": <Box 7>}`` — the EXACT key shape the T2.24
    ``gst_ledger["declared_boxes"]`` seam consumes, so it drops in with no mapping shim. Located
    by structural label scan (col A == "Box N", value in col C); NO fixed header offset. Reads
    VALUES only — classifies nothing and encodes no tax rule. Raises ValueError if the 'Return'
    sheet or either box row is absent / non-numeric (an honest client-input failure, never a
    silent partial dict).
    """
    path = Path(source)
    from openpyxl import load_workbook  # lazy

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if RETURN_SHEET not in wb.sheetnames:
            raise ValueError(
                f"Xero F5 workbook missing sheet {RETURN_SHEET!r}; cannot read declared boxes"
            )
        ws = wb[RETURN_SHEET]
        found: dict = {}
        for raw in ws.iter_rows(values_only=True):
            label = schema.ser(raw[0] if raw else None).strip()
            key = _DECLARED_BOX_LABELS.get(label)
            if key is None:
                continue
            cell = raw[_RETURN_VALUE_COL] if len(raw) > _RETURN_VALUE_COL else None
            value = schema.to_float(schema.ser(cell) or None)
            if value is None:
                raise ValueError(
                    f"{label!r} on the {RETURN_SHEET!r} sheet carries no numeric value (got {cell!r})"
                )
            found[key] = value
    finally:
        wb.close()

    missing = [label for label, key in _DECLARED_BOX_LABELS.items() if key not in found]
    if missing:
        raise ValueError(
            f"{RETURN_SHEET!r} sheet missing required declared-box row(s): {missing}"
        )
    return found


def parse_not_included(source) -> list:
    """Read the 'Transactions not included' section of the 'Transactions by box number' sheet.

    Returns one dict per row — ``{account, reference, description, tax_rate, gross, net, tax}``.
    These are the postings Xero EXCLUDES from every F5 box (e.g. a raw-GL manual journal posted
    to the GST control account with no tax code). The value-box loader (``_load_transactions``)
    skips this section entirely; this reader is ADDITIVE and reads the ``Account`` column that
    loop ignores. Reads values only — interprets no tax code. Raises ValueError if the sheet or
    the not-included section header is absent.
    """
    path = Path(source)
    if path.suffix.lower() != ".xlsx":
        raise ValueError(f"unsupported Xero export source {path!r}: expected a .xlsx workbook")
    from openpyxl import load_workbook  # lazy

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if TRANSACTIONS_SHEET not in wb.sheetnames:
            raise ValueError(f"Xero F5 workbook missing sheet {TRANSACTIONS_SHEET!r}")
        ws = wb[TRANSACTIONS_SHEET]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    col = _locate_header(rows)  # reuse the value-box sheet's structural header locate

    # Find the "Transactions not included" section header (a col-A label with no tax rate).
    start = None
    for idx in range(col["_header_row_index"] + 1, len(rows)):
        cells = [schema.ser(c) for c in rows[idx]]
        if _cell(cells, col.get(_COL_DATE)).strip() == NOT_INCLUDED_HEADER:
            start = idx + 1
            break
    if start is None:
        raise ValueError(
            f"Xero F5 workbook has no {NOT_INCLUDED_HEADER!r} section on sheet {TRANSACTIONS_SHEET!r}"
        )

    out: list = []
    for raw in rows[start:]:
        cells = [schema.ser(c) for c in raw]
        if not any(c.strip() for c in cells):
            continue  # blank spacer row
        first = _cell(cells, col.get(_COL_DATE)).strip()
        if first == "Total":
            continue  # subtotal row
        if _is_box_header(first):
            break  # a following box/section header ends the not-included section
        out.append({
            "account": _cell(cells, col.get(_COL_ACCOUNT)).strip(),
            "reference": _cell(cells, col.get(_COL_REFERENCE)).strip(),
            "description": _cell(cells, col.get(_COL_DESCRIPTION)).strip(),
            "tax_rate": _cell(cells, col.get(_COL_TAX_RATE)).strip(),
            "gross": schema.to_float(_cell(cells, col.get(_COL_GROSS)) or None) or 0.0,
            "net": schema.to_float(_cell(cells, col.get(_COL_NET)) or None) or 0.0,
            "tax": schema.to_float(_cell(cells, col.get(_COL_TAX)) or None) or 0.0,
        })
    return out
