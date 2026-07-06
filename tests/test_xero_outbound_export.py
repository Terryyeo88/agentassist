"""Outbound Xero export tool — SAP B1 raw capture → Xero import CSVs.

Failing-test-first coverage (append-only; new file) for the SEPARATE outbound tool
that re-shapes the FULL raw SAP capture (tests/fixtures/sbodemosg-extract/*.raw.json)
into Xero import CSVs for the Invoices / Bills / Contacts templates.

Design under test (Terry-ruled, translation-only — never corrects a value):
  * TaxType = line VatGroup → SAP→Annex-E crosswalk (emits the Annex E code); an
    unmapped SAP code FLAGS-AND-HALTS, never guesses/defaults.
  * AccountCode emitted BLANK (client fills in Xero).
  * Zero-quantity line → Quantity=1 AND UnitAmount=line-net (qty×unit == line total);
    non-zero → Quantity pass-through, UnitAmount=UnitPrice.
  * SAP ISO date → Xero DD/MM/YYYY.
  * Column order/presence matches each template exactly (AccountCode present-but-blank).
  * Contacts dedup: same CardName collapses to one row.

Honest status: DEMO/synthetic-format only (SBODEMOSG). NOT real-client-export validated.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from exports import xero_crosswalk as xw
from exports import xero_export as xe

_REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"


# ---------------------------------------------------------------------------
# Crosswalk — the 18 Terry-authored SAP→Annex-E rows + flag-and-halt on unknown.
# ---------------------------------------------------------------------------

_EXPECTED_CROSSWALK = {
    "SO": "SR", "ZR": "ZR", "OS": "OS", "DS": "DS", "ES33": "ES33",
    "ESN33": "ESN33", "SI": "TX", "ZP": "ZP", "EP": "EP", "OP": "OP",
    "IM": "IM", "IGDS": "IGDS", "ME": "ME", "NR": "NR", "BL": "BL",
    "TX-E33": "TX-ESS", "TX-N33": "TX-N33", "TX-RE": "TX-RE",
}


@pytest.mark.parametrize("sap_code,annex_e", sorted(_EXPECTED_CROSSWALK.items()))
def test_crosswalk_maps_each_sap_code_to_annex_e(sap_code, annex_e):
    assert xw.to_annex_e(sap_code) == annex_e


def test_crosswalk_covers_exactly_the_eighteen_rows():
    assert xw.SAP_TO_ANNEX_E == _EXPECTED_CROSSWALK


def test_unmapped_code_flags_and_halts_never_defaults():
    with pytest.raises(xw.UnmappedTaxCodeError):
        xw.to_annex_e("ZZZ")
    # And it must not silently coerce blank/None to a default either.
    with pytest.raises(xw.UnmappedTaxCodeError):
        xw.to_annex_e("")


def test_crosswalk_cites_committed_annex_e_pdf():
    # In-repo IRAS traceability: the module cites the committed Annex E guide,
    # and that path really exists in the tree.
    assert xw.ANNEX_E_SOURCE == "knowledge-base/etaxguide_gst_invoicenow_requirement.pdf"
    assert (_REPO_ROOT / xw.ANNEX_E_SOURCE).exists()


# ---------------------------------------------------------------------------
# Quantity / UnitAmount rule.
# ---------------------------------------------------------------------------

def test_zero_quantity_line_becomes_qty_one_unit_equals_net():
    line = {"Quantity": 0.0, "UnitPrice": 200.0, "LineTotal": 200.0,
            "ItemDescription": "Stationery need for Planning", "VatGroup": "SO",
            "AccountCode": "640020"}
    row = xe.line_qty_unit(line)
    assert row["Quantity"] == "1"
    assert row["UnitAmount"] == "200"
    # qty × unit reconciles to the line total.
    assert float(row["Quantity"]) * float(row["UnitAmount"]) == pytest.approx(200.0)


def test_non_zero_quantity_passes_through_unit_is_unitprice():
    line = {"Quantity": 3.0, "UnitPrice": 352.5, "LineTotal": 1057.5,
            "ItemDescription": "Portable Hard Disk 1TB", "VatGroup": "SO",
            "AccountCode": "400000"}
    row = xe.line_qty_unit(line)
    assert row["Quantity"] == "3"
    assert row["UnitAmount"] == "352.5"


# ---------------------------------------------------------------------------
# Date reformat: SAP ISO → Xero DD/MM/YYYY.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("iso,expected", [
    ("2024-08-05T00:00:00Z", "05/08/2024"),
    ("2024-09-05T00:00:00Z", "05/09/2024"),
    ("2024-07-23T00:00:00Z", "23/07/2024"),
])
def test_xero_date_reformat(iso, expected):
    assert xe.xero_date(iso) == expected


# ---------------------------------------------------------------------------
# Row projection over the real raw capture.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def reader():
    return xe.RawCaptureReader(CAPTURE_DIR)


def test_account_code_emitted_blank_on_every_invoice_and_bill_row(reader):
    inv_rows = xe.build_invoice_rows(reader.fetch_invoices("Invoices"))
    bill_rows = xe.build_bill_rows(reader.fetch_invoices("PurchaseInvoices"))
    assert inv_rows and bill_rows
    assert all(r["AccountCode"] == "" for r in inv_rows)
    assert all(r["AccountCode"] == "" for r in bill_rows)


def test_taxtype_is_always_a_crosswalked_annex_e_code(reader):
    inv_rows = xe.build_invoice_rows(reader.fetch_invoices("Invoices"))
    bill_rows = xe.build_bill_rows(reader.fetch_invoices("PurchaseInvoices"))
    annex_e_values = set(_EXPECTED_CROSSWALK.values())
    assert all(r["TaxType"] in annex_e_values for r in inv_rows + bill_rows)
    # SO→SR specifically present on the sales side.
    assert any(r["TaxType"] == "SR" for r in inv_rows)
    # SI→TX specifically present on the purchase side.
    assert any(r["TaxType"] == "TX" for r in bill_rows)


# ---------------------------------------------------------------------------
# Full emit — column order / presence per template + Contacts dedup + determinism.
# ---------------------------------------------------------------------------

def _read_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def test_invoices_csv_header_matches_template_order(tmp_path, reader):
    paths = xe.export_all(CAPTURE_DIR, tmp_path)
    header, body = _read_csv(paths["invoices"])
    assert header == xe.INVOICE_COLUMNS
    assert body  # at least one line row


def test_bills_csv_header_matches_template_order(tmp_path):
    paths = xe.export_all(CAPTURE_DIR, tmp_path)
    header, body = _read_csv(paths["bills"])
    assert header == xe.BILL_COLUMNS
    assert body


def test_contacts_csv_is_name_only_and_deduped(tmp_path):
    paths = xe.export_all(CAPTURE_DIR, tmp_path)
    header, body = _read_csv(paths["contacts"])
    assert header == xe.CONTACT_COLUMNS  # ContactName only
    names = [r[0] for r in body]
    assert names == sorted(set(names), key=names.index)  # no duplicate CardName
    assert len(names) == len(set(names))


def test_export_is_byte_stable_across_two_runs(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    pa = xe.export_all(CAPTURE_DIR, a)
    pb = xe.export_all(CAPTURE_DIR, b)
    for key in ("invoices", "bills", "contacts"):
        assert Path(pa[key]).read_bytes() == Path(pb[key]).read_bytes()
