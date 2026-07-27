"""tests/test_xero_coverage_derived.py -- D-2026-07-27-xero-coverage-derived FAILING-FIRST.

BUILD ID: t-xero-coverage-derived. Written BEFORE the implementation exists; the red
tests here MUST fail today for the RIGHT reason (population asserted by fiat), then pass
once the build lands.

THE INVARIANT (three-times rule -- prompt + code + THIS file): Xero coverage population
is OBSERVED from the data, never asserted by fiat; a present-but-empty column is NOT
populated.

WHAT IS CHANGING. Both Xero readers today build their coverage seam as::

    fields    = {key: (key in _COVERED_FIELDS) for key in schema.COVERAGE_FIELDS}
    populated = dict(fields)                     # <-- BY FIAT: "present implies populated"

``populated`` is a copy of ``fields``, so a column that the format carries but that is
EMPTY in every row still reads as populated. The build makes ``populated`` OBSERVED over
the reader's own canonical documents using ExtractCoverage's exact cell predicate
(``value is not None and str(value).strip() != ""`` -- see
feeders/extract_reader.py::_compute_populated_columns), so the two Xero readers measure
population the same way the extract reader already does.

WHAT IS **NOT** CHANGING (pinned by the guard tests below):
  * ``fields`` stays CONSTANT-driven -- it is a FORMAT fact (which columns this export
    shape carries), not a content fact. is_present() is unchanged.
  * FederalTaxID stays uncovered; NO_GST_REG stays "unavailable" with the SAME reason.
  * On the COMMITTED fixtures every one of the 11 coverage rows stays byte-identical --
    fiat and observed agree there, so NOTHING a reviewer reads changes.
  * populatable_sides() (the locked F3 sweep's requirement) is untouched.

WHY THE RED TESTS USE CONSTRUCTED FIXTURES. A measurement run over the committed
fixtures showed fiat == observed on EVERY field, and all 11 coverage rows byte-identical.
A committed-fixture test therefore CANNOT go red, so the failing tests build their own
workbook / CSV variants in ``tmp_path`` with a present-but-all-empty column. The
COMMITTED FIXTURES ARE NEVER EDITED by this file -- they are opened read-only, and every
constructed variant is written under ``tmp_path``.

PER-TEST WHY-RED / WHY-GREEN:
  T1  RED today  -- fiat makes is_populated(documents, DocCurrency) True on an F5
                    workbook whose "Source currency" column is present but all-empty.
  T2  RED today  -- same fiat, same shape, on the sales reader with an all-empty
                    "Currency" column.
  T3  GREEN today AND after -- the golden 11-row coverage_status() literal over BOTH
                    committed fixtures. A GUARD PIN: it is the byte-identity claim.
  T4  GREEN today AND after -- NO_GST_REG reason asserted BY REFERENCE to the production
                    constant. A GUARD PIN against a pin that asserts dead text.
  T5  RED today  -- blanking the "Tax" column must degrade EXACTLY E2/E3/E4 (the checks
                    that read TaxTotal) and leave E1 full; fiat keeps everything full.
  T6  GREEN today AND after -- feeders/ leaf purity, AST-checked over every module
                    (the Inv-7 leg the auditor flagged as missing).
  T7  GREEN today AND after -- populatable_sides() unchanged on both readers.

HERMETIC: committed fixtures (read-only) + tmp_path-constructed variants only. No
network, no SAP (the readers dial nothing and need no env creds), no anthropic import,
no model call. Pure file parsing.

DOES NOT EDIT ANY EXISTING TEST FILE.
"""
from __future__ import annotations

import ast
import csv
import importlib
import pkgutil
from pathlib import Path

import pytest

from config.loader import load_client_config
from feeders import coverage_status as coverage_status_mod
from feeders import extract_schema as schema
from feeders.xero_f5_reader import TRANSACTIONS_SHEET, XeroF5ChainReader
from feeders.xero_sales_reader import XeroSalesInvoiceChainReader

_REPO_ROOT = Path(__file__).resolve().parents[1]

_F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)
_SALES_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
    / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
)

_DOCS = schema.DOCUMENTS_SHEET  # "documents"


# ---------------------------------------------------------------------------
# Committed-fixture readers (opened READ-ONLY; the fixtures are never rewritten).
# ---------------------------------------------------------------------------


def _committed_f5_reader() -> XeroF5ChainReader:
    return XeroF5ChainReader(_F5_FIXTURE)


def _committed_sales_reader() -> XeroSalesInvoiceChainReader:
    """The committed sales fixture, read with the xero_sales_demo config mappings."""
    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    return XeroSalesInvoiceChainReader(
        _SALES_FIXTURE,
        tax_code_mappings=cfg.effective_tax_code_mappings,
        out_of_scope_codes=cfg.out_of_scope_codes,
    )


# ---------------------------------------------------------------------------
# Constructed fixture builders (tmp_path ONLY). Both mirror the real export
# LAYOUT; ``blank_columns`` leaves a column's HEADER in place and empties every
# data cell under it -- the present-but-unpopulated shape.
# ---------------------------------------------------------------------------

# Real Xero F5 row-5 header (the 4-row title block precedes it).
_F5_HEADER = [
    "Date", "Reference", "Contact", "Description", "Tax rate",
    "Source currency", "Gross", "Net", "Tax", "Account",
]

# One sales transaction row and one purchase transaction row, so BOTH entities exist.
# "Tax rate" must be non-empty (a blank tax rate is the section-header signal) AND a
# MAPPED name (an unmapped stem fails loud by design).
_F5_SALES_ROW = {
    "Date": "2026-04-08",
    "Reference": "INV-9001",
    "Contact": "Alpha Pte Ltd",
    "Description": "Consulting services",
    "Tax rate": "Standard-Rated Supplies (9%)",
    "Source currency": "SGD",
    "Gross": 10900.0,
    "Net": 10000.0,
    "Tax": 900.0,
    "Account": "200",
}
_F5_PURCHASE_ROW = {
    "Date": "2026-05-12",
    "Reference": "BILL-9002",
    "Contact": "Beta Supplies Pte Ltd",
    "Description": "Office consumables",
    "Tax rate": "Standard-Rated Purchases (9%)",
    "Source currency": "SGD",
    "Gross": 2180.0,
    "Net": 2000.0,
    "Tax": 180.0,
    "Account": "429",
}


def _f5_workbook(tmp_path: Path, filename: str, blank_columns=()) -> Path:
    """A minimal but REAL-SHAPED Xero F5 workbook under tmp_path.

    Title block (rows 1-4, row 3 carrying the period line), row-5 header, then a Box 1
    value-box section with one sales row and a Box 5 value-box section with one purchase
    row. Every column named in ``blank_columns`` keeps its HEADER and carries "" in every
    transaction row -- present, 0%-populated.
    """
    from openpyxl import Workbook  # lazy, mirrors the reader

    blanks = set(blank_columns)

    def _cells(row: dict) -> list:
        return [("" if col in blanks else row[col]) for col in _F5_HEADER]

    wb = Workbook()
    ws = wb.active
    ws.title = TRANSACTIONS_SHEET
    ws.append(["AgentAssist Coverage Demo Pte Ltd"])
    ws.append(["Transactions by box number"])
    ws.append(["For the period Apr 1, 2026 to Jun 30, 2026"])
    ws.append([])
    ws.append(list(_F5_HEADER))
    ws.append(["Box 1 - Total value of standard-rated supplies"])
    ws.append(_cells(_F5_SALES_ROW))
    ws.append([])
    ws.append(["Box 5 - Total value of taxable purchases and imports"])
    ws.append(_cells(_F5_PURCHASE_ROW))
    ws.append([])
    out = tmp_path / filename
    wb.save(out)
    return out


# Real-FORMAT Xero sales-invoice export columns (one row per invoice LINE).
_SALES_COLUMNS = [
    "ContactName", "InvoiceNumber", "InvoiceDate", "DueDate", "Description",
    "Quantity", "UnitAmount", "AccountCode", "TaxType", "TaxAmount", "LineAmount",
    "Currency", "Total",
]

# TaxType values MUST be in the xero_sales_demo tax_code_mappings (an unmapped code
# fails loud). "Standard-Rated Supplies" -> SR, "Zero-Rated Supplies" -> ZR.
_SALES_ROWS = [
    {
        "ContactName": "Acme Pte Ltd", "InvoiceNumber": "INV-9101",
        "InvoiceDate": "2026-04-05", "DueDate": "", "Description": "Consulting services",
        "Quantity": "1", "UnitAmount": "10000", "AccountCode": "200",
        "TaxType": "Standard-Rated Supplies", "TaxAmount": "900",
        "LineAmount": "10000", "Currency": "SGD", "Total": "10900",
    },
    {
        "ContactName": "Borealis Pte Ltd", "InvoiceNumber": "INV-9102",
        "InvoiceDate": "2026-04-10", "DueDate": "", "Description": "Export goods",
        "Quantity": "1", "UnitAmount": "5000", "AccountCode": "201",
        "TaxType": "Zero-Rated Supplies", "TaxAmount": "0",
        "LineAmount": "5000", "Currency": "SGD", "Total": "5000",
    },
]


def _sales_csv(tmp_path: Path, filename: str, blank_columns=()) -> Path:
    """A minimal real-FORMAT Xero sales-invoice CSV under tmp_path.

    Every column named in ``blank_columns`` keeps its HEADER and carries "" in every data
    row -- present, 0%-populated. Only non-load-bearing columns are ever blanked here
    (``Currency`` feeds DocCurrency, which no check reads).
    """
    blanks = set(blank_columns)
    out = tmp_path / filename
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_SALES_COLUMNS)
        writer.writeheader()
        for row in _SALES_ROWS:
            writer.writerow(
                {col: ("" if col in blanks else row.get(col, "")) for col in _SALES_COLUMNS}
            )
    return out


def _sales_reader_over(path: Path) -> XeroSalesInvoiceChainReader:
    cfg = load_client_config("xero_sales_demo", check_connectivity=False)
    return XeroSalesInvoiceChainReader(
        path,
        tax_code_mappings=cfg.effective_tax_code_mappings,
        out_of_scope_codes=cfg.out_of_scope_codes,
    )


def _levels(reader) -> dict:
    return {s.check: s.level for s in reader.coverage_status()}


def _reasons(reader) -> dict:
    return {s.check: s.reason for s in reader.coverage_status()}


# ---------------------------------------------------------------------------
# T1 -- F5: a present-but-empty column reads UNPOPULATED (RED today).
# ---------------------------------------------------------------------------


def test_f5_present_but_empty_column_reads_unpopulated(tmp_path):
    """An F5 export whose "Source currency" column is present but empty in every row is
    NOT populated for documents/DocCurrency -- and therefore not covered.

    FAILS TODAY: xero_f5_reader.coverage() does ``populated = dict(fields)``, so
    DocCurrency reads populated=True purely because the FORMAT carries the column. The
    data says otherwise. This is population asserted by fiat.

    ``fields`` (header/format presence) is deliberately UNCHANGED -- is_present stays
    True. Only the observed half moves.
    """
    wb = _f5_workbook(tmp_path, "f5_blank_currency.xlsx", blank_columns=["Source currency"])
    cov = XeroF5ChainReader(wb).coverage()

    # The FORMAT fact is untouched: the column is declared present.
    assert cov.is_present(_DOCS, "DocCurrency") is True, (
        "fields stays constant-driven -- the format carries a Source currency column"
    )
    # The DATA fact: every cell was empty, so it is not populated and not covered.
    assert cov.is_populated(_DOCS, "DocCurrency") is False, (
        "a present-but-all-empty column is NOT populated -- population must be OBSERVED"
    )
    assert cov.is_covered(_DOCS, "DocCurrency") is False

    # NON-VACUITY: a genuinely-filled column still reads populated (the test is not
    # passing simply because everything went False).
    assert cov.is_populated(_DOCS, "CardName") is True
    assert cov.is_covered(_DOCS, "CardName") is True


# ---------------------------------------------------------------------------
# T2 -- sales: the same shape on the sales reader (RED today).
# ---------------------------------------------------------------------------


def test_sales_present_but_empty_column_reads_unpopulated(tmp_path):
    """A Xero sales-invoice export whose "Currency" column is present but empty in every
    row is NOT populated for documents/DocCurrency.

    FAILS TODAY: xero_sales_reader.coverage() does the identical ``populated =
    dict(fields)`` fiat, so DocCurrency reads populated=True.

    "Currency" is the safely-blankable choice: it feeds DocCurrency, which no check in
    ``coverage_status._ECHECK_LINE_FIELDS`` reads -- so the blanking isolates the
    population question from the degrade question (T5 covers the degrade side).
    """
    src = _sales_csv(tmp_path, "sales_blank_currency.csv", blank_columns=["Currency"])
    cov = _sales_reader_over(src).coverage()

    assert cov.is_present(_DOCS, "DocCurrency") is True, (
        "fields stays constant-driven -- the format carries a Currency column"
    )
    assert cov.is_populated(_DOCS, "DocCurrency") is False, (
        "a present-but-all-empty column is NOT populated -- population must be OBSERVED"
    )
    assert cov.is_covered(_DOCS, "DocCurrency") is False

    # NON-VACUITY.
    assert cov.is_populated(_DOCS, "CardName") is True
    assert cov.is_covered(_DOCS, "CardName") is True


# ---------------------------------------------------------------------------
# T3 -- GUARD PIN: the committed-fixture coverage rows are byte-identical.
# ---------------------------------------------------------------------------

# The 11 coverage rows both Xero readers emit over their COMMITTED fixtures, copied
# EXACTLY from the pre-build measurement run (em-dashes U+2014 and trailing periods
# included). This literal is GREEN TODAY AND MUST STAY GREEN AFTER THE BUILD -- it is
# the "nothing a reviewer reads changes" claim, stated as a test rather than a promise.
_GOLDEN_COVERAGE_ROWS = [
    ("DUP_CLAIM", "degraded", "NumAtCard absent or unpopulated — DUP_CLAIM under-detects."),
    (
        "NO_GST_REG",
        "unavailable",
        "FederalTaxID absent — NO_GST_REG cannot run; require supplier-master sheet at onboarding.",
    ),
    (
        "SEQ_GAP",
        "degraded",
        "company-wide document population absent — SEQ_GAP limited to within-period.",
    ),
    ("E1", "full", ""),
    ("E2", "full", ""),
    ("E3", "full", ""),
    ("E4", "full", ""),
    (
        "gst_amount_mismatch",
        "unavailable",
        "source documents (document_pdfs) absent — gst_amount_mismatch cannot run; "
        "supply source-document PDFs at onboarding.",
    ),
    (
        "correct_period",
        "unavailable",
        "source documents (document_pdfs) absent — correct_period cannot run; "
        "supply source-document PDFs at onboarding.",
    ),
    (
        "total_inconsistency",
        "unavailable",
        "source documents (document_pdfs) absent — total_inconsistency cannot run; "
        "supply source-document PDFs at onboarding.",
    ),
    (
        "reg11_supplier_gst_absent",
        "unavailable",
        "source documents (document_pdfs) absent — reg11_supplier_gst_absent cannot run; "
        "supply source-document PDFs at onboarding.",
    ),
]


@pytest.mark.parametrize("which", ["f5", "sales"])
def test_golden_committed_fixture_rows_byte_identical(which):
    """Over the COMMITTED fixtures both readers emit exactly these 11 rows, unchanged.

    GUARD PIN -- green TODAY and green AFTER. On the committed fixtures fiat and observed
    population agree on every field, so deriving population must not move a single row.
    If this reddens, the build changed what a reviewer reads, which it must not.

    The committed fixtures are opened READ-ONLY and are never regenerated by this file.
    """
    reader = _committed_f5_reader() if which == "f5" else _committed_sales_reader()
    rows = [(s.check, s.level, s.reason) for s in reader.coverage_status()]
    assert rows == _GOLDEN_COVERAGE_ROWS


# ---------------------------------------------------------------------------
# T4 -- GUARD PIN: NO_GST_REG stays unavailable, reason asserted BY REFERENCE.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["f5", "sales"])
def test_nogstreg_reason_by_reference(which):
    """NO_GST_REG stays "unavailable" and carries the PRODUCTION reason constant.

    Asserted BY REFERENCE to ``feeders.coverage_status._NO_GST_REG_UNAVAILABLE``, never as
    a hand-copied literal: a hand-copied literal is exactly how a pin ends up asserting
    DEAD TEXT while production quietly rewords the sentence a reviewer actually sees --
    the R11 defect. Referencing the constant makes the pin track the production string.

    GUARD PIN -- green today and after. FederalTaxID is uncovered on both Xero formats
    before and after the build (no supplier master exists in either export), so deriving
    population must not resurrect it.
    """
    reader = _committed_f5_reader() if which == "f5" else _committed_sales_reader()
    row = next(s for s in reader.coverage_status() if s.check == "NO_GST_REG")

    assert row.level == "unavailable"
    assert row.reason == coverage_status_mod._NO_GST_REG_UNAVAILABLE
    # The underlying coverage fact the status is derived from, also unchanged.
    cov = reader.coverage()
    assert cov.is_covered(schema.BUSINESS_PARTNERS_SHEET, "FederalTaxID") is False


# ---------------------------------------------------------------------------
# T5 -- symmetry: blanking degrades EXACTLY the checks that read the field (RED today).
# ---------------------------------------------------------------------------


def test_symmetry_blanking_degrades_exactly_the_reading_checks(tmp_path):
    """Blanking a column degrades exactly the checks that READ it -- no more, no less.

    Blanking "Tax" (-> line TaxTotal) must degrade E2/E3/E4 with a reason NAMING TaxTotal,
    and must leave E1 FULL: per ``coverage_status._ECHECK_LINE_FIELDS`` E1 reads only
    VatGroup + LineTotal. Blanking "Source currency" (-> DocCurrency) must degrade NO
    E-check at all, because no check reads DocCurrency.

    FAILS TODAY: with population asserted by fiat, every line field reads populated
    regardless of the data, so all four E-checks stay "full" in the blanked-Tax workbook.

    The two halves together are the symmetry claim: the derivation must be sensitive to
    exactly the fields the checks declare, and insensitive to the ones they do not.
    """
    # -- half 1: blanking Tax degrades the TaxTotal readers (E2, E3, E4) only ----------
    tax_blank = _f5_workbook(tmp_path, "f5_blank_tax.xlsx", blank_columns=["Tax"])
    tax_reader = XeroF5ChainReader(tax_blank)
    tax_cov = tax_reader.coverage()

    assert tax_cov.is_present(_DOCS, "TaxTotal") is True, "format fact unchanged"
    assert tax_cov.is_populated(_DOCS, "TaxTotal") is False, (
        "every Tax cell was empty -- TaxTotal is present but unpopulated"
    )
    # The other two line fields are genuinely populated (isolates the degrade to TaxTotal).
    assert tax_cov.is_populated(_DOCS, "VatGroup") is True
    assert tax_cov.is_populated(_DOCS, "LineTotal") is True

    tax_levels = _levels(tax_reader)
    tax_reasons = _reasons(tax_reader)

    assert tax_levels["E1"] == "full", "E1 reads VatGroup+LineTotal only -- untouched"
    assert tax_reasons["E1"] == "", "a full status carries no reason"

    assert tax_levels["E2"] == "degraded"
    assert "TaxTotal" in tax_reasons["E2"], "the reason names the missing field"
    assert tax_levels["E3"] == "degraded"
    assert "TaxTotal" in tax_reasons["E3"]
    assert tax_levels["E4"] == "degraded"
    assert "TaxTotal" in tax_reasons["E4"]

    # -- half 2: blanking Source currency degrades NOTHING -----------------------------
    ccy_blank = _f5_workbook(
        tmp_path, "f5_blank_ccy_symmetry.xlsx", blank_columns=["Source currency"]
    )
    ccy_reader = XeroF5ChainReader(ccy_blank)
    assert ccy_reader.coverage().is_populated(_DOCS, "DocCurrency") is False

    ccy_levels = _levels(ccy_reader)
    assert ccy_levels["E1"] == "full", "no check reads DocCurrency"
    assert ccy_levels["E2"] == "full", "no check reads DocCurrency"
    assert ccy_levels["E3"] == "full", "no check reads DocCurrency"
    assert ccy_levels["E4"] == "full", "no check reads DocCurrency"


# ---------------------------------------------------------------------------
# T6 -- GUARD PIN: feeders/ is a LEAF (AST-checked, every module, lazy imports too).
# ---------------------------------------------------------------------------

# Top-level package names feeders must never import, in any module, at any nesting depth.
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {"anthropic", "agent", "engine", "orchestrator", "reasoning", "documents"}
)


def _feeders_source_files() -> list:
    """Every module file under feeders/, auto-discovered -- NO hardcoded list."""
    feeders_pkg = importlib.import_module("feeders")
    pkg_dir = Path(feeders_pkg.__path__[0])
    files = [pkg_dir / "__init__.py"]  # the package file itself (iter_modules omits it)
    for info in pkgutil.iter_modules(feeders_pkg.__path__):
        candidate = pkg_dir / (
            f"{info.name}/__init__.py" if info.ispkg else f"{info.name}.py"
        )
        files.append(candidate)
    return [f for f in files if f.exists()]


def _imported_roots(source: str) -> set:
    """Every top-level package name imported anywhere in ``source``.

    Walks the WHOLE tree, so a lazy import nested inside a function or a ``try`` block is
    caught just like a module-level one -- the loophole a plain header grep leaves open.
    Relative imports (level > 0) are sibling imports and are not package roots.
    """
    roots: set = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_feeders_leaf_purity_ast():
    """No module under feeders/ imports anthropic, agent, engine, orchestrator,
    reasoning or documents -- at module level OR lazily inside a function.

    GUARD PIN -- green today and after. This is Invariant 1's missing leg for the feeders
    package: the CI import-scan greps orchestrator/ only, and a grep cannot see an import
    indented inside a function body. The build adds document-walking code to two feeder
    modules, which is exactly the moment an upward import would be convenient.

    Discovery is automatic (pkgutil over feeders.__path__), so a NEW feeder module is
    covered the day it is added -- a hardcoded list would silently exempt it.
    """
    files = _feeders_source_files()
    assert len(files) >= 6, f"auto-discovery found too few feeder modules: {files}"

    violations = []
    for path in files:
        roots = _imported_roots(path.read_text(encoding="utf-8"))
        for bad in sorted(roots & _FORBIDDEN_IMPORT_ROOTS):
            violations.append(f"{path.name} imports {bad}")
    assert violations == [], (
        "feeders/ must stay a LEAF (no upward or SDK imports): " + "; ".join(violations)
    )


# ---------------------------------------------------------------------------
# T7 -- GUARD PIN: populatable_sides() is unchanged on both readers.
# ---------------------------------------------------------------------------


def test_populatable_sides_unchanged():
    """The F3 sweep's requirement stays satisfied: both readers expose a CALLABLE
    ``populatable_sides()`` returning the same frozensets as before.

    GUARD PIN -- green today and after. populatable_sides is a FORMAT-capability fact
    (which F5 sides the export shape can carry); deriving population is a CONTENT fact and
    must not leak into it. In particular the F5 reader must keep declaring "purchase" even
    when a period carries no purchase rows -- capability, not emptiness, drives the render
    marker (open item #48).
    """
    assert callable(getattr(XeroF5ChainReader, "populatable_sides", None))
    assert callable(getattr(XeroSalesInvoiceChainReader, "populatable_sides", None))

    assert _committed_f5_reader().populatable_sides() == frozenset({"sales", "purchase"})
    assert _committed_sales_reader().populatable_sides() == frozenset({"sales"})
