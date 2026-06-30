"""PR-A — real-FORMAT Xero F5 reader: failing-first tests (written BEFORE the module exists).

Per the build SOP these tests are authored against ``feeders/xero_f5_reader.py`` BEFORE that
module is implemented, so collection FAILS at import for the right reason (the module/class is
absent — NOT a typo). They lock the three NEW real-format rules of the Xero "Transactions by box
number" export reader, each asserted in a dedicated test (three-times rule: prompt + code + test):

  1. ``parse_tax_rate``        — strip the LAST trailing " (NN%)" suffix Xero appends.
  2. ``tax_rate_to_vat_group`` — the PROPOSED/UNVALIDATED name-stem → VatGroup mapping.
  3. ``XeroF5ChainReader``     — value-box-only structural selection over the real sheet
                                 (tax-box sections re-list rows and are SKIPPED — no hash dedupe).

SCOPE / HONESTY (T2.11):
  * real-FORMAT, SYNTHETIC-DATA: the fixture mirrors a genuine Xero IRAS-F5 export LAYOUT but
    carries hand-authored synthetic transactions. This is NOT a real client file and asserts NO
    GST/accuracy verdict — only that the reader reproduces the canonical shaped surfaces.
  * The ``tax_rate_to_vat_group`` mapping is PROPOSED / UNVALIDATED (DEBT-1: IRAS citations
    deferred). The mapping assertions below pin the LOCKED PROPOSED behaviour — a candidate, not
    a verdict.

Pure stdlib + pytest (+ openpyxl, lazily, inside the reader). No anthropic, no engine/reasoning.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Import the not-yet-existing module under test. Until PR-A is built this import fails at
# COLLECTION — by design (module/class absent), the failing-first signal the SOP requires.
from feeders.xero_f5_reader import (
    XeroF5ChainReader,
    parse_tax_rate,
    tax_rate_to_vat_group,
)

# Coverage-status vocabulary is read from the REAL emitter — do not invent status strings.
from feeders.coverage_status import FULL

# Fixture resolved relative to the repo root via pathlib (NOT an absolute path).
_REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)

PERIOD_START = "2026-04-01"
PERIOD_END = "2026-06-30"


# ---------------------------------------------------------------------------
# Ground-truth value-box transactions (what the reader MUST yield).
# ---------------------------------------------------------------------------

# (DocNum, CardName, VatGroup, LineTotal, TaxTotal)
SALES_INVOICES = [
    ("INV-2001", "Acme Pte Ltd", "SR", 10000.0, 900.0),
    ("INV-2002", "Borealis Pte Ltd", "SR", 5000.0, 0.0),
    ("INV-2003", "Cresco Pte Ltd", "ZR", 3000.0, 270.0),
]
PURCHASE_INVOICES = [
    ("BILL-3001", "GoodVendor Pte Ltd", "TX", 2000.0, 180.0),
    ("BILL-3002", "OldRate Supplies Pte Ltd", "TX", 4000.0, 320.0),
    ("BILL-3003", "NoReg Trading", "TX", 1500.0, 135.0),
    ("BILL-3004", "DupSupplier Pte Ltd", "TX", 2500.0, 225.0),
    ("BILL-3005", "DupSupplier Pte Ltd", "TX", 2500.0, 225.0),
    ("BILL-3006", "Marina Fine Dining Pte Ltd", "TX", 800.0, 72.0),
    ("BILL-3007", "AutoCare SG Pte Ltd", "TX", 1200.0, 108.0),
]


def _reader():
    return XeroF5ChainReader(FIXTURE)


def _docnums(docs):
    return [str(d.get("DocNum")) for d in docs]


def _only_line(doc):
    """The single canonical line of a one-line value-box document."""
    lines = doc["DocumentLines"]
    assert len(lines) == 1, f"expected one line, got {len(lines)} for {doc.get('DocNum')!r}"
    return lines[0]


def _by_docnum(docs):
    return {str(d.get("DocNum")): d for d in docs}


# ---------------------------------------------------------------------------
# Rule 1 — parse_tax_rate: strip the LAST trailing " (NN%)" suffix only.
# ---------------------------------------------------------------------------


def test_parse_tax_rate_strips_last_suffix_all_cases():
    """parse_tax_rate trims whitespace, strips ONLY the last ' (NN%)', returns (name, fraction)."""
    assert parse_tax_rate("Standard-Rated Supplies (9%)") == ("Standard-Rated Supplies", 0.09)
    # Double-suffix: strip only the LAST token; the earlier "(0%)" stays in the name.
    assert parse_tax_rate("SR-NoGST (0%) [test] (0%)") == ("SR-NoGST (0%) [test]", 0.0)
    # Leading space is trimmed; last-suffix-only on a double suffix.
    assert parse_tax_rate(" ZR-Broken (9%) [test] (9%)") == ("ZR-Broken (9%) [test]", 0.09)
    assert parse_tax_rate("SI-Stale (8%) [test] (8%)") == ("SI-Stale (8%) [test]", 0.08)
    assert parse_tax_rate("Standard-Rated Purchases (9%)") == ("Standard-Rated Purchases", 0.09)


# ---------------------------------------------------------------------------
# Rule 2 — tax_rate_to_vat_group: PROPOSED/UNVALIDATED stem → VatGroup (DEBT-1).
# ---------------------------------------------------------------------------


def test_tax_rate_to_vat_group_proposed_mapping():
    """LOCKED PROPOSED mapping (DEBT-1, IRAS deferred): name-stem → VatGroup code. Candidate only."""
    assert tax_rate_to_vat_group("Standard-Rated Supplies (9%)") == "SR"
    assert tax_rate_to_vat_group("SR-NoGST (0%) [test] (0%)") == "SR"
    assert tax_rate_to_vat_group(" ZR-Broken (9%) [test] (9%)") == "ZR"
    assert tax_rate_to_vat_group("Standard-Rated Purchases (9%)") == "TX"
    assert tax_rate_to_vat_group("SI-Stale (8%) [test] (8%)") == "TX"


# ---------------------------------------------------------------------------
# Rule 3 — XeroF5ChainReader over the real "Transactions by box number" sheet.
# ---------------------------------------------------------------------------


def test_reader_loads_real_fixture_without_error():
    """Loading the real export succeeds — proves title-block skip / row-5 header detection.

    A naive row-1-header reader would mis-parse the Xero title block; a clean load that yields
    the known value-box counts is the structural proof the header row is found correctly.
    """
    reader = _reader()
    assert reader is not None
    # A clean load is observable through the value-box counts being the known ground truth.
    assert reader.count("Invoices", PERIOD_START, PERIOD_END) == 3
    assert reader.count("PurchaseInvoices", PERIOD_START, PERIOD_END) == 7


def test_count_selects_value_boxes_only():
    """count() reflects value-box selection: 3 sales invoices, 7 purchase invoices."""
    reader = _reader()
    assert reader.count("Invoices", PERIOD_START, PERIOD_END) == 3
    assert reader.count("PurchaseInvoices", PERIOD_START, PERIOD_END) == 7


def test_structural_dedupe_excludes_tax_box_relists():
    """Total logical docs == 10 (NOT 19): tax-box (Box 6/7) re-lists are SKIPPED, not hashed.

    The value boxes carry each transaction once; the tax boxes re-list 2 std supplies + 7
    purchases (9 extra rows → 19 if naively concatenated). The reader extracts only value boxes,
    so the total is 3 + 7 = 10 and no value-box row is duplicated.
    """
    reader = _reader()
    sales = reader.fetch_invoices("Invoices", PERIOD_START, PERIOD_END)
    purch = reader.fetch_invoices("PurchaseInvoices", PERIOD_START, PERIOD_END)

    assert len(sales) + len(purch) == 10
    assert len(sales) + len(purch) != 19

    sales_nums = _docnums(sales)
    # INV-2001 is re-listed under Box 6 (output tax) — it must NOT appear twice.
    assert sales_nums.count("INV-2001") == 1
    assert len(sales_nums) == len(set(sales_nums))


def test_dupsupplier_pair_both_survive_anti_undercount():
    """Both look-alike-but-distinct DupSupplier purchase invoices survive (no over-dedupe).

    BILL-3004 (quotation) and BILL-3005 (tax invoice) share CardName/LineTotal/TaxTotal. Structural
    value-box selection keeps BOTH — a content-hash dedupe would wrongly collapse them (undercount).
    """
    purch = reader_purch = _reader().fetch_invoices("PurchaseInvoices", PERIOD_START, PERIOD_END)
    by_num = _by_docnum(purch)

    assert "BILL-3004" in by_num
    assert "BILL-3005" in by_num

    look_alikes = []
    for doc in purch:
        line = _only_line(doc)
        if line["LineTotal"] == 2500.0 and line["TaxTotal"] == 225.0:
            look_alikes.append(str(doc.get("DocNum")))
    assert sorted(look_alikes) == ["BILL-3004", "BILL-3005"]
    assert by_num["BILL-3004"]["CardName"] == "DupSupplier Pte Ltd"
    assert by_num["BILL-3005"]["CardName"] == "DupSupplier Pte Ltd"


def test_fetch_invoices_line_shape_and_carried_header():
    """Each doc carries DocumentLines of {VatGroup, LineTotal, TaxTotal}; CardName is carried."""
    reader = _reader()
    sales = _by_docnum(reader.fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
    purch = _by_docnum(reader.fetch_invoices("PurchaseInvoices", PERIOD_START, PERIOD_END))

    # Every doc on both surfaces has the canonical line shape.
    for doc in list(sales.values()) + list(purch.values()):
        for line in doc["DocumentLines"]:
            assert set(line.keys()) >= {"VatGroup", "LineTotal", "TaxTotal"}

    inv = sales["INV-2001"]
    assert inv["CardName"] == "Acme Pte Ltd"
    inv_line = _only_line(inv)
    assert inv_line["VatGroup"] == "SR"
    assert inv_line["LineTotal"] == 10000.0
    assert inv_line["TaxTotal"] == 900.0

    bill = purch["BILL-3001"]
    assert bill["CardName"] == "GoodVendor Pte Ltd"
    bill_line = _only_line(bill)
    assert bill_line["VatGroup"] == "TX"
    assert bill_line["LineTotal"] == 2000.0
    assert bill_line["TaxTotal"] == 180.0


def test_absent_surfaces_are_honest():
    """No BP master, no listing surface in a Xero export — degrade honestly, never fabricate.

    * get_business_partner raises KeyError (no supplier master in a Xero export).
    * fetch_listing returns the four canonical buckets, all EMPTY.
    * coverage_status() marks the BP/listing-dependent checks as NOT 'full' (degraded/unavailable),
      asserted against the REAL coverage_status vocabulary (feeders/coverage_status.py).
    """
    reader = _reader()

    with pytest.raises(KeyError):
        reader.get_business_partner("BILL-3001")

    listing = reader.fetch_listing({"start": PERIOD_START, "end": PERIOD_END})
    expected_buckets = {
        "period_sales_headers",
        "period_purch_headers",
        "all_sales_headers",
        "all_purch_headers",
    }
    assert set(listing.keys()) == expected_buckets
    for bucket in expected_buckets:
        assert listing[bucket] == []

    statuses = {cs.check: cs.level for cs in reader.coverage_status()}
    # BP/listing-dependent checks must NOT read as 'full' (covered) over a listing-less export.
    for check in ("NO_GST_REG", "DUP_CLAIM", "SEQ_GAP"):
        assert check in statuses
        assert statuses[check] != FULL
