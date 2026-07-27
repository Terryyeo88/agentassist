"""feeders/xero_sales_reader.py — XeroSalesInvoiceChainReader: a ChainReader over an inbound
Xero SALES-INVOICE export (the flat, one-row-per-invoice-line sheet).

Emits the SAME shaped record lists/dicts the deterministic checking core consumes from the
live-SAP feeder — the identical structural ``ChainReader`` contract ``ExtractChainReader`` /
``XeroF5ChainReader`` satisfy (T2.23), neither importing nor widening the Protocol:

    count(entity, period_start, period_end)            -> Optional[int]
    fetch_invoices(entity, period_start, period_end)   -> list[dict]
    fetch_credit_notes(entity_type, ps, pe)            -> list[dict]
    get_business_partner(card_code)                    -> dict
    fetch_listing(period)                              -> dict   (4 buckets)

It exists ALONGSIDE ``XeroF5ChainReader`` (the "Transactions by box number" F5 export) and
``ExtractChainReader`` (the synthetic documents/business_partners/listing shape) — it does NOT
edit or branch either, so those paths stay byte-identical.

THREE THINGS THIS READER DOES (each pinned in tests/test_xero_sales_feeder.py — three-times rule):

  1. GROUP BY InvoiceNumber. The export is one row per invoice LINE; a multi-line invoice repeats
     InvoiceNumber. Rows are grouped (first-seen order) into one canonical sales-invoice document
     with an ordered ``DocumentLines`` list and a synthesized per-line index.

  2. MAP TaxType -> VatGroup VIA THE CLIENT YAML. The Xero ``TaxType`` string is resolved to a
     canonical VatGroup through the ``tax_code_mappings`` PASSED IN from the client config — NEVER
     a table hardcoded in this reader (no repeat of xero_f5_reader.py's DEBT-1). A code that is in
     the client's ``out_of_scope_codes`` is ACCEPTED but set aside from GST categorisation (its
     line is dropped from ``DocumentLines`` and counted for the visible out-of-scope note). A code
     in NEITHER mapping NOR out-of-scope fails LOUD (ValueError naming it) rather than silently
     mis-coding or passing through.

  3. DEGRADE ABSENT SURFACES HONESTLY. A sales-invoice export carries NO supplier master, NO
     document-number listing, NO credit notes and NO purchase side, so:
       * ``get_business_partner`` raises KeyError,
       * ``fetch_credit_notes`` / the purchase buckets / ``fetch_listing`` are EMPTY,
       * ``coverage_status`` degrades the BP/listing/document-dependent checks through the SAME
         ``derive_coverage_statuses`` seam the other readers use (NO_GST_REG unavailable,
         DUP_CLAIM/SEQ_GAP degraded). Xero references are non-numeric, so DocNum carries the
         InvoiceNumber string and CardCode is empty (the XeroF5 treatment).

HONEST STATUS (T2.11): real-Xero-FORMAT parsing over SYNTHETIC content. NOT a real client export
(the exact real column-header set / TaxType vocabulary still need pinning against a genuine
export); NOT accuracy-validated. The mapping is Terry-authored against IRAS Annex E and lives in
the client YAML — this reader is the mechanism, never the authority.

line_description emit is real-FORMAT over synthetic Xero, NOT real-client-validated; field is
INERT until the Prompt E adapter wires sales_line_source — the exempt skill does NOT run on
Xero yet.

Pure stdlib; openpyxl is imported lazily only on the .xlsx path. No SAP, no anthropic. Imports
only feeders siblings + stdlib (feeders stays a leaf).
"""
from __future__ import annotations

import copy
import csv
from pathlib import Path
from typing import Optional

from feeders import extract_schema as schema
from feeders.coverage_status import derive_coverage_statuses
from feeders.extract_reader import ExtractCoverage

# The single flat sheet is identified structurally by these two marker columns (mirrors
# xero_f5_reader's header-marker approach) — distinct from the F5 "Transactions by box number"
# sheet and from the three-sheet extract shape, so the router can tell the three apart.
_COL_CONTACT = "ContactName"
_COL_INVOICE_NUMBER = "InvoiceNumber"
_COL_INVOICE_DATE = "InvoiceDate"
# Per-line narrative (Prompt D): emitted as line_description so the Prompt-E adapter is a
# straight passthrough into the reasoning contract. Optional — absent/blank column → "".
_COL_DESCRIPTION = "Description"
_COL_TAX_TYPE = "TaxType"
_COL_TAX_AMOUNT = "TaxAmount"
_COL_LINE_AMOUNT = "LineAmount"
_COL_CURRENCY = "Currency"
_COL_TOTAL = "Total"
_HEADER_MARKERS = (_COL_INVOICE_NUMBER, _COL_TAX_TYPE)

# This reader fills only the sales-invoice bucket; the purchase / credit-note buckets stay empty
# (a sales-invoice export carries neither).
_SALES_INVOICE = ("sales", "invoice")

# Which canonical (surface, field) coverage keys this reader populates — the documents-surface
# line + header fields it emits ARE covered; CardCode (no Xero card code), the BP master
# (FederalTaxID) and the whole listing surface are ABSENT (the honest-degrade signal). Same set
# as xero_f5_reader — a Xero export has no card code.
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


class XeroSalesInvoiceChainReader:
    """A ``ChainReader`` backed by an inbound Xero SALES-INVOICE export (CSV file or .xlsx).

    Args:
        source: path to the Xero sales-invoice export — a single ``.csv`` file OR a single
                ``.xlsx`` workbook whose sheet carries the ``InvoiceNumber`` + ``TaxType`` columns.
        tax_code_mappings: source tax code (UPPER) -> canonical VatGroup, from the client config
                (``ClientConfig.effective_tax_code_mappings``). The AUTHORITY for TaxType coding —
                this reader holds no table of its own.
        out_of_scope_codes: iterable of source tax codes (any case) that are ACCEPTED but set
                aside from GST categorisation (from ``ClientConfig.out_of_scope_codes``).

    Each read returns FRESH objects (deepcopy on hand-off), matching the other readers' per-call
    freshness.
    """

    def __init__(self, source, *, tax_code_mappings, out_of_scope_codes):
        self._source = Path(source)
        self._mappings = {str(k).strip().upper(): v for k, v in dict(tax_code_mappings).items()}
        self._out_of_scope = frozenset(str(c).strip().upper() for c in out_of_scope_codes)
        # Out-of-scope tally (code -> count), populated during the build.
        self._oos_counts: dict[str, int] = {}
        self._docs_by_bucket: dict[tuple, list[dict]] = {_SALES_INVOICE: []}
        self._build_documents(_load_rows(self._source))

    # -- construction --------------------------------------------------------

    def _resolve_vat_group(self, tax_type: str) -> Optional[str]:
        """Resolve one Xero ``TaxType`` to a canonical VatGroup, or None if out-of-scope.

        Mapped -> the canonical code (from the injected client mapping). Out-of-scope -> None
        (line set aside, tallied). Neither -> ValueError naming the code (fail loud, never silent).
        """
        code = (tax_type or "").strip().upper()
        if code in self._mappings:
            return self._mappings[code]
        if code in self._out_of_scope:
            self._oos_counts[code] = self._oos_counts.get(code, 0) + 1
            return None
        raise ValueError(
            f"unmapped Xero TaxType {tax_type!r} (normalised {code!r}) — it is in neither "
            f"tax_code_mappings nor out_of_scope_codes for this client. The mapping is "
            f"Terry-authored (IRAS Annex E); an unknown code is surfaced, never guessed. "
            f"(13 codes are PARKED pending T2.21 vocabulary resumption.)"
        )

    def _build_documents(self, rows: list[dict]) -> None:
        """Group flat line rows by InvoiceNumber into canonical sales-invoice documents."""
        # InvoiceNumber -> {"header": {...}, "lines": [line, ...]}  (first-seen order preserved)
        grouped: dict[str, dict] = {}
        order: list[str] = []
        for row in rows:
            invnum = schema.to_str(row.get(_COL_INVOICE_NUMBER)).strip()
            entry = grouped.get(invnum)
            if entry is None:
                entry = {
                    "header": {
                        # Xero InvoiceNumber is non-numeric — carry it as a STRING (the XeroF5
                        # treatment); a numeric DocNum/Series surface is absent (SEQ_GAP degrades).
                        "DocNum": invnum,
                        "DocDate": schema.to_str(row.get(_COL_INVOICE_DATE)),
                        "CardCode": "",  # no card code in a Xero export
                        "CardName": schema.to_str(row.get(_COL_CONTACT)),
                        "DocCurrency": schema.to_str(row.get(_COL_CURRENCY)),
                        # Invoice-level gross total (repeats on every line row → taken once here).
                        "DocTotal": schema.to_float(row.get(_COL_TOTAL)),
                    },
                    "lines": [],
                }
                grouped[invnum] = entry
                order.append(invnum)
            vat_group = self._resolve_vat_group(schema.to_str(row.get(_COL_TAX_TYPE)))
            if vat_group is None:
                # Out-of-scope: accepted, tallied in _resolve_vat_group, and set aside from
                # GST categorisation (never added to DocumentLines).
                continue
            entry["lines"].append(
                {
                    "VatGroup": vat_group,
                    "LineTotal": schema.to_float(row.get(_COL_LINE_AMOUNT)),
                    "TaxTotal": schema.to_float(row.get(_COL_TAX_AMOUNT)),
                    # Prompt D: the export's per-line Description, verbatim, under the
                    # reasoning-contract key name (Prompt-E adapter = straight passthrough).
                    # Tolerant: absent/blank column -> "". INERT for boxes/gates —
                    # calculate_f5_return reads only the three fixed keys above — and
                    # unconsumed until the Prompt-E adapter wires sales_line_source.
                    "line_description": schema.to_str(row.get(_COL_DESCRIPTION)).strip(),
                }
            )

        for invnum in order:
            entry = grouped[invnum]
            doc = dict(entry["header"])
            # line_index is synthesized by first-seen row order within the invoice.
            doc["DocumentLines"] = list(entry["lines"])
            self._docs_by_bucket[_SALES_INVOICE].append(doc)

    # -- ChainReader surfaces (structural) -----------------------------------

    def count(self, entity: str, period_start: str, period_end: str) -> Optional[int]:
        """S0 — grouped sales-invoice count (the export has every row); other entities → 0/None."""
        route = schema.ENTITY_ROUTING.get(entity)
        if route is None:
            return None
        return len(self._docs_by_bucket.get(route, []))

    def fetch_invoices(self, entity: str, period_start: str, period_end: str) -> list:
        """S1 — grouped documents for ``entity``; only ``Invoices`` (sales) fills, else empty."""
        route = schema.ENTITY_ROUTING[entity]
        return copy.deepcopy(self._docs_by_bucket.get(route, []))

    def fetch_credit_notes(self, entity_type: str, period_start: str, period_end: str) -> list:
        """S2 — EMPTY: a sales-invoice export carries no credit notes."""
        _ = schema.CREDIT_NOTE_TYPE_ROUTING[entity_type]  # validate the entity_type
        return []

    def get_business_partner(self, card_code: str) -> dict:
        """S3 — a sales-invoice export carries NO supplier master; never fabricate one."""
        raise KeyError(
            f"CardCode {card_code!r}: a Xero sales-invoice export carries no business-partner "
            f"master (supply a supplier-master sheet at onboarding)"
        )

    def fetch_listing(self, period: dict) -> dict:
        """S5 — the four canonical listing buckets, all EMPTY (no listing surface in the export)."""
        return {name: [] for name in schema.LISTING_BUCKETS}

    # -- out-of-scope note + coverage seam (beside the Protocol) --------------

    def out_of_scope_summary(self) -> dict:
        """The out-of-scope-lines note: {count, by_code, reason}. Visible, never silent.

        ``by_code`` maps each out-of-scope TaxType (uppercased) to how many lines carried it;
        ``reason`` states the coverage FACT (accepted, set aside from GST categorisation — NOT a
        deficiency). ``count`` 0 → an empty reason (nothing to surface).
        """
        total = sum(self._oos_counts.values())
        if total == 0:
            return {"count": 0, "by_code": {}, "reason": ""}
        codes = ", ".join(sorted(self._oos_counts))
        reason = (
            f"{total} line(s) carried an out-of-scope TaxType ({codes}) — ACCEPTED and set aside "
            f"from GST categorisation (a data-coverage fact, not a compliance verdict)."
        )
        return {"count": total, "by_code": dict(self._oos_counts), "reason": reason}

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
        return frozenset(seen)

    def coverage(self) -> ExtractCoverage:
        """Declare which canonical fields the export carried (header AND value).

        Documents-surface line+header fields are covered; CardCode, the BP master and the whole
        listing surface are absent — the honest-degrade signal the status mapping consumes.

        D-2026-07-27-xero-coverage-derived: ``fields`` (header/format presence) stays
        CONSTANT-driven — presence is a FORMAT fact for this reader. ``populated`` is
        now OBSERVED from the loaded documents (previously ``dict(fields)`` — asserted
        by fiat), so a present-but-all-empty column reads NOT populated and
        ``is_covered`` degrades honestly, exactly as the extract reader has always
        behaved. FederalTaxID stays outside the covered set: NO_GST_REG remains
        unavailable on this reader and this change makes nothing newly runnable.
        """
        fields = {key: (key in _COVERED_FIELDS) for key in schema.COVERAGE_FIELDS}
        observed = self._observed_populated_keys()
        populated = {key: (fields[key] and key in observed) for key in schema.COVERAGE_FIELDS}
        return ExtractCoverage(fields=fields, populated=populated)

    def populatable_sides(self) -> frozenset:
        """Which F5 SIDES this FORMAT can populate — a capability fact, never a content fact.

        A Xero sales-invoice export carries sales documents ONLY: no purchase surface
        exists in the format, so a purchase-side box is STRUCTURALLY UNKNOWABLE from it
        (open item #48 — the paper must never state a figure the source could not
        support). Declared beside ``coverage_status()`` (the same duck-typed honest-
        degrade seam family); the chain projects sides → per-box status and the report
        layer renders unavailable boxes as a marker, never a fabricated 0.00.
        """
        return frozenset({"sales"})

    def coverage_status(self) -> list:
        """Map this export's coverage onto per-check status (the EXISTING 2B + ext-1 + ext-3 seam).

        A Xero sales-invoice export has no company-wide listing surface and no source-document
        (PDF) provider, so both flags are False — NO_GST_REG is unavailable, DUP_CLAIM/SEQ_GAP
        degrade, and the four document-pre-pass checks are unavailable. Byte-identical seam usage
        to xero_f5_reader. Emission only; asserts no verdict. (The out-of-scope-lines note is a
        separate, visible surface — see ``out_of_scope_summary``.)
        """
        return derive_coverage_statuses(
            self.coverage(),
            company_wide_population_present=False,
            document_pdfs_present=False,
        )


# ---------------------------------------------------------------------------
# Loading — a single flat CSV file OR a single .xlsx sheet. Returns list[row-dict].
# ---------------------------------------------------------------------------


def _load_rows(source: Path) -> list[dict]:
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return _load_csv(source)
    if suffix == ".xlsx":
        return _load_xlsx(source)
    raise ValueError(
        f"unsupported Xero sales-invoice source {source!r}: expected a .csv or .xlsx file"
    )


def _load_csv(source: Path) -> list[dict]:
    with source.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or [])
        _require_markers(header, source)
        return [dict(row) for row in reader]


def _load_xlsx(source: Path) -> list[dict]:
    # Lazy import: keep the module dependency-light until a workbook is actually opened.
    from openpyxl import load_workbook

    wb = load_workbook(source, read_only=True, data_only=True)
    try:
        sheet = _locate_sheet(wb)
        if sheet is None:
            raise ValueError(
                f"Xero sales-invoice sheet not found in {source!r} "
                f"(no sheet carrying {_HEADER_MARKERS!r})"
            )
        ws = wb[sheet]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = [("" if h is None else str(h)) for h in next(rows_iter)]
        except StopIteration:
            header = []
        _require_markers(set(header), source)
        records: list[dict] = []
        for raw in rows_iter:
            if all(cell is None for cell in raw):
                continue
            records.append(
                {col: schema.ser(raw[i]) if i < len(raw) else "" for i, col in enumerate(header)}
            )
        return records
    finally:
        wb.close()


def _locate_sheet(wb) -> Optional[str]:
    """The first sheet whose row-1 header carries both marker columns, or None."""
    for name in wb.sheetnames:
        ws = wb[name]
        first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        labels = {("" if c is None else str(c)).strip() for c in first}
        if all(marker in labels for marker in _HEADER_MARKERS):
            return name
    return None


def _require_markers(header: set, source: Path) -> None:
    missing = [m for m in _HEADER_MARKERS if m not in header]
    if missing:
        raise ValueError(
            f"Xero sales-invoice export {source!r} missing required column(s) {missing} "
            f"(need {list(_HEADER_MARKERS)})"
        )


# ---------------------------------------------------------------------------
# Format detection for the upload router (mirrors xero_f5_reader.is_xero_f5_workbook).
# ---------------------------------------------------------------------------


def is_xero_sales_invoice_workbook(source) -> bool:
    """True iff ``source`` is a .xlsx carrying a Xero sales-invoice sheet (InvoiceNumber + TaxType).

    The router key for POST /review/upload: checked AFTER ``is_xero_f5_workbook`` (F5 keeps
    precedence) and BEFORE the ExtractChainReader fallback. Any open/parse failure → False (not a
    Xero sales-invoice workbook), so an untrusted/garbage upload falls through to the existing
    handling rather than raising here.
    """
    path = Path(source)
    if path.suffix.lower() != ".xlsx":
        return False
    try:
        from openpyxl import load_workbook  # lazy

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return _locate_sheet(wb) is not None
        finally:
            wb.close()
    except Exception:  # noqa: BLE001 — an unreadable upload is simply "not this format"
        return False
