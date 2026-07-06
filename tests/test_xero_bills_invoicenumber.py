"""Bill InvoiceNumber: prefer supplier reference (NumAtCard) else DocNum + companion file.

Bill-only, Terry-approved. A Bill's Xero ``InvoiceNumber`` uses the supplier's own
reference (SAP ``NumAtCard``) when present and non-empty (after ``.strip()``), else
falls back to the internal ``DocNum``. Every fallback is recorded in a new companion
file ``bills.fallbacks.csv`` (Option A). Sales invoices are UNCHANGED (keep ``DocNum``).

This is a data-provenance/bookkeeping choice, NOT a tax-semantics claim — the crosswalk
is untouched, no IRAS citation involved.

HONEST STATUS: the prefer-``NumAtCard`` branch is proven only by the synthetic unit
cases below — SBODEMOSG has ``NumAtCard`` null on 100% of bills, so on the demo every
bill falls back to ``DocNum`` (all 34), and the prefer branch is NOT demo-exercised and
NOT real-client-validated. New file (append-only); edits no existing locked test.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from exports import xero_export as xe

_REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "sbodemosg-extract"

# Step-2 baseline SHA-256 of the three IMPORT CSVs on the frozen fixtures. The
# bill-InvoiceNumber change is byte-invisible to these on demo data (NumAtCard null
# everywhere → every bill still falls back to DocNum), so they must be UNCHANGED.
_BASELINE_SHA = {
    "invoices": "39236acbb1f9a87cffe29498cae3e02b83d4dced940f6541b6f04eef2765af45",
    "bills": "101a75e304a5293489d7ba670ca28b0e59be2fe9aa5f422765ad0f9901ba25fb",
    "contacts": "0e75934e6d96ec3702e53588c731c150b75f64ebf286a93b4a2cfa8636fa2761",
}


def _bill(docnum, numatcard, card="Acme Supplier", vat="SI"):
    """A synthetic one-line purchase document (bill) with a controllable NumAtCard."""
    return {
        "DocNum": docnum,
        "NumAtCard": numatcard,
        "CardName": card,
        "DocDate": "2024-08-05T00:00:00Z",
        "DocDueDate": "2024-09-05T00:00:00Z",
        "DocumentLines": [{
            "VatGroup": vat, "Quantity": 2.0, "UnitPrice": 50.0, "LineTotal": 100.0,
            "ItemDescription": "Widget", "AccountCode": "208040",
        }],
    }


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# 1. Prefer branch: NumAtCard present → it wins.
def test_bill_prefers_numatcard_when_present():
    rows = xe.build_bill_rows([_bill(591, "SUP-INV-001")])
    assert rows[0]["InvoiceNumber"] == "SUP-INV-001"


# 2. Fallback (None and whitespace) → DocNum, and each is recorded.
def test_bill_falls_back_to_docnum_and_records_it():
    assert xe.build_bill_rows([_bill(591, None)])[0]["InvoiceNumber"] == "591"
    assert xe.build_bill_rows([_bill(592, "   ")])[0]["InvoiceNumber"] == "592"
    fallbacks = xe.collect_bill_fallbacks([_bill(591, None), _bill(592, "   ")])
    assert [f["DocNum"] for f in fallbacks] == ["591", "592"]
    assert all(f["ContactName"] == "Acme Supplier" for f in fallbacks)
    assert all(f["Reason"] for f in fallbacks)  # a non-empty reason is recorded


def test_bill_with_supplier_ref_is_not_recorded_as_fallback():
    assert xe.collect_bill_fallbacks([_bill(591, "SUP-INV-001")]) == []


# 3. Invoices untouched — a sales invoice ignores NumAtCard, keeps DocNum.
def test_sales_invoice_invoicenumber_unchanged_ignores_numatcard():
    rows = xe.build_invoice_rows([_bill(700, "SUP-INV-XXX", card="Maxi-Teq", vat="SO")])
    assert rows[0]["InvoiceNumber"] == "700"


# 4. Companion file: header + one row per fallen-back bill; on the demo that is all 34.
def test_export_writes_bills_fallbacks_companion_file(tmp_path):
    paths = xe.export_all(CAPTURE_DIR, tmp_path)
    assert "bills_fallbacks" in paths
    with open(paths["bills_fallbacks"], "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == xe.FALLBACK_COLUMNS          # stable header
    assert len(rows) - 1 == 34                     # all 34 demo bills fall back (NumAtCard null)
    # DocNums present + reason column populated on every recorded row.
    assert all(r[0] for r in rows[1:]) and all(r[2] for r in rows[1:])


# 5. Companion file is byte-stable across two runs (document-order deterministic).
def test_bills_fallbacks_is_byte_stable(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    pa = xe.export_all(CAPTURE_DIR, a)
    pb = xe.export_all(CAPTURE_DIR, b)
    assert Path(pa["bills_fallbacks"]).read_bytes() == Path(pb["bills_fallbacks"]).read_bytes()


# 6. The three IMPORT CSVs are byte-identical to the Step-2 baseline (change is invisible).
def test_three_import_csvs_unchanged(tmp_path):
    paths = xe.export_all(CAPTURE_DIR, tmp_path)
    for key, expected in _BASELINE_SHA.items():
        assert _sha(paths[key]) == expected, f"{key}.csv changed — must stay byte-identical"
