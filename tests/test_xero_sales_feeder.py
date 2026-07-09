"""Failing-first tests for the inbound Xero SALES-INVOICE feeder (xero_sales, option-3 slice).

Authored BEFORE ``feeders/xero_sales_reader.py`` exists, so collection FAILS at import for the
right reason (the module/class is absent — the failing-first signal the build SOP requires).

Locks, each in a dedicated test (three-times rule: prompt + code + test):

  a. PARSE + GROUP — a flat one-row-per-line Xero sales export (CSV and XLSX) groups by
     InvoiceNumber into canonical documents; a MULTI-LINE invoice (repeated InvoiceNumber)
     becomes ONE document with ordered lines and a synthesized line_index.
  b. MAPPING VIA YAML — TaxType resolves to VatGroup through the client-YAML tax_code_mappings
     passed into the reader (NEVER a hardcoded reader table — no repeat of XeroF5's DEBT-1).
  c. OUT-OF-SCOPE — an out_of_scope_codes line ("No Tax") is ACCEPTED, EXCLUDED from GST
     categorisation, and its count/reason surfaces visibly (never silent).
  d. FAIL-LOUD — a TaxType in NEITHER tax_code_mappings NOR out_of_scope_codes raises
     ValueError naming the code.
  e. ABSENT SURFACES — credit notes / purchases / BP master / listing degrade honestly via the
     EXISTING coverage seam (mirrors xero_f5_reader.py's booleans).
  f. DOCNUM-AS-STRING — a non-numeric InvoiceNumber (INV-2001) is carried as a string (XeroF5
     treatment); SEQ_GAP degrades accordingly.
  g. ROUTER — the detector recognises the sales-invoice shape; an F5 workbook still routes to
     XeroF5; a three-sheet extract workbook still routes to ExtractChainReader (precedence).
  h. PARKED-CODE EXPOSURE — a line whose TaxType is one of the 13 PARKED codes ("Reverse
     charge: taxable supply @ 9%") fails loud (documented behaviour until T2.21 resumes).

HONEST STATUS (T2.11): real-Xero-FORMAT parsing over SYNTHETIC content — NOT a real client
export, NOT accuracy-validated. The mapping is Terry-authored (IRAS Annex E); values are read
from config, never authored here.

Pure stdlib + pytest (+ openpyxl, lazily, in the reader / fixture builder). No anthropic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Import the not-yet-existing module + detector under test. Until the build lands this import
# fails at COLLECTION — by design (the failing-first signal the SOP requires).
from feeders.xero_sales_reader import XeroSalesInvoiceChainReader

from config.loader import load_client_config
from feeders.coverage_status import DEGRADED, UNAVAILABLE
from tests.synth_xero_sales_export import DEMO_ROWS, write_csv, write_xlsx

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "xero-sales-export"
FIXTURE_XLSX = _FIXTURE_DIR / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.xlsx"
FIXTURE_CSV = _FIXTURE_DIR / "AgentAssist_Xero_SalesInvoices_2026-04-01_to_2026-06-30.csv"

F5_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "xero-f5-export"
    / "AgentAssist_IRAS_F5_2026-04-01_to_2026-06-30.xlsx"
)

PERIOD_START = "2026-04-01"
PERIOD_END = "2026-06-30"


def _cfg():
    """The committed xero_sales demo config (also proves the YAML loads clean)."""
    return load_client_config("xero_sales_demo", check_connectivity=False)


def _reader(source=FIXTURE_XLSX):
    cfg = _cfg()
    return XeroSalesInvoiceChainReader(
        source,
        tax_code_mappings=cfg.effective_tax_code_mappings,
        out_of_scope_codes=cfg.out_of_scope_codes,
    )


def _by_docnum(docs):
    return {str(d.get("DocNum")): d for d in docs}


# ---------------------------------------------------------------------------
# a. PARSE + GROUP (CSV and XLSX), multi-line invoice grouping.
# ---------------------------------------------------------------------------


def test_parse_groups_multiline_invoice_csv_and_xlsx_agree():
    """CSV and XLSX parse identically; INV-2001 groups two rows into ONE ordered-line doc."""
    for source in (FIXTURE_XLSX, FIXTURE_CSV):
        reader = _reader(source)
        sales = _by_docnum(reader.fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
        # 3 distinct invoices from 5 rows (INV-2001 repeats).
        assert set(sales) == {"INV-2001", "INV-2002", "INV-2003"}, f"source={source}"

        inv1 = sales["INV-2001"]
        # Multi-line: two lines under one document, in first-seen order.
        assert len(inv1["DocumentLines"]) == 2, f"source={source}"
        assert inv1["CardName"] == "Acme Pte Ltd"
        assert inv1["DocCurrency"] == "SGD"
        assert inv1["DocTotal"] == 21800.0
        for line in inv1["DocumentLines"]:
            assert set(line.keys()) >= {"VatGroup", "LineTotal", "TaxTotal"}
            assert line["LineTotal"] == 10000.0
            assert line["TaxTotal"] == 900.0


def test_count_reflects_grouped_sales_documents():
    """count() is the TRUE grouped sales-invoice count (3), not the 5 flat rows."""
    reader = _reader()
    assert reader.count("Invoices", PERIOD_START, PERIOD_END) == 3


# ---------------------------------------------------------------------------
# b. MAPPING VIA YAML — resolved through the passed tax_code_mappings, not hardcoded.
# ---------------------------------------------------------------------------


def test_taxtype_maps_to_vatgroup_via_client_yaml():
    """VatGroup comes from the client-YAML mapping: SR for supplies, ZR for zero-rated."""
    reader = _reader()
    sales = _by_docnum(reader.fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
    assert sales["INV-2001"]["DocumentLines"][0]["VatGroup"] == "SR"
    assert sales["INV-2002"]["DocumentLines"][0]["VatGroup"] == "ZR"


def test_mapping_is_not_hardcoded_in_reader():
    """The reader carries NO built-in TaxType->VatGroup table (no DEBT-1 repeat).

    An EMPTY mapping (no out_of_scope) must make EVERY line fail loud — proving the reader has
    no private fallback table; resolution is entirely the injected config's.
    """
    with pytest.raises(ValueError):
        XeroSalesInvoiceChainReader(
            FIXTURE_XLSX, tax_code_mappings={}, out_of_scope_codes=frozenset()
        )


# ---------------------------------------------------------------------------
# c. OUT-OF-SCOPE — accepted, excluded from categorisation, visibly counted.
# ---------------------------------------------------------------------------


def test_out_of_scope_line_accepted_excluded_and_counted():
    """The "No Tax" line on INV-2003 is accepted (no error), excluded, and counted visibly."""
    reader = _reader()
    sales = _by_docnum(reader.fetch_invoices("Invoices", PERIOD_START, PERIOD_END))
    # INV-2003 had 2 rows (SR + No Tax); the out-of-scope line is set aside → 1 kept line.
    assert len(sales["INV-2003"]["DocumentLines"]) == 1
    assert sales["INV-2003"]["DocumentLines"][0]["VatGroup"] == "SR"

    summary = reader.out_of_scope_summary()
    assert summary["count"] == 1
    assert summary["by_code"] == {"NO TAX": 1}
    assert summary["reason"], "out-of-scope note must carry a non-empty, visible reason"


# ---------------------------------------------------------------------------
# d. FAIL-LOUD — unknown TaxType (neither mapped nor out-of-scope) → ValueError naming it.
# ---------------------------------------------------------------------------


def test_unknown_taxtype_fails_loud(tmp_path):
    rows = [dict(DEMO_ROWS[0])]
    rows[0]["TaxType"] = "Totally Made Up Tax Type"
    src = write_csv(tmp_path / "bad.csv", rows)
    with pytest.raises(ValueError, match="Totally Made Up Tax Type"):
        _reader(src)


# ---------------------------------------------------------------------------
# e. ABSENT SURFACES — honest degrade via the EXISTING coverage seam.
# ---------------------------------------------------------------------------


def test_absent_surfaces_degrade_honestly():
    reader = _reader()

    assert reader.count("PurchaseInvoices", PERIOD_START, PERIOD_END) == 0
    assert reader.fetch_credit_notes("sales", PERIOD_START, PERIOD_END) == []

    with pytest.raises(KeyError):
        reader.get_business_partner("INV-2001")

    listing = reader.fetch_listing({"start": PERIOD_START, "end": PERIOD_END})
    assert set(listing.keys()) == {
        "period_sales_headers", "period_purch_headers",
        "all_sales_headers", "all_purch_headers",
    }
    assert all(bucket == [] for bucket in listing.values())

    by_check = {s.check: s for s in reader.coverage_status()}
    assert by_check["NO_GST_REG"].level == UNAVAILABLE
    assert by_check["DUP_CLAIM"].level == DEGRADED
    assert by_check["SEQ_GAP"].level == DEGRADED


# ---------------------------------------------------------------------------
# f. DOCNUM-AS-STRING — non-numeric InvoiceNumber carried as a string.
# ---------------------------------------------------------------------------


def test_docnum_carried_as_string():
    reader = _reader()
    sales = reader.fetch_invoices("Invoices", PERIOD_START, PERIOD_END)
    docnums = [d["DocNum"] for d in sales]
    assert "INV-2001" in docnums
    for dn in docnums:
        assert isinstance(dn, str)


# ---------------------------------------------------------------------------
# g. ROUTER — detector precedence: sales vs F5 vs three-sheet extract.
# ---------------------------------------------------------------------------


def _write_extract_workbook(path: Path) -> Path:
    """A minimal three-sheet extract workbook (documents/business_partners/listing)."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "documents"
    wb["documents"].append(["doc_type", "doc_kind", "DocNum", "VatGroup", "LineTotal", "TaxTotal"])
    for name in ("business_partners", "listing"):
        ws = wb.create_sheet(name)
        ws.append(["CardCode"])
    wb.save(path)
    return path


def test_router_detects_sales_shape_with_correct_precedence(tmp_path):
    from feeders.xero_sales_reader import is_xero_sales_invoice_workbook
    from feeders.xero_f5_reader import is_xero_f5_workbook

    # The sales-invoice workbook: sales-detector YES, F5-detector NO.
    assert is_xero_sales_invoice_workbook(FIXTURE_XLSX) is True
    assert is_xero_f5_workbook(FIXTURE_XLSX) is False

    # The real F5 workbook: F5-detector YES, sales-detector NO (F5 keeps precedence).
    assert is_xero_f5_workbook(F5_FIXTURE) is True
    assert is_xero_sales_invoice_workbook(F5_FIXTURE) is False

    # A three-sheet extract workbook: neither Xero detector matches → falls to ExtractChainReader.
    extract_wb = _write_extract_workbook(tmp_path / "extract.xlsx")
    assert is_xero_f5_workbook(extract_wb) is False
    assert is_xero_sales_invoice_workbook(extract_wb) is False


# ---------------------------------------------------------------------------
# h. PARKED-CODE EXPOSURE — a parked (T2.21) code fails loud until vocabulary resumes.
# ---------------------------------------------------------------------------


def test_parked_code_fails_loud(tmp_path):
    """A PARKED code ("Reverse charge: taxable supply @ 9%") fails loud — accepted trade-off."""
    rows = [dict(DEMO_ROWS[0])]
    rows[0]["TaxType"] = "Reverse charge: taxable supply @ 9%"
    src = write_csv(tmp_path / "parked.csv", rows)
    with pytest.raises(ValueError, match="Reverse charge: taxable supply @ 9%"):
        _reader(src)
