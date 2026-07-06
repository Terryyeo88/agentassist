"""Column-spec proof for the outbound Xero export tool (PR #88 amendment).

Xero import requires the FULL template column set, in Xero's exact order, with
unused columns present-but-blank. This file pins INVOICE_COLUMNS / BILL_COLUMNS to
the full ordered template sets AND proves the *emitted* header row matches them
byte-for-byte — the load-bearing check the required-columns-only build lacked.

Target headers are Collin's three real Xero template files (NOT in-repo). They are
transcribed here verbatim; if the three CSVs are later dropped into the tree, assert
these constants against the files' header rows programmatically.

Scope fence: this is a COLUMN-SPEC proof only. It re-pins the ruled behaviours
(zero-qty → Quantity=1/UnitAmount=line-net, AccountCode BLANK, flag-and-halt) so the
widening cannot silently regress them.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from exports import xero_crosswalk as xw
from exports import xero_export as xe

_REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

# --- Target template headers (verbatim from Collin's real Xero template files) ---
INVOICE_TEMPLATE = [
    "ContactName", "EmailAddress", "POAddressLine1", "POAddressLine2",
    "POAddressLine3", "POAddressLine4", "POCity", "PORegion", "POPostalCode",
    "POCountry", "InvoiceNumber", "Reference", "InvoiceDate", "DueDate", "Total",
    "InventoryItemCode", "Description", "Quantity", "UnitAmount", "Discount",
    "AccountCode", "TaxType", "TaxAmount", "TrackingName1", "TrackingOption1",
    "TrackingName2", "TrackingOption2", "Currency", "BrandingTheme",
]
BILL_TEMPLATE = [
    "ContactName", "EmailAddress", "POAddressLine1", "POAddressLine2",
    "POAddressLine3", "POAddressLine4", "POCity", "PORegion", "POPostalCode",
    "POCountry", "InvoiceNumber", "InvoiceDate", "DueDate", "Total",
    "InventoryItemCode", "Description", "Quantity", "UnitAmount", "AccountCode",
    "TaxType", "TaxAmount", "TrackingName1", "TrackingOption1", "TrackingName2",
    "TrackingOption2", "Currency",
]

# The SAP-derived columns (everything else is emitted blank).
_SOURCED = {
    "ContactName", "InvoiceNumber", "InvoiceDate", "DueDate",
    "Description", "Quantity", "UnitAmount", "TaxType",
}


def test_invoice_columns_is_full_29_col_template():
    assert xe.INVOICE_COLUMNS == INVOICE_TEMPLATE
    assert len(xe.INVOICE_COLUMNS) == 29


def test_bill_columns_is_full_26_col_template():
    assert xe.BILL_COLUMNS == BILL_TEMPLATE
    assert len(xe.BILL_COLUMNS) == 26


def _emit(tmp_path):
    return xe.export_all(CAPTURE_DIR, tmp_path)


def test_emitted_invoice_header_matches_template_byte_for_byte(tmp_path):
    paths = _emit(tmp_path)
    raw_first_line = Path(paths["invoices"]).read_bytes().split(b"\r\n", 1)[0]
    assert raw_first_line == ",".join(INVOICE_TEMPLATE).encode("utf-8")
    with open(paths["invoices"], "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == INVOICE_TEMPLATE


def test_emitted_bill_header_matches_template_byte_for_byte(tmp_path):
    paths = _emit(tmp_path)
    raw_first_line = Path(paths["bills"]).read_bytes().split(b"\r\n", 1)[0]
    assert raw_first_line == ",".join(BILL_TEMPLATE).encode("utf-8")
    with open(paths["bills"], "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == BILL_TEMPLATE


def test_sap_values_land_in_correct_columns_others_blank(tmp_path):
    paths = _emit(tmp_path)
    with open(paths["invoices"], "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    # First invoice line is DocNum 356 (Maxi-Teq, SO→SR, zero-qty service line).
    r0 = rows[0]
    assert r0["ContactName"] == "Maxi-Teq"
    assert r0["InvoiceNumber"] == "356"
    assert r0["InvoiceDate"] == "05/08/2024"   # DocDate
    assert r0["DueDate"] == "05/09/2024"       # DocDueDate → DueDate
    assert r0["Description"] == "Stationery need for Planning"  # ItemDescription
    assert r0["TaxType"] == "SR"               # VatGroup SO → Annex E SR
    # Every non-sourced column is emitted blank on every row (both templates).
    for path_key, cols in (("invoices", xe.INVOICE_COLUMNS), ("bills", xe.BILL_COLUMNS)):
        with open(paths[path_key], "r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                for col in cols:
                    if col not in _SOURCED:
                        assert row[col] == "", f"{path_key}:{col} must be blank"


# --- Regression pins: ruled behaviours survive the widening -----------------

def test_zero_qty_row_still_qty_one_unit_net_in_correct_columns(tmp_path):
    paths = _emit(tmp_path)
    with open(paths["invoices"], "r", encoding="utf-8", newline="") as fh:
        r0 = next(csv.DictReader(fh))  # DocNum 356, the zero-qty service line
    assert r0["Quantity"] == "1"
    assert r0["UnitAmount"] == "200"           # line net (LineTotal)
    assert float(r0["Quantity"]) * float(r0["UnitAmount"]) == pytest.approx(200.0)
    assert r0["AccountCode"] == ""             # BLANK by ruling


def test_account_code_blank_across_all_rows(tmp_path):
    paths = _emit(tmp_path)
    for key in ("invoices", "bills"):
        with open(paths[key], "r", encoding="utf-8", newline="") as fh:
            assert all(row["AccountCode"] == "" for row in csv.DictReader(fh))


def test_unmapped_code_still_flags_and_halts():
    with pytest.raises(xw.UnmappedTaxCodeError):
        xw.to_annex_e("ZZZ")


# --- Contacts: FLAG for Terry, do NOT expand here ---------------------------
# The real Xero Contacts import template is 73 columns. Whether Xero accepts a
# single-ContactName contacts import is an OPEN confirm for Terry — this fix
# deliberately does NOT guess Xero's tolerance and leaves Contacts at 1 column.
def test_contacts_stays_single_column_pending_terry():
    assert xe.CONTACT_COLUMNS == ["ContactName"]  # TODO(Terry): 73-col template?
