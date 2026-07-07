"""Empty companion: header-only ``bills.fallbacks.csv`` when NO bill falls back.

Companion to ``test_xero_bills_invoicenumber.py``. That file asserts the *demo* path,
where SBODEMOSG has ``NumAtCard`` null on all 34 bills, so every bill falls back to
``DocNum`` and the companion file is fully populated. The opposite path — the
real-client-first case where *every* bill carries a supplier reference, so ZERO bills
fall back and ``bills.fallbacks.csv`` is emitted header-only — is code-correct but
cannot be reached on the demo fixture. This closes that coverage gap with a synthetic
capture in which every bill has a non-empty ``NumAtCard``.

Characterisation of existing-correct behaviour: passes on first run (no source change).
New file (append-only); edits no existing locked test.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from exports import xero_export as xe


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


def _write_capture(capture_dir, purchases, sales=None):
    """Materialise a synthetic raw capture the RawCaptureReader can read back."""
    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / "invoices.raw.json").write_text(
        json.dumps(sales or []), encoding="utf-8"
    )
    (capture_dir / "purchase-invoices.raw.json").write_text(
        json.dumps(purchases), encoding="utf-8"
    )
    return capture_dir


def test_bills_fallbacks_header_only_when_no_bill_falls_back(tmp_path):
    """Every bill has a supplier ref → zero fallbacks → header-only companion file."""
    capture = _write_capture(
        tmp_path / "capture",
        purchases=[
            _bill(801, "SUP-A-001"),
            _bill(802, "SUP-B-002", card="Beta Supplier"),
            _bill(803, "  SUP-C-003  "),  # non-empty after strip → still not a fallback
        ],
    )
    paths = xe.export_all(capture, tmp_path / "out")

    # The companion path is always returned and the file always written.
    assert "bills_fallbacks" in paths
    fb = Path(paths["bills_fallbacks"])
    assert fb.exists()

    with fb.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))

    assert rows[0] == xe.FALLBACK_COLUMNS   # header present (writeheader unconditional)
    assert len(rows) == 1                    # header only — zero data rows
